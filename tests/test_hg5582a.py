"""HG5582A source adaptation and actual-FDT safety regressions."""
import importlib.util
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

def module(filename, name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / filename)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result

installer = module("install-hg5582a.py", "hg5582a_installer")
validator = module("validate-hg5582a.py", "hg5582a_validator")
SOURCE = pathlib.Path(os.environ.get("PONWRT_TEST_SOURCE", "/nonexistent"))
GUARD = '''
\tif [ "$board" = "fiberhome,hg5582a" ]; then
\t\t/usr/sbin/hg5582a-check-upgrade --hardware || return 1
\tfi
'''

@unittest.skipUnless((SOURCE / "target/linux/airoha").exists(), "Live cloud PonWrt source required")
class SourceAdaptationChecks(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.source = pathlib.Path(temp.name)
        for path in [
            "target/linux/airoha/dts/an7581-fiberhome-hg5382a.dts",
            "target/linux/airoha/dts/an7581-fiberhome-ubi-parts.dtsi",
            "target/linux/airoha/patches-6.18/141-mtd-rawnand-mtk-add-Airoha-EN7581-support.patch",
            "target/linux/airoha/image/an7581.mk",
            "configs/an7581.config",
            "target/linux/airoha/an7581/base-files/etc/board.d/02_network",
            "target/linux/airoha/an7581/base-files/lib/upgrade/platform.sh",
        ]:
            target = self.source / path
            target.parent.mkdir(parents=True, exist_ok=True)
            text = (SOURCE / path).read_text()
            text = text.replace(installer.BLOCK, "")
            text = text.replace("CONFIG_TARGET_DEVICE_airoha_an7581_DEVICE_fiberhome_hg5582a=y\n", "")
            if path.endswith(("02_network", "platform.sh")):
                text = text.replace("fiberhome,hg5582a|" + chr(92) + "\n\t", "")
                text = text.replace(GUARD, "")
                text = text.replace('RAMFS_COPY_DATA="${RAMFS_COPY_DATA:-} /usr/sbin/hg5582a-check-upgrade"\n', "")
            target.write_text(text)
        subprocess.run(["git", "init", "-q", str(self.source)], check=True)
        subprocess.run(["git", "-C", str(self.source), "add", "."], check=True)
        subprocess.run(["git", "-C", str(self.source), "-c", "user.name=CI",
                        "-c", "user.email=ci@example.invalid", "commit", "-qm", "fixture"], check=True)

    def test_adds_variant_without_changing_shared_hardware(self):
        shared = self.source / "target/linux/airoha/dts/an7581-fiberhome-ubi-parts.dtsi"
        before = shared.read_bytes()
        report = installer.install(self.source)
        self.assertEqual(before, shared.read_bytes())
        self.assertEqual(8, report["expected_ecc_strength"])
        self.assertFalse(report["bootloader_or_factory_embedded"])
        platform = (self.source / "target/linux/airoha/an7581/base-files/lib/upgrade/platform.sh").read_text()
        self.assertEqual(2, platform.count("fiberhome,hg5582a|"))
        self.assertEqual(2, platform.count("hg5582a-check-upgrade --hardware"))

    def test_same_adaptation_is_idempotent(self):
        installer.install(self.source)
        image = self.source / "target/linux/airoha/image/an7581.mk"
        first = image.read_bytes()
        installer.install(self.source)
        self.assertEqual(first, image.read_bytes())

    def test_changed_layout_stops_before_editing(self):
        shared = self.source / "target/linux/airoha/dts/an7581-fiberhome-ubi-parts.dtsi"
        shared.write_text(shared.read_text().replace("0x00020000", "0x00080000"))
        image = self.source / "target/linux/airoha/image/an7581.mk"
        before = image.read_bytes()
        with self.assertRaisesRegex(ValueError, "UBI boundary"):
            installer.install(self.source)
        self.assertEqual(before, image.read_bytes())

    def test_explicit_shared_ecc_is_rejected(self):
        shared = self.source / "target/linux/airoha/dts/an7581-fiberhome-ubi-parts.dtsi"
        shared.write_text(shared.read_text() + "\nnand-ecc-strength = <8>;\n")
        with self.assertRaisesRegex(ValueError, "Explicit shared ECC"):
            installer.install(self.source)

    def test_changed_ecc_driver_is_rejected(self):
        patch = self.source / "target/linux/airoha/patches-6.18/141-mtd-rawnand-mtk-add-Airoha-EN7581-support.patch"
        patch.write_text(patch.read_text().replace("preserve_ecc_requirements", "different_policy"))
        with self.assertRaisesRegex(ValueError, "ECC preservation"):
            installer.install(self.source)

    def test_unreviewed_upstream_profile_is_preserved(self):
        new = self.source / "target/linux/airoha/dts/an7581-fiberhome-hg5582a.dts"
        new.write_text("upstream owns this file")
        with self.assertRaisesRegex(ValueError, "already defines"):
            installer.install(self.source)
        self.assertEqual("upstream owns this file", new.read_text())

@unittest.skipUnless(shutil.which("dtc") and shutil.which("fdtget"), "dtc/fdtget required")
class CompiledDTChecks(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = pathlib.Path(temp.name)
        self.text = '''/dts-v1/;
/ {
 model = "FiberHome HG5582A";
 compatible = "fiberhome,hg5582a", "fiberhome,hg5382a", "airoha,an7581", "airoha,en7581";
 memory@80000000 { reg = <0 0x80000000 0 0x20000000>; };
 soc {
  ethernet@1fb64000 { airoha,default-line-mode = "epon-10g-1g"; };
  nand-controller@1fa11000 { nand@0 {
   nand-bus-width = <8>; nand-ecc-mode = "hw";
   partitions {
    partition@0 { reg = <0 0x20000>; };
    partition@20000 { reg = <0x20000 0>; };
   };
  }; };
 };
};
'''
    def check(self, text):
        dts, dtb = self.root / "test.dts", self.root / "test.dtb"
        dts.write_text(text)
        subprocess.run(["dtc", "-I", "dts", "-O", "dtb", "-o", str(dtb), str(dts)],
                       check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        validator.validate_dtb(dtb)

    def test_correct_compiled_board(self):
        self.check(self.text)

    def test_wrong_default_mode_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "default-line-mode"):
            self.check(self.text.replace("epon-10g-1g", "xgpon"))

    def test_old_model_label_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "model"):
            self.check(self.text.replace("FiberHome HG5582A", "FiberHome HG5382A"))

    def test_changed_boot_partition_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "partition@0"):
            self.check(self.text.replace("reg = <0 0x20000>", "reg = <0 0x80000>"))

    def test_explicit_ecc_cannot_bypass_preserved_id_policy(self):
        with self.assertRaisesRegex(ValueError, "ECC"):
            self.check(self.text.replace('nand-ecc-mode = "hw";',
                                        'nand-ecc-mode = "hw"; nand-ecc-strength = <8>;'))

class ScriptChecks(unittest.TestCase):
    def test_support_scripts_parse_as_posix_shell(self):
        for name in ["hg5582a-check-upgrade", "39-hg5582a-pon"]:
            subprocess.run(["sh", "-n", str(ROOT / "packages/hg5582a-support/files" / name)], check=True)

if __name__ == "__main__":
    unittest.main()
