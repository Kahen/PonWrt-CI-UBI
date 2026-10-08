#!/usr/bin/env python3
"""Fix feed-only metadata incompatibilities in the Airoha headless firmware build.

Use only exact, known upstream metadata patterns. Never hide missing packages.
"""
import pathlib
import sys

MPD_LINK = pathlib.Path("package/feeds/packages/mpd")
LIBEVDEV_MAKEFILE = pathlib.Path("feeds/packages/libs/libevdev/Makefile")
INPUT_FEATURE = "  DEPENDS:=input-support"
PATCHED_FEATURE = "  # This package is also needed by libudev-zero for USB enumeration.\n  # Airoha has no OpenWrt input-support target feature; libevdev is userspace.\n  DEPENDS:="


def adjust(source):
    source = pathlib.Path(source)
    mpd = source / MPD_LINK
    if mpd.is_symlink():
        # Unselected audio package causes PACKAGE_mpd-full -> itself in Kconfig.
        mpd.unlink()
    elif mpd.exists():
        raise ValueError(f"Refusing to remove non-feed package: {mpd}")

    path = source / LIBEVDEV_MAKEFILE
    text = path.read_text()
    if text.count(INPUT_FEATURE) == 1 and PATCHED_FEATURE not in text:
        text = text.replace(INPUT_FEATURE, PATCHED_FEATURE, 1)
        path.write_text(text)
    elif text.count(PATCHED_FEATURE) == 1:
        pass  # Rerunning customization must be idempotent.
    elif "DEPENDS:=input-support" in text:
        raise ValueError("Upstream libevdev input-support dependency changed")
    else:
        print("libevdev no longer depends on input-support; no patch needed")
    print("Applied headless Airoha feed compatibility adjustments.")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("Usage: adjust-feed-packages.py PONWRT_SOURCE")
    adjust(sys.argv[1])
