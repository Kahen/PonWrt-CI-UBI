#!/usr/bin/env python3
"""Validate the HG5582A DT actually embedded in both generated FIT images."""
import hashlib
import json
import pathlib
import struct
import subprocess
import sys
import tempfile
from image_packages import fdtget, rootfs_from_fit

PROFILE = "fiberhome_hg5582a"
MODEL = "FiberHome HG5582A"

def embedded_fdt(image):
    nodes = subprocess.check_output(["fdtget", "-l", str(image), "/images"], text=True).splitlines()
    candidates = ["/images/" + n for n in nodes
                  if fdtget(image, "/images/" + n, "type", "s") == "flat_dt"]
    if len(candidates) != 1:
        raise ValueError("Expected exactly one DT in HG5582A FIT")
    node = candidates[0]
    props = subprocess.check_output(["fdtget", "-p", str(image), node], text=True).splitlines()
    if "data" in props:
        data = bytes(int(x, 16) for x in fdtget(image, node, "data", "bx").split())
    else:
        size = int(fdtget(image, node, "data-size"), 16)
        if "data-position" in props:
            offset = int(fdtget(image, node, "data-position"), 16)
        elif "data-offset" in props:
            header = image.read_bytes()[:8]
            total = struct.unpack(">II", header)[1]
            offset = (total + 3) // 4 * 4 + int(fdtget(image, node, "data-offset"), 16)
        else:
            raise ValueError("No inline/external DT payload")
        if size <= 0 or offset < 40 or offset + size > image.stat().st_size:
            raise ValueError("FIT DT range is outside image")
        with image.open("rb") as stream:
            stream.seek(offset)
            data = stream.read(size)
    if data[:4] != b"\xd0\x0d\xfe\xed":
        raise ValueError("FIT DT payload is not FDT")
    return data

def validate_dtb(dtb):
    def expect(node, prop, expected, kind="s"):
        actual = fdtget(dtb, node, prop, kind).split() if kind != "s" else fdtget(dtb, node, prop, kind)
        if actual != expected:
            raise ValueError(f"HG5582A DT differs: {node} {prop}: {actual}")
    expect("/", "model", MODEL)
    expect("/", "compatible", "fiberhome,hg5582a fiberhome,hg5382a airoha,an7581 airoha,en7581")
    expect("/memory@80000000", "reg", ["0", "80000000", "0", "20000000"], "x")
    expect("/soc/ethernet@1fb64000", "airoha,default-line-mode", "epon-10g-1g")
    nand = "/soc/nand-controller@1fa11000/nand@0"
    expect(nand, "nand-bus-width", ["8"], "x")
    expect(nand, "nand-ecc-mode", "hw")
    props = subprocess.check_output(["fdtget", "-p", str(dtb), nand], text=True).splitlines()
    if set(props) & {"nand-ecc-strength", "nand-ecc-step-size", "nand-ecc-maximize"}:
        raise ValueError("HG5582A DT overrides the preserved Toshiba ID ECC policy")
    expect(nand + "/partitions/partition@0", "reg", ["0", "20000"], "x")
    expect(nand + "/partitions/partition@20000", "reg", ["20000", "0"], "x")

def validate_images(source, output, info):
    records = []
    for image in info["images"]:
        if image["type"] != "sysupgrade" and "initramfs" not in image["name"]:
            continue
        path = source / "bin/targets/airoha/an7581" / image["name"]
        data = embedded_fdt(path)
        with tempfile.TemporaryDirectory() as temporary:
            dtb = pathlib.Path(temporary) / "board.dtb"
            dtb.write_bytes(data)
            validate_dtb(dtb)
        records.append({"image": image["name"], "dtb_sha256": hashlib.sha256(data).hexdigest(),
                        "model": MODEL, "pon_default": "epon-10g-1g"})
    if len(records) < 2:
        raise ValueError("Missing validated HG5582A sysupgrade/recovery DT")
    upgrade = next(x for x in info["images"] if x["type"] == "sysupgrade")
    with tempfile.TemporaryDirectory() as temporary:
        rootfs = pathlib.Path(temporary) / "rootfs"
        rootfs.write_bytes(rootfs_from_fit(source / "bin/targets/airoha/an7581" / upgrade["name"]))
        ci = pathlib.Path(__file__).resolve().parent.parent
        for target, original in [
            ("usr/sbin/hg5582a-check-upgrade", "hg5582a-check-upgrade"),
            ("etc/uci-defaults/39-hg5582a-pon", "39-hg5582a-pon"),
        ]:
            actual = subprocess.check_output(["unsquashfs", "-cat", str(rootfs), target])
            expected = (ci / "packages/hg5582a-support/files" / original).read_bytes()
            if actual != expected:
                raise ValueError("HG5582A support file missing/modified in rootfs: " + target)
    adaptation = json.loads((source / "hg5582a-adaptation.json").read_text())
    report = {"profile": PROFILE, "images": records, "support_files_verified": True,
              "expected_runtime_ecc": "8/512 on verified TC58NVG1S3HTAI0",
              "ecc_policy": "Preserved ID/ONFI selection; verify runtime NAND before upgrade",
              "adaptation": adaptation, "physical_optical_registration_verified": False}
    (output / (PROFILE + "-board-validation.json")).write_text(json.dumps(report, indent=2) + "\n")
    return report
