#!/usr/bin/env python3
"""Regression checks for pinned audio/USB feed metadata on Airoha."""
import importlib.util
import os
import pathlib
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location(
    "adjust_feed_packages", ROOT / "scripts/adjust-feed-packages.py"
)
patches = importlib.util.module_from_spec(spec)
spec.loader.exec_module(patches)


class FeedCompatibilityChecks(unittest.TestCase):
    def test_unused_mpd_removed_and_libevdev_usb_chain_unblocked(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = pathlib.Path(tmp)
            mpd = source / patches.MPD_LINK
            mpd.parent.mkdir(parents=True)
            mpd.symlink_to("../../../../feeds/packages/sound/mpd")
            evdev = source / patches.LIBEVDEV_MAKEFILE
            evdev.parent.mkdir(parents=True)
            evdev.write_text("define Package/libevdev\n  DEPENDS:=input-support\nendef\n")
            patches.adjust(source)
            self.assertFalse(mpd.is_symlink())
            self.assertNotIn("DEPENDS:=input-support", evdev.read_text())
            self.assertIn("DEPENDS:=", evdev.read_text())
            before = evdev.read_bytes()
            patches.adjust(source)
            self.assertEqual(before, evdev.read_bytes())

    def test_refuses_to_delete_real_mpd_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = pathlib.Path(tmp)
            mpd = source / patches.MPD_LINK
            mpd.mkdir(parents=True)
            (source / patches.LIBEVDEV_MAKEFILE).parent.mkdir(parents=True)
            (source / patches.LIBEVDEV_MAKEFILE).write_text(
                "  DEPENDS:=input-support\n"
            )
            with self.assertRaisesRegex(ValueError, "Refusing"):
                patches.adjust(source)
            self.assertTrue(mpd.is_dir())

    def test_required_usb_packages_not_dropped(self):
        config = (ROOT / "config/general-packages.config").read_text()
        required = (ROOT / "config/required-packages.txt").read_text().splitlines()
        self.assertIn("CONFIG_PACKAGE_libudev-zero=y", config)
        self.assertIn("CONFIG_PACKAGE_usbmuxd=y", config)
        self.assertIn("CONFIG_PACKAGE_usbutils=y", (ROOT / "config/common.config").read_text()
                      + config)
        self.assertIn("usbmuxd", required)
        self.assertIn("usbutils", required)

    def test_ci_build_source_is_patched(self):
        path = os.environ.get("PONWRT_TEST_SOURCE")
        if not path:
            self.skipTest("Only checked when a fetched PonWrt source is available")
        source = pathlib.Path(path)
        self.assertFalse((source / patches.MPD_LINK).is_symlink())
        evdev = (source / patches.LIBEVDEV_MAKEFILE).read_text()
        self.assertNotIn("DEPENDS:=input-support", evdev)
        for relative in ["feeds/packages/utils/usbutils/Makefile",
                         "feeds/packages/utils/usbmuxd/Makefile",
                         "feeds/packages/libs/libudev-zero/Makefile"]:
            self.assertTrue((source / relative).is_file(), relative)


if __name__ == "__main__":
    unittest.main()
