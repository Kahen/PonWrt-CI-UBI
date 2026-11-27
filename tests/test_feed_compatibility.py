#!/usr/bin/env python3
"""Regression checks for pinned feed metadata on Airoha."""
import importlib.util
import os
import pathlib
import tempfile
import unittest
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location(
    "adjust_feed_packages", ROOT / "scripts/adjust-feed-packages.py"
)
patches = importlib.util.module_from_spec(spec)
spec.loader.exec_module(patches)


class FeedCompatibilityChecks(unittest.TestCase):
    def test_unused_luci_cycle_links_removed_but_sources_and_runtime_apps_kept(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = pathlib.Path(tmp)
            links = source / "package/feeds/luci"
            links.mkdir(parents=True)
            for name in (*patches.UNUSED_LUCI_CYCLES, "luci-app-openclash"):
                package = source / "feeds/luci/applications" / name
                package.mkdir(parents=True)
                (package / "Makefile").write_text("preserve package source\n")
                (links / name).symlink_to(package)
            patches.exclude_unused_luci_cycles(source)
            patches.exclude_unused_luci_cycles(source)
            for name in patches.UNUSED_LUCI_CYCLES:
                self.assertFalse((links / name).is_symlink())
                self.assertTrue((source / "feeds/luci/applications" / name / "Makefile").is_file())
            self.assertTrue((links / "luci-app-openclash").is_symlink())

    def test_luci_exclusion_refuses_real_directories_before_removing_links(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = pathlib.Path(tmp)
            links = source / "package/feeds/luci"
            links.mkdir(parents=True)
            first = links / patches.UNUSED_LUCI_CYCLES[0]
            first.symlink_to("missing feed source")
            (links / patches.UNUSED_LUCI_CYCLES[1]).mkdir()
            with self.assertRaisesRegex(ValueError, "Refusing to remove non-feed"):
                patches.exclude_unused_luci_cycles(source)
            self.assertTrue(first.is_symlink())

    def test_luci_exclusion_cannot_remove_requested_application(self):
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.object(patches, "UNUSED_LUCI_CYCLES", ("luci-app-openclash",)):
                with self.assertRaisesRegex(ValueError, "Cannot exclude requested"):
                    patches.exclude_unused_luci_cycles(pathlib.Path(tmp))

    def test_gnupg2_utils_selects_gnupg2_without_changing_other_packages(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = pathlib.Path(tmp)
            makefile = source / patches.GNUPG2_MAKEFILE
            makefile.parent.mkdir(parents=True)
            original = (
                b"define Package/gnupg2-utils\n"
                b"  $(call Package/gnupg2/Default)\n"
                b"  DEPENDS:=gnupg2 +libcurl\n"
                b"endef\n\n"
                b"define Package/another-package\n"
                b"  DEPENDS:=gnupg2 +libcurl\n"
                b"endef\n"
            )
            makefile.write_bytes(original)

            patches.adjust_gnupg2(source)
            patches.adjust_gnupg2(source)

            self.assertEqual(
                original.replace(b"DEPENDS:=gnupg2", b"DEPENDS:=+gnupg2", 1),
                makefile.read_bytes(),
            )

    def assert_miniupnpd_patched(self, package):
        if "PKG_VERSION:=2.3.11\n" not in (package / "Makefile").read_text():
            return
        for name in patches.MINIUPNPD_BACKPORTS:
            self.assertFalse((package / "patches" / name).exists())
        logging = package / "patches" / patches.MINIUPNPD_LOGGING_PATCH
        # Some pinned feeds have already dropped the optional logging patch.
        # A retained patch must be the CI refresh or the verified upstream fix.
        if logging.exists():
            self.assertIn(patches.hashlib.sha256(logging.read_bytes()).hexdigest(), {
                patches.hashlib.sha256(patches.MINIUPNPD_LOGGING_REFRESH.read_bytes()).hexdigest(),
                patches.MINIUPNPD_UPSTREAM_LOGGING_SHA256,
            })

    def miniupnpd_fixture(self, source, version):
        package = source / patches.MINIUPNPD
        (package / "patches").mkdir(parents=True)
        (package / "Makefile").write_text(f"PKG_VERSION:={version}\n")
        patch = package / "patches" / "020-descr-filter-fix.patch"
        patch.write_text("known permission-parser backport\n")
        return package, patch

    def test_miniupnpd_removes_only_verified_backport_and_is_idempotent(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = pathlib.Path(tmp)
            package, patch = self.miniupnpd_fixture(source, "2.3.11")
            other = package / "patches/900-compat.patch"
            other.write_text("keep this patch\n")
            logging = package / "patches" / patches.MINIUPNPD_LOGGING_PATCH
            logging.write_text("known logging patch\n")
            digest = patches.hashlib.sha256(patch.read_bytes()).hexdigest()
            logging_digest = patches.hashlib.sha256(logging.read_bytes()).hexdigest()
            with mock.patch.object(patches, "MINIUPNPD_BACKPORTS", {patch.name: digest}), \
                    mock.patch.object(patches, "MINIUPNPD_LOGGING_SHA256", logging_digest):
                patches.adjust_miniupnpd(source)
                patches.adjust_miniupnpd(source)
            self.assertFalse(patch.exists())
            self.assertEqual("keep this patch\n", other.read_text())
            self.assertEqual("PKG_VERSION:=2.3.11\n", (package / "Makefile").read_text())
            self.assertEqual(patches.MINIUPNPD_LOGGING_REFRESH.read_bytes(), logging.read_bytes())
            self.assert_miniupnpd_patched(package)

    def test_miniupnpd_feed_without_obsolete_patches_passes_ci_check(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = pathlib.Path(tmp)
            package, patch = self.miniupnpd_fixture(source, "2.3.11")
            patch.unlink()  # Upstream already removed the obsolete backports.
            other = package / "patches/900-compat.patch"
            other.write_text("retain upstream compatibility\n")
            patches.adjust_miniupnpd(source)
            self.assert_miniupnpd_patched(package)
            self.assertFalse((package / "patches" / patches.MINIUPNPD_LOGGING_PATCH).exists())
            self.assertEqual("retain upstream compatibility\n", other.read_text())

    def test_miniupnpd_upstream_refresh_is_preserved_and_passes_ci_check(self):
        # Exact patch from the failed run's packages feed (72c7391fb2d0).
        refreshed = (ROOT / "tests/fixtures/miniupnpd/040-improve-logging-upstream.patch").read_bytes()
        with tempfile.TemporaryDirectory() as tmp:
            source = pathlib.Path(tmp)
            package, patch = self.miniupnpd_fixture(source, "2.3.11")
            patch.unlink()  # Upstream e765fb8870b5 also removed both backports.
            logging = package / "patches" / patches.MINIUPNPD_LOGGING_PATCH
            logging.write_bytes(refreshed)
            patches.adjust_miniupnpd(source)
            self.assert_miniupnpd_patched(package)
            patches.adjust_miniupnpd(source)
            self.assertEqual(refreshed, logging.read_bytes())

    def test_miniupnpd_modified_upstream_refresh_requires_review(self):
        refreshed = (ROOT / "tests/fixtures/miniupnpd/040-improve-logging-upstream.patch").read_bytes()
        with tempfile.TemporaryDirectory() as tmp:
            source = pathlib.Path(tmp)
            package, patch = self.miniupnpd_fixture(source, "2.3.11")
            patch.unlink()
            logging = package / "patches" / patches.MINIUPNPD_LOGGING_PATCH
            modified = refreshed.replace(b"LOG_WARNING", b"LOG_DEBUG", 1)
            self.assertNotEqual(refreshed, modified)
            logging.write_bytes(modified)
            with self.assertRaisesRegex(ValueError, "Unrecognized miniupnpd logging"):
                patches.adjust_miniupnpd(source)
            self.assertEqual(modified, logging.read_bytes())

    def test_miniupnpd_ci_check_rejects_stale_retained_logging_patch(self):
        with tempfile.TemporaryDirectory() as tmp:
            package, patch = self.miniupnpd_fixture(pathlib.Path(tmp), "2.3.11")
            patch.unlink()
            (package / "patches" / patches.MINIUPNPD_LOGGING_PATCH).write_text("stale logging\n")
            with self.assertRaises(AssertionError):
                self.assert_miniupnpd_patched(package)

    def test_miniupnpd_unknown_logging_patch_preserves_all_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = pathlib.Path(tmp)
            package, patch = self.miniupnpd_fixture(source, "2.3.11")
            logging = package / "patches" / patches.MINIUPNPD_LOGGING_PATCH
            logging.write_text("unreviewed logging patch\n")
            digest = patches.hashlib.sha256(patch.read_bytes()).hexdigest()
            with mock.patch.object(patches, "MINIUPNPD_BACKPORTS", {patch.name: digest}):
                with self.assertRaisesRegex(ValueError, "Unrecognized miniupnpd logging"):
                    patches.adjust_miniupnpd(source)
            self.assertTrue(patch.exists())
            self.assertEqual("unreviewed logging patch\n", logging.read_text())

    def test_miniupnpd_older_release_keeps_its_required_backport(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = pathlib.Path(tmp)
            _, patch = self.miniupnpd_fixture(source, "2.3.9")
            patches.adjust_miniupnpd(source)
            self.assertTrue(patch.exists())

    def test_miniupnpd_changed_patch_requires_review(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = pathlib.Path(tmp)
            _, patch = self.miniupnpd_fixture(source, "2.3.11")
            with self.assertRaisesRegex(ValueError, "Unrecognized miniupnpd"):
                patches.adjust_miniupnpd(source)
            self.assertTrue(patch.exists())

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
        for name in patches.UNUSED_LUCI_CYCLES:
            self.assertFalse((source / "package/feeds/luci" / name).is_symlink())
        self.assertFalse((source / patches.MPD_LINK).is_symlink())
        evdev = (source / patches.LIBEVDEV_MAKEFILE).read_text()
        self.assertNotIn("DEPENDS:=input-support", evdev)
        for relative in ["feeds/packages/utils/usbutils/Makefile",
                         "feeds/packages/utils/usbmuxd/Makefile",
                         "feeds/packages/libs/libudev-zero/Makefile"]:
            self.assertTrue((source / relative).is_file(), relative)
        gnupg2 = source / patches.GNUPG2_MAKEFILE
        if gnupg2.is_file():
            self.assertNotIn(patches.GNUPG2_UTILS_DEPENDENCY, gnupg2.read_bytes())
        package = source / patches.MINIUPNPD
        self.assert_miniupnpd_patched(package)


if __name__ == "__main__":
    unittest.main()
