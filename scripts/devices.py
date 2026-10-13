#!/usr/bin/env python3
"""Discover every PON profile selected by upstream release configurations."""
import json
import pathlib
import re
import subprocess
import sys

CI_DIR = pathlib.Path(__file__).resolve().parent.parent
SOC_PACKAGES = {
    "an7581": ["airoha-en7581-npu-firmware"],
    "an7583": ["airoha-an7583-npu-firmware"],
}


def discover(source):
    targets = {}
    for subtarget in SOC_PACKAGES:
        config = (source / "configs" / f"{subtarget}.config").read_text()
        pattern = rf"^CONFIG_TARGET_(?:DEVICE_)?airoha_{subtarget}_DEVICE_([\w-]+)=y$"
        profiles = sorted(set(re.findall(pattern, config, re.MULTILINE)))
        supported = set(re.findall(
            r"^TARGET_DEVICES\s*\+=\s*([\w-]+)\s*$",
            (source / "target/linux/airoha/image" / f"{subtarget}.mk").read_text(),
            re.MULTILINE,
        ))
        if not profiles or set(profiles) - supported:
            raise ValueError(f"Invalid upstream {subtarget} profiles: {set(profiles) - supported}")
        targets[subtarget] = profiles
    documented = set()
    for line in (source / "README_zh.md").read_text().splitlines():
        if re.match(r"\|\s*AN758[13]\s*\|", line):
            documented.update(re.findall(chr(96) + r"([\w-]+)" + chr(96), line.split("|")[3]))
    selected = set().union(*(set(x) for x in targets.values()))
    if documented - selected:
        raise ValueError(f"Upstream release configs omit documented devices: {documented - selected}")
    sha = subprocess.check_output(
        ["git", "-C", str(source), "rev-parse", "HEAD"], text=True
    ).strip()
    result = {"source_commit": sha, "targets": targets, "profile_count": len(selected)}
    adaptation = source / "hg5582a-adaptation.json"
    if adaptation.exists():
        result["ci_adaptations"] = [json.loads(adaptation.read_text())]
    return result


def profiles_for(catalog, subtarget):
    if subtarget not in SOC_PACKAGES:
        raise ValueError(f"Unsupported subtarget: {subtarget}")
    profiles = catalog["targets"][subtarget]
    if not profiles or len(profiles) != len(set(profiles)):
        raise ValueError(f"Invalid profile catalog for {subtarget}")
    if any(not re.fullmatch(r"[\w-]+", x) for x in profiles):
        raise ValueError("Invalid profile identifier")
    return profiles


def required_packages(subtarget):
    common = [
        x.strip() for x in (CI_DIR / "config/required-packages.txt").read_text().splitlines()
        if x.strip() and not x.startswith("#")
    ]
    return common + SOC_PACKAGES[subtarget]


def config_fragment(catalog, subtarget):
    lines = [
        "CONFIG_TARGET_airoha=y", f"CONFIG_TARGET_airoha_{subtarget}=y",
        "CONFIG_TARGET_MULTI_PROFILE=y", "CONFIG_TARGET_PER_DEVICE_ROOTFS=y",
        "# CONFIG_TARGET_ALL_PROFILES is not set",
    ]
    lines += [
        f"CONFIG_TARGET_DEVICE_airoha_{subtarget}_DEVICE_{profile}=y"
        for profile in profiles_for(catalog, subtarget)
    ]
    lines += [f"CONFIG_PACKAGE_{package}=y" for package in SOC_PACKAGES[subtarget]]
    if subtarget == "an7581":
        lines.append("CONFIG_PACKAGE_kmod-airoha-paged-bosa=y")
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    if len(sys.argv) == 4 and sys.argv[1] == "discover":
        catalog = discover(pathlib.Path(sys.argv[2]).resolve())
        pathlib.Path(sys.argv[3]).write_text(json.dumps(catalog, indent=2) + "\n")
        print(f"Discovered {catalog['profile_count']} profiles: {catalog['targets']}")
    elif len(sys.argv) == 4 and sys.argv[1] == "config":
        catalog = json.loads(pathlib.Path(sys.argv[3]).read_text())
        print(config_fragment(catalog, sys.argv[2]), end="")
    else:
        raise SystemExit("Usage: devices.py discover SOURCE CATALOG | config SUBTARGET CATALOG")
