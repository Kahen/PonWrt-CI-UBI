#!/usr/bin/env python3
"""Collect validated, complete per-device firmware sets for one SoC."""
import hashlib
import json
import pathlib
import shutil
import subprocess
import sys
from devices import profiles_for
from image_packages import image_packages
from validate import validate_config, validate_profile


def sha256(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def collect(source, output, subtarget, catalog):
    errors = validate_config(source / ".config", subtarget, catalog)
    if errors:
        raise ValueError("\n".join(errors))
    source_sha = subprocess.check_output(
        ["git", "-C", str(source), "rev-parse", "HEAD"], text=True
    ).strip()
    if source_sha != catalog["source_commit"]:
        raise ValueError("Build source differs from the shared build plan")
    target = source / "bin/targets/airoha" / subtarget
    overview = json.loads((target / "profiles.json").read_text())
    profiles = overview["profiles"]
    expected = profiles_for(catalog, subtarget)
    if set(profiles) != set(expected) or overview["target"] != f"airoha/{subtarget}":
        raise ValueError("profiles.json does not contain exactly the requested target/profiles")
    if overview.get("git_commit") != source_sha:
        raise ValueError("profiles.json source commit differs from the build plan")
    output.mkdir(parents=True, exist_ok=False)
    summary, published = [], set()
    fwtool = source / "staging_dir/host/bin/fwtool"
    for profile in expected:
        info = profiles[profile]
        images = info["images"]
        upgrades = [x for x in images if x["type"] == "sysupgrade"
                    and x.get("filesystem") == "squashfs"]
        recovery = [x for x in images if "initramfs" in x["name"]]
        if len(upgrades) != 1 or not recovery:
            raise ValueError(f"{profile}: missing unique sysupgrade or initramfs image")
        for item in images:
            name = item["name"]
            if pathlib.Path(name).name != name or not name.startswith(info["image_prefix"] + "-"):
                raise ValueError(f"{profile}: invalid image name {name}")
            if name in published:
                raise ValueError(f"Duplicate image filename: {name}")
            path = target / name
            if not path.is_file() or path.stat().st_size != item["size"] or sha256(path) != item["sha256"]:
                raise ValueError(f"{profile}: missing, truncated or corrupt image {name}")
            published.add(name)
        upgrade = target / upgrades[0]["name"]
        metadata_file = output / f"{profile}-sysupgrade-metadata.json"
        subprocess.run([str(fwtool), "-q", "-i", str(metadata_file), str(upgrade)], check=True)
        metadata = json.loads(metadata_file.read_text())
        packages = image_packages(upgrade, require_temperature=True)
        errors = validate_profile(metadata, info, profile, subtarget, packages)
        if errors:
            raise ValueError("\n".join(errors))
        manifest = output / f"{info['image_prefix']}.manifest"
        manifest.write_text("".join(
            f"{name} - {version}\n" for name, version in sorted(packages.items())
        ))
        for item in images:
            shutil.copy2(target / item["name"], output / item["name"])
        summary.append({
            "profile": profile, "titles": info.get("titles", []),
            "sysupgrade": upgrades[0]["name"], "recovery": [x["name"] for x in recovery],
            "images": images, "package_count": len(packages),
        })
        print(f"Validated {profile}: {len(images)} images, {len(packages)} installed packages.", flush=True)
    for name, source_file in {
        f"{subtarget}-profiles.json": target / "profiles.json",
        f"{subtarget}-build.config": source / ".config",
        f"{subtarget}-feeds.conf.default": source / "feeds.conf.default",
        f"{subtarget}-feeds-resolution.json": source / "feeds-resolution.json",
    }.items():
        shutil.copy2(source_file, output / name)
    if (source / "requested-packages-dropped.txt").stat().st_size:
        shutil.copy2(source / "requested-packages-dropped.txt",
                     output / f"{subtarget}-requested-packages-dropped.txt")
    commits = ["component\tcommit\n", f"ponwrt\t{source_sha}\n"]
    for gitdir in sorted(list((source / "feeds").glob("*/.git")) +
                         list((source / "package").glob("*/.git"))):
        repo = gitdir.parent
        commit = subprocess.check_output(
            ["git", "-C", str(repo), "rev-parse", "HEAD"], text=True
        ).strip()
        commits.append(f"{repo.relative_to(source)}\t{commit}\n")
    commits.append((source / "custom-package-commits.tsv").read_text())
    (output / f"{subtarget}-source-commits.tsv").write_text("".join(commits))
    (output / f"{subtarget}-build-summary.json").write_text(json.dumps({
        "source_commit": source_sha, "target": f"airoha/{subtarget}", "profiles": summary,
    }, indent=2) + "\n")
    checksums = "".join(f"{sha256(path)}  {path.name}\n" for path in sorted(output.iterdir()) if path.is_file())
    (output / f"SHA256SUMS-{subtarget}").write_text(checksums)


if __name__ == "__main__":
    if len(sys.argv) != 5:
        raise SystemExit("Usage: collect.py SOURCE OUTPUT SUBTARGET CATALOG")
    catalog = json.loads(pathlib.Path(sys.argv[4]).read_text())
    collect(pathlib.Path(sys.argv[1]).resolve(), pathlib.Path(sys.argv[2]).resolve(),
            sys.argv[3], catalog)

