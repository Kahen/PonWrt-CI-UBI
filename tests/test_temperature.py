#!/usr/bin/env python3
"""Exercise the actual patched feed files, helper output and publication gate."""
import contextlib
import importlib.util
import io
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile
import tarfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
from image_packages import image_packages
from temperature_files import TEMPERATURE_PATHS, validate_temperature_files

spec = importlib.util.spec_from_file_location("integrate_temperature",
                                               ROOT / "scripts/integrate-temperature.py")
integration = importlib.util.module_from_spec(spec)
spec.loader.exec_module(integration)
SOURCE = pathlib.Path(os.environ.get("PONWRT_TEST_SOURCE", ROOT.parent / "ponwrt-source")).resolve()


@unittest.skipUnless((SOURCE / ".git").exists(), "PonWrt source/feed snapshot required")
class TemperatureChecks(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.tree = pathlib.Path(self.tmp.name) / "source"
        for relative in [integration.MAKEFILE, integration.RPC, integration.PAGE, integration.ACL,
                         integration.ZH_HANS]:
            if str(relative).startswith("feeds/luci/"):
                repository = SOURCE / "feeds/luci"
                path = str(relative)[len("feeds/luci/"):]
            else:
                repository, path = SOURCE, str(relative)
            contents = subprocess.check_output(["git", "-C", str(repository),
                                               "show", "HEAD:" + path])
            target = self.tree / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(contents)
        self.before_acl = json.loads((self.tree / integration.ACL).read_text())
        with contextlib.redirect_stdout(io.StringIO()):
            integration.integrate(self.tree)

    def rootfs(self):
        rootfs = pathlib.Path(self.tmp.name) / "rootfs"
        sources = [
            SOURCE / "package/emortal/autocore/files/tempinfo",
            self.tree / integration.RPC, self.tree / integration.ACL, self.tree / integration.PAGE,
        ]
        for name, original in zip(TEMPERATURE_PATHS, sources):
            target = rootfs / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(original, target)
        (rootfs / "sbin/tempinfo").chmod(0o755)
        return rootfs

    def test_airoha_installation_rule_selects_both_targets(self):
        text = (self.tree / integration.MAKEFILE).read_text()
        expression = re.search(r"\$\(filter [^,]+, \$\(TARGETID\)\)", text)[0]
        for target in ["airoha/an7581", "airoha/an7583"]:
            makefile = "TARGETID := " + target + "\nall:\n\t@printf '%s' '" + expression + "'\n"
            result = subprocess.check_output(["make", "-s", "-f", "-"],
                                             input=makefile, text=True)
            self.assertEqual(target, result)

    def test_native_helper_to_rpc_to_page_with_device_reading(self):
        if not shutil.which("node"):
            self.skipTest("Node.js required for LuCI render checks")
        fixture = pathlib.Path(self.tmp.name) / "sysfs"
        (fixture / "thermal_zone0").mkdir(parents=True)
        (fixture / "thermal_zone0/temp").write_text("65600\n")
        (fixture / "thermal_zone0/type").write_text("cpu-thermal\n")
        release = pathlib.Path(self.tmp.name) / "openwrt_release"
        release.write_text("DISTRIB_TARGET='airoha/an7581'\n")
        ieee = pathlib.Path(self.tmp.name) / "ieee80211"
        ieee.mkdir()
        helper = (SOURCE / "package/emortal/autocore/files/tempinfo").read_text()
        helper = helper.replace("/etc/openwrt_release", str(release))
        helper = helper.replace("/sys/class/thermal", str(fixture))
        helper = helper.replace("/sys/class/ieee80211", str(ieee))
        measured = subprocess.check_output(["sh"], input=helper, text=True)
        self.assertEqual("CPU: 65.6°C", measured)
        subprocess.run(["node", str(ROOT / "tests/temperature-integration.js"),
                        str(self.tree / integration.PAGE),
                        str(ROOT / "config/temperature-rpc.uc"), measured], check=True)

    def test_status_reader_has_only_read_access(self):
        acl = json.loads((self.tree / integration.ACL).read_text())
        allowed = acl["luci-mod-status-index"]["read"]["ubus"]["luci"]
        self.assertIn("getTempInfo", allowed)
        allowed.remove("getTempInfo")
        self.assertEqual(self.before_acl, acl)

    def test_reapplying_integration_is_idempotent(self):
        names = [integration.MAKEFILE, integration.RPC, integration.PAGE, integration.ACL,
                 integration.ZH_HANS]
        before = [(self.tree / name).read_bytes() for name in names]
        with contextlib.redirect_stdout(io.StringIO()):
            integration.integrate(self.tree)
        self.assertEqual(before, [(self.tree / name).read_bytes() for name in names])

    def test_squashfs_image_checks_files_in_addition_to_package_database(self):
        if not all(shutil.which(x) for x in ['mksquashfs', 'unsquashfs']):
            self.skipTest('squashfs-tools required')
        rootfs = self.rootfs()
        database = rootfs / 'lib/apk/db/installed'
        database.parent.mkdir(parents=True)
        database.write_text('P:autocore\nV:42.1\n\n')
        for complete in [True, False]:
            if not complete:
                (rootfs / 'sbin/tempinfo').unlink()
            squashfs = pathlib.Path(self.tmp.name) / ('root-' + str(complete))
            subprocess.run(['mksquashfs', str(rootfs), str(squashfs), '-noappend',
                            '-processors', '1', '-comp', 'gzip'], check=True,
                           stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
            image = pathlib.Path(self.tmp.name) / ('upgrade-' + str(complete) + '.bin')
            with tarfile.open(image, 'w') as archive:
                archive.add(squashfs, arcname='sysupgrade-board/root')
            if complete:
                self.assertEqual({'autocore': '42.1'},
                                 image_packages(image, require_temperature=True))
            else:
                self.assertEqual({'autocore': '42.1'}, image_packages(image))
                with self.assertRaises(ValueError):
                    image_packages(image, require_temperature=True)

    def test_complete_image_passes(self):
        self.assertEqual([], validate_temperature_files(self.rootfs()))

    def test_installed_autocore_without_tempinfo_blocks_publication(self):
        rootfs = self.rootfs()
        (rootfs / "sbin/tempinfo").unlink()
        self.assertTrue(validate_temperature_files(rootfs))

    def test_nonexecutable_helper_blocks_publication(self):
        rootfs = self.rootfs()
        (rootfs / "sbin/tempinfo").chmod(0o644)
        self.assertTrue(validate_temperature_files(rootfs))

    def test_missing_rpc_blocks_publication(self):
        rootfs = self.rootfs()
        path = rootfs / TEMPERATURE_PATHS[1]
        path.write_text(path.read_text().replace("getTempInfo", "removedMethod"))
        self.assertTrue(validate_temperature_files(rootfs))

    def test_missing_status_permission_blocks_publication(self):
        rootfs = self.rootfs()
        path = rootfs / TEMPERATURE_PATHS[2]
        acl = json.loads(path.read_text())
        acl["luci-mod-status-index"]["read"]["ubus"]["luci"].remove("getTempInfo")
        path.write_text(json.dumps(acl))
        self.assertTrue(validate_temperature_files(rootfs))

    def test_old_system_page_blocks_publication(self):
        rootfs = self.rootfs()
        path = rootfs / TEMPERATURE_PATHS[3]
        path.write_text(path.read_text().replace("getTempInfo", "removedMethod"))
        self.assertTrue(validate_temperature_files(rootfs))


if __name__ == "__main__":
    unittest.main()
