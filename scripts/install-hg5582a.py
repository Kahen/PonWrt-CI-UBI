#!/usr/bin/env python3
"""Add the verified HG5582A variant to a cloud PonWrt source tree."""
import hashlib
import json
import pathlib
import re
import shutil
import subprocess
import sys

CI = pathlib.Path(__file__).resolve().parent.parent
PROFILE = "fiberhome_hg5582a"
DTS = "an7581-fiberhome-hg5582a"
BLOCK = """
# Verified HG5582A Toshiba/ECC8 variant; retain the shared UBI boot chain.
define Device/fiberhome_hg5582a
  $(call Device/fiberhome_hg5382a)
  DEVICE_MODEL := HG5582A
  DEVICE_DTS := an7581-fiberhome-hg5582a
  SUPPORTED_DEVICES := fiberhome,hg5582a fiberhome,hg5382a
  DEVICE_PACKAGES += hg5582a-support
endef
TARGET_DEVICES += fiberhome_hg5582a
"""

def digest(text):
    return hashlib.sha256(text.encode()).hexdigest()

def require(condition, message):
    if not condition:
        raise ValueError(message)

def install(source):
    marker = source / "hg5582a-adaptation.json"
    dts = source / "target/linux/airoha/dts"
    image = source / "target/linux/airoha/image/an7581.mk"
    config = source / "configs/an7581.config"
    base = source / "target/linux/airoha/an7581/base-files"
    network = base / "etc/board.d/02_network"
    platform = base / "lib/upgrade/platform.sh"
    parent = (dts / "an7581-fiberhome-hg5382a.dts").read_text()
    parts = (dts / "an7581-fiberhome-ubi-parts.dtsi").read_text()
    nand = (source / "target/linux/airoha/patches-6.18/141-mtd-rawnand-mtk-add-Airoha-EN7581-support.patch").read_text()
    require('reg = <0x0 0x80000000 0x0 0x20000000>' in parent, "Shared board RAM changed")
    require('reg = <0x00000000 0x00020000>' in parts and
            'reg = <0x00020000 0x00000000>' in parts, "Shared UBI boundary changed")
    require('nfc->caps->preserve_ecc_requirements' in nand and
            'if (preserve_requirements)' in nand and
            'ECC requirement leaves %d FDM bytes' in nand, "EN7581 ECC preservation changed")
    require(not re.search(r"nand-ecc-(?:strength|step-size|maximize)\s*(?:=|;)", parts + parent),
            "Explicit shared ECC overrides need hardware review")
    template = (CI / "boards/hg5582a" / (DTS + ".dts")).read_text()
    if marker.exists():
        recorded = json.loads(marker.read_text())
        require(recorded["template_sha256"] == digest(template), "Installed adaptation differs")
        require((dts / (DTS + ".dts")).read_text() == template, "Installed DTS changed")
        require(image.read_text().count(BLOCK) == 1, "Installed profile changed")
        require(config.read_text().count("CONFIG_TARGET_DEVICE_airoha_an7581_DEVICE_" + PROFILE + "=y") == 1,
                "Installed profile selection changed")
        return recorded
    require(not (dts / (DTS + ".dts")).exists() and
            "define Device/" + PROFILE not in image.read_text(),
            "Upstream already defines HG5582A; review it before applying this adaptation")
    net = network.read_text()
    plat = platform.read_text()
    pattern = "fiberhome,hg5382a|" + chr(92) + chr(10)
    require(net.count(pattern) == 1 and plat.count(pattern) == 2, "Board routing context changed")
    net = net.replace(pattern, "fiberhome,hg5582a|" + chr(92) + chr(10) + chr(9) + pattern)
    plat = plat.replace(pattern, "fiberhome,hg5582a|" + chr(92) + chr(10) + chr(9) + pattern)
    check = '\t[ "$#" -gt 1 ] && return 1\n'
    require(plat.count(check) == 1, "Upgrade validation context changed")
    plat = plat.replace(check, check + """
	if [ "$board" = "fiberhome,hg5582a" ]; then
		/usr/sbin/hg5582a-check-upgrade --hardware || return 1
	fi
""")
    upgrade = 'platform_do_upgrade() {\n\tlocal board=$(board_name)\n'
    require(plat.count(upgrade) == 1, "Upgrade dispatch context changed")
    plat = plat.replace(upgrade, upgrade + """
	if [ "$board" = "fiberhome,hg5582a" ]; then
		/usr/sbin/hg5582a-check-upgrade --hardware || return 1
	fi
""")
    plat = plat.replace("REQUIRE_IMAGE_METADATA=1",
                        'REQUIRE_IMAGE_METADATA=1\nRAMFS_COPY_DATA="${RAMFS_COPY_DATA:-} /usr/sbin/hg5582a-check-upgrade"')
    package = source / "package/hg5582a-support"
    require(not package.exists(), "Existing support package preserved")
    image.write_text(image.read_text() + BLOCK)
    (dts / (DTS + ".dts")).write_text(template)
    config.write_text(config.read_text().rstrip() + "\nCONFIG_TARGET_DEVICE_airoha_an7581_DEVICE_" + PROFILE + "=y\n")
    network.write_text(net)
    platform.write_text(plat)
    shutil.copytree(CI / "packages/hg5582a-support", package)
    recorded = {
        "profile": PROFILE, "source_commit": subprocess.check_output(
            ["git", "-C", str(source), "rev-parse", "HEAD"], text=True).strip(),
        "template_sha256": digest(template), "shared_board_sha256": digest(parent),
        "shared_layout_sha256": digest(parts), "nand_patch_sha256": digest(nand),
        "nand": "TC58NVG1S3HTAI0", "expected_ecc_strength": 8, "expected_ecc_step": 512,
        "ecc_selection": "Preserved NAND ID/ONFI requirements; no global ECC override",
        "pon_default": "epon-10g-1g", "bootloader_or_factory_embedded": False,
    }
    marker.write_text(json.dumps(recorded, indent=2) + "\n")
    return recorded

if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("Usage: install-hg5582a.py SOURCE")
    print(json.dumps(install(pathlib.Path(sys.argv[1]).resolve()), indent=2))
