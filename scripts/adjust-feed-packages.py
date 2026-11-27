#!/usr/bin/env python3
"""Fix feed-only metadata incompatibilities in the Airoha headless firmware build.

Use only exact, known upstream metadata patterns. Never hide missing packages.
"""
import hashlib
import pathlib
import re
import sys

MPD_LINK = pathlib.Path("package/feeds/packages/mpd")
LIBEVDEV_MAKEFILE = pathlib.Path("feeds/packages/libs/libevdev/Makefile")
INPUT_FEATURE = "  DEPENDS:=input-support"
PATCHED_FEATURE = "  # This package is also needed by libudev-zero for USB enumeration.\n  # Airoha has no OpenWrt input-support target feature; libevdev is userspace.\n  DEPENDS:="
GNUPG2_MAKEFILE = pathlib.Path("feeds/packages/utils/gnupg2/Makefile")
GNUPG2_UTILS_DEPENDENCY = (
    b"define Package/gnupg2-utils\n"
    b"  $(call Package/gnupg2/Default)\n"
    b"  DEPENDS:=gnupg2 +libcurl\n"
)
MINIUPNPD = pathlib.Path("feeds/packages/net/miniupnpd")
MINIUPNPD_BACKPORTS = {
    "020-descr-filter-fix.patch": "4e0f8ddf58cb130044a5f3b92bdf3a8859f8c15e0edbcbcb2b8df42f99e41da1",
    "030-allow-private-fix.patch": "c667bfaa2f1028d1dc44547d4dd4302891799fc0de271a17618eff537b1a2339",
}
MINIUPNPD_LOGGING_PATCH = "040-improve-logging.patch"
MINIUPNPD_LOGGING_SHA256 = "aad6802ab9d01ecea2c143d7495644b714e171552434049f8669d4f28611bcba"
# ImmortalWrt packages e765fb8870b5911992eb4b5a1624ad451e42f4a8
# already refreshes this patch for 2.3.11. Keep its contents byte-for-byte.
MINIUPNPD_UPSTREAM_LOGGING_SHA256 = "69fb7a80e422b6533086b48c1a531eb2eb20c068a8a7f0722fc11ce905e83f23"
MINIUPNPD_LOGGING_REFRESH = pathlib.Path(__file__).resolve().parent.parent / "config/miniupnpd/040-improve-logging-2.3.11.patch"
UNUSED_LUCI_CYCLES = ("luci-app-homeproxy", "luci-app-ipsec-vpnd", "luci-app-passwall")


def exclude_unused_luci_cycles(source):
    ci = pathlib.Path(__file__).resolve().parent.parent
    requested = "\n".join((ci / "config" / name).read_text() for name in (
        "common.config", "general-packages.config", "pon-packages.config"))
    required = set((ci / "config/required-packages.txt").read_text().splitlines())
    # These unused apps introduce sing-box/strongswan/self dependency cycles in
    # the historical HG5582A feeds. Only remove the installed feed links, keeping
    # the feed sources and all requested runtime applications intact.
    links = []
    for name in UNUSED_LUCI_CYCLES:
        if name in required or re.search(rf"^CONFIG_PACKAGE_{re.escape(name)}=[ym]$", requested, re.M):
            raise ValueError(f"Cannot exclude requested LuCI package: {name}")
        link = pathlib.Path(source) / "package/feeds/luci" / name
        if link.is_symlink():
            links.append(link)
        elif link.exists():
            raise ValueError(f"Refusing to remove non-feed package: {link}")
    for link in links:
        link.unlink()
        print(f"Excluded unused cyclic LuCI feed package: {link.name}")


def adjust_gnupg2(source):
    makefile = source / GNUPG2_MAKEFILE
    if not makefile.is_file():
        return
    original = makefile.read_bytes()
    if GNUPG2_UTILS_DEPENDENCY not in original:
        return
    # Backport OpenWrt packages PR #31465. Selecting gnupg2 here prevents
    # Kconfig from propagating the FWKNOPD_GPG condition to luci-app-fwknopd.
    fixed_dependency = GNUPG2_UTILS_DEPENDENCY.replace(
        b"DEPENDS:=gnupg2", b"DEPENDS:=+gnupg2"
    )
    makefile.write_bytes(original.replace(GNUPG2_UTILS_DEPENDENCY, fixed_dependency))
    print("gnupg2-utils: select gnupg2 to break the fwknopd Kconfig cycle")


def adjust_miniupnpd(source):
    package = pathlib.Path(source) / MINIUPNPD
    makefile = package / "Makefile"
    if not makefile.exists():
        return
    version = re.search(r"^PKG_VERSION:=(\S+)\s*$", makefile.read_text(), re.M)
    if not version or version[1] != "2.3.11":
        return
    # Verify every affected file before editing; unknown feed revisions need review.
    obsolete = []
    for name, checksum in MINIUPNPD_BACKPORTS.items():
        patch = package / "patches" / name
        if patch.exists():
            if hashlib.sha256(patch.read_bytes()).hexdigest() != checksum:
                raise ValueError(f"Unrecognized miniupnpd patch: {name}")
            obsolete.append(patch)
    logging = package / "patches" / MINIUPNPD_LOGGING_PATCH
    refreshed = MINIUPNPD_LOGGING_REFRESH.read_bytes()
    logging_action = "kept refreshed or absent logging patch"
    if logging.exists() and logging.read_bytes() != refreshed:
        checksum = hashlib.sha256(logging.read_bytes()).hexdigest()
        if checksum == MINIUPNPD_UPSTREAM_LOGGING_SHA256:
            logging_action = "kept upstream logging fix"
        elif checksum == MINIUPNPD_LOGGING_SHA256:
            logging.write_bytes(refreshed)
            logging_action = "refreshed legacy logging patch"
        else:
            raise ValueError("Unrecognized miniupnpd logging patch")
    # 2.3.11 includes both parser/private-address fixes. Retain upstream security
    # fixes, source hash, UPnP compatibility patches and refreshed logging behavior.
    for patch in obsolete:
        patch.unlink()
    print(f"miniupnpd 2.3.11: omitted merged backports; {logging_action}")


def adjust(source):
    source = pathlib.Path(source)
    exclude_unused_luci_cycles(source)
    adjust_gnupg2(source)
    adjust_miniupnpd(source)
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
