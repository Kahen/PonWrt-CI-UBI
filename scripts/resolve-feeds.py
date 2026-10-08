#!/usr/bin/env python3
"""Pin upstream feeds to revisions contemporary with the selected PonWrt source."""
import datetime
import json
import os
import pathlib
import re
import subprocess
import sys
import urllib.parse
import urllib.request


# Video/desktop multimedia adds Qt, GStreamer and EGL Kconfig cycles to this
# headless PON router build. It supplies none of the requested runtime apps,
# image tooling or PON driver packages.
EXCLUDED_FEEDS = {"video"}


def git(source, *args):
    return subprocess.check_output(
        ["git", "-C", str(source), *args], text=True
    ).strip()


def github_json(path, params=None):
    url = "https://api.github.com" + path
    if params:
        url += "?" + urllib.parse.urlencode(params)
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "PonWrt-XG040G-MD-CI",
    }
    if os.environ.get("GH_TOKEN"):
        headers["Authorization"] = "Bearer " + os.environ["GH_TOKEN"]
    request = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.load(response)


def resolve_feed(kind, name, spec, source_time, fetch):
    if kind not in {"src-git", "src-git-full"}:
        raise ValueError(f"Unsupported active feed type for {name}: {kind}")
    if "^" in spec:
        url, ref = spec.rsplit("^", 1)
        mode = "upstream-pin"
    elif ";" in spec:
        url, ref = spec.rsplit(";", 1)
        mode = "source-date"
    else:
        url, ref, mode = spec, None, "source-date"
    match = re.fullmatch(r"https://github\.com/([\w.-]+)/([\w.-]+?)(?:\.git)?/?", url)
    if not match:
        raise ValueError(f"Unsupported feed URL for {name}: {url}")
    owner, repo = match.groups()
    api = f"/repos/{owner}/{repo}/commits"
    if mode == "upstream-pin":
        if re.fullmatch(r"[0-9a-f]{40}", ref or ""):
            sha = ref
        else:
            sha = fetch(api + "/" + urllib.parse.quote(ref, safe=""))["sha"]
    else:
        params = {"until": source_time, "per_page": 1}
        if ref:
            params["sha"] = ref
        commits = fetch(api, params)
        if not commits:
            raise ValueError(f"No commit for feed {name} at or before {source_time}")
        commit = commits[0]
        sha = commit["sha"]
        commit_time = datetime.datetime.fromisoformat(
            commit["commit"]["committer"]["date"].replace("Z", "+00:00")
        )
        cutoff = datetime.datetime.fromisoformat(source_time.replace("Z", "+00:00"))
        if commit_time > cutoff:
            raise ValueError(f"Feed {name} resolved to a commit newer than the source")
    if not re.fullmatch(r"[0-9a-f]{40}", sha):
        raise ValueError(f"Invalid resolved commit for feed {name}: {sha}")
    record = {"name": name, "url": url, "ref": ref, "commit": sha, "mode": mode}
    return f"{kind} {name} {url}^{sha}", record


def resolve(source, fetch=github_json):
    # Read the chosen commit, not a file left behind by an earlier build.
    upstream = git(source, "show", "HEAD:feeds.conf.default")
    source_sha = git(source, "rev-parse", "HEAD")
    source_time = git(source, "show", "-s", "--format=%cI", "HEAD")
    lines, records, names, excluded = [], [], set(), []
    for line in upstream.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            lines.append(line)
            continue
        fields = stripped.split()
        if len(fields) != 3:
            raise ValueError(f"Unsupported feed definition: {line}")
        kind, name, spec = fields
        if name in names:
            raise ValueError(f"Duplicate feed name: {name}")
        names.add(name)
        if name in EXCLUDED_FEEDS:
            excluded.append(name)
            lines.append(f"# CI excluded unused feed: {name} ({spec})")
            print(f"{name}: excluded (unused multimedia feed)", flush=True)
            continue
        pinned, record = resolve_feed(kind, name, spec, source_time, fetch)
        lines.append(pinned)
        records.append(record)
        print(f"{name}: {record['commit']} ({record['mode']})", flush=True)
    if not records:
        raise ValueError("The upstream source contains no active feeds")
    resolution = {"source_commit": source_sha, "source_time": source_time,
                  "feeds": records, "excluded_feeds": excluded}
    # Do not replace the upstream config until every feed has resolved.
    (source / "feeds.conf.default").write_text("\n".join(lines) + "\n")
    (source / "feeds-resolution.json").write_text(
        json.dumps(resolution, ensure_ascii=False, indent=2) + "\n"
    )
    return resolution


def main():
    if len(sys.argv) != 2:
        print("Usage: resolve-feeds.py SOURCE_DIR", file=sys.stderr)
        return 2
    try:
        resolve(pathlib.Path(sys.argv[1]).resolve())
    except (ValueError, KeyError, OSError, subprocess.CalledProcessError) as error:
        print(f"ERROR: feed resolution failed: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
