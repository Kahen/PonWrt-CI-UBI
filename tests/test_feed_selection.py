#!/usr/bin/env python3
"""Make sure unsupported multimedia feeds stay out of headless PON builds."""
import importlib.util
import json
import pathlib
import tempfile
import unittest
from unittest.mock import patch

ROOT = pathlib.Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("resolve_feeds", ROOT / "scripts/resolve-feeds.py")
feed_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(feed_module)


class FeedSelectionChecks(unittest.TestCase):
    def test_video_is_disabled_but_pon_and_app_feeds_remain_pinned(self):
        source_text = "\n".join([
            "src-git packages https://github.com/immortalwrt/packages.git",
            "src-git luci https://github.com/immortalwrt/luci.git",
            "src-git video https://github.com/openwrt/video.git",
            "src-git pon_drivers https://github.com/pbs05/openwrt-pon-drivers.git",
            "src-git pon_userspace https://github.com/pbs05/openwrt-pon-userspace.git",
        ])
        def git(_source, *args):
            if args == ("show", "HEAD:feeds.conf.default"):
                return source_text
            if args == ("rev-parse", "HEAD"):
                return "a" * 40
            if args == ("show", "-s", "--format=%cI", "HEAD"):
                return "2026-10-01T00:00:00+00:00"
            raise AssertionError(args)

        requests = []
        def fetch(url, params=None):
            requests.append(url)
            if "/video/" in url:
                raise AssertionError("Unused video feed should not make an API request")
            return [{
                "sha": "b" * 40,
                "commit": {"committer": {"date": "2026-09-01T00:00:00Z"}}
            }]

        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            with patch.object(feed_module, "git", git):
                resolution = feed_module.resolve(root, fetch)
            pinned = (root / "feeds.conf.default").read_text()
            metadata = json.loads((root / "feeds-resolution.json").read_text())
        self.assertIn("# CI excluded unused feed: video", pinned)
        self.assertNotIn("src-git video ", pinned)
        self.assertEqual(["video"], resolution["excluded_feeds"])
        self.assertEqual(["video"], metadata["excluded_feeds"])
        self.assertEqual(
            {"packages", "luci", "pon_drivers", "pon_userspace"},
            {entry["name"] for entry in resolution["feeds"]}
        )
        self.assertEqual(4, len(requests))
        self.assertIn("src-git pon_userspace ", pinned)
        self.assertIn("src-git luci ", pinned)


if __name__ == "__main__":
    unittest.main()
