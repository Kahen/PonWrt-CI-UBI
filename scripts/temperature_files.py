#!/usr/bin/env python3
"""Require the complete temperature chain in each published root filesystem."""
import json
import pathlib

TEMPERATURE_PATHS = [
    "sbin/tempinfo",
    "usr/share/rpcd/ucode/luci",
    "usr/share/rpcd/acl.d/luci-mod-status-index.json",
    "www/luci-static/resources/view/status/include/10_system.js",
]


def validate_temperature_files(root):
    root = pathlib.Path(root)
    errors, contents = [], {}
    for name in TEMPERATURE_PATHS:
        path = root / name
        if not path.is_file():
            errors.append("Missing temperature integration file: " + name)
        else:
            contents[name] = path.read_bytes()
    if errors:
        return errors
    if not (root / "sbin/tempinfo").stat().st_mode & 0o111:
        errors.append("sbin/tempinfo is not executable")
    rpc = contents[TEMPERATURE_PATHS[1]]
    if b"getTempInfo" not in rpc or b"/sbin/tempinfo" not in rpc:
        errors.append("luci.getTempInfo is not connected to sbin/tempinfo")
    page = contents[TEMPERATURE_PATHS[3]]
    if b"getTempInfo" not in page or b"Temperature" not in page:
        errors.append("LuCI system page is missing its temperature call/field")
    try:
        acl = json.loads(contents[TEMPERATURE_PATHS[2]])
        permitted = acl["luci-mod-status-index"]["read"]["ubus"]["luci"]
        if "getTempInfo" not in permitted:
            errors.append("Status page lacks read permission for luci.getTempInfo")
    except (ValueError, KeyError, TypeError):
        errors.append("Invalid status temperature ACL")
    return errors
