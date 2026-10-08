#!/usr/bin/env python3
"""Read the installed package database from FIT or tar sysupgrade images."""
import pathlib
import struct
import subprocess
import tarfile
import tempfile
from temperature_files import validate_temperature_files, TEMPERATURE_PATHS


def fdtget(image, node, prop, kind="x"):
    return subprocess.check_output(
        ["fdtget", "-t", kind, str(image), node, prop], text=True
    ).strip()


def rootfs_from_fit(image):
    nodes = subprocess.check_output(
        ["fdtget", "-l", str(image), "/images"], text=True
    ).splitlines()
    candidates = []
    for name in nodes:
        node = "/images/" + name
        if fdtget(image, node, "type", "s") == "filesystem":
            candidates.append(node)
    if len(candidates) != 1:
        raise ValueError(f"Expected one rootfs in FIT image, found {candidates}")
    node = candidates[0]
    props = subprocess.check_output(
        ["fdtget", "-p", str(image), node], text=True
    ).splitlines()
    size = int(fdtget(image, node, "data-size"), 16)
    if "data-position" in props:
        offset = int(fdtget(image, node, "data-position"), 16)
    elif "data-offset" in props:
        with image.open("rb") as stream:
            _, total_size = struct.unpack(">II", stream.read(8))
        offset = (total_size + 3) // 4 * 4 + int(fdtget(image, node, "data-offset"), 16)
    else:
        raise ValueError("FIT rootfs is not external data")
    if size <= 0 or offset < 40 or offset + size > image.stat().st_size:
        raise ValueError("FIT rootfs range is outside the image")
    with image.open("rb") as stream:
        stream.seek(offset)
        return stream.read(size)


def rootfs_from_tar(image):
    with tarfile.open(image, "r:*") as archive:
        members = [x for x in archive.getmembers() if x.isfile() and x.name.endswith("/root")]
        if len(members) != 1:
            raise ValueError("Expected one root file in the sysupgrade tar")
        with archive.extractfile(members[0]) as stream:
            return stream.read()


def parse_packages(text):
    packages, name = {}, None
    for line in text.splitlines():
        if line.startswith("P:"):
            name = line[2:]
        elif line.startswith("Package: "):
            name = line[9:]
        elif name and line.startswith("V:"):
            packages[name] = line[2:]
        elif name and line.startswith("Version: "):
            packages[name] = line[9:]
    if not packages:
        raise ValueError("No installed packages found in the rootfs database")
    return packages


def image_packages(image, require_temperature=False):
    image = pathlib.Path(image)
    with image.open("rb") as stream:
        magic = stream.read(4)
    rootfs = rootfs_from_fit(image) if magic == b"\xd0\x0d\xfe\xed" else rootfs_from_tar(image)
    if rootfs[:4] != b"hsqs":
        raise ValueError("The sysupgrade rootfs is not squashfs")
    with tempfile.TemporaryDirectory() as temporary:
        path = pathlib.Path(temporary) / "rootfs.squashfs"
        path.write_bytes(rootfs)
        if require_temperature:
            directory = pathlib.Path(temporary) / "temperature"
            result = subprocess.run(
                ["unsquashfs", "-no-progress", "-no-xattrs", "-processors", "1",
                 "-d", str(directory), str(path), *TEMPERATURE_PATHS],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            )
            if result.returncode:
                raise ValueError("Cannot extract temperature integration files: " + result.stderr)
            errors = validate_temperature_files(directory)
            if errors:
                raise ValueError("\n".join(errors))
        for db in ["lib/apk/db/installed", "usr/lib/apk/db/installed",
                   "usr/lib/opkg/status", "var/lib/opkg/status"]:
            result = subprocess.run(
                ["unsquashfs", "-cat", str(path), db],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            )
            if result.returncode == 0 and result.stdout:
                return parse_packages(result.stdout)
    raise ValueError("No apk/opkg installed package database found in the image")

