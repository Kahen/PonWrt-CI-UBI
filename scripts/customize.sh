#!/usr/bin/env bash
set -euo pipefail

# This script runs inside the cloned PonWrt source tree, after feeds install.
# Keep NAND/UBI layout untouched; only add runtime packages here.
: > ./custom-package-commits.tsv

record_commit() {
  printf '%s\t%s\n' "$1" "$(git -C "$2" rev-parse HEAD)" >> ./custom-package-commits.tsv
}

remove_matches() {
  local pattern="$1"
  find ./package ./feeds/luci ./feeds/packages \
    -maxdepth 4 -type d -iname "*${pattern}*" 2>/dev/null \
    -print -exec rm -rf {} + || true
}

clone_direct() {
  local target="$1"
  local repo="$2"
  local branch="$3"

  remove_matches "$target"
  git clone --depth=1 --single-branch --branch "$branch" \
    "https://github.com/${repo}.git" "./package/${target}"
  record_commit "$repo" "./package/${target}"
}

import_footstrap() {
  local tmp
  tmp="$(mktemp -d)"
  remove_matches "footstrap"

  # The upstream repository contains the OpenWrt package one directory below
  # its root, so it cannot be imported with clone_direct().
  git clone --depth=1 --single-branch --branch main \
    https://github.com/VizzleTF/luci-theme-footstrap.git "$tmp/footstrap"

  if [ ! -f "$tmp/footstrap/luci-theme-footstrap/Makefile" ]; then
    echo "ERROR: luci-theme-footstrap Makefile not found"
    exit 1
  fi

  cp -a "$tmp/footstrap/luci-theme-footstrap" ./package/luci-theme-footstrap
  record_commit VizzleTF/luci-theme-footstrap "$tmp/footstrap"
  rm -rf "$tmp"
}

import_openclash() {
  local tmp
  tmp="$(mktemp -d)"
  remove_matches "openclash"

  git clone --depth=1 --single-branch --branch dev \
    https://github.com/vernesong/OpenClash.git "$tmp/OpenClash"

  local src
  src="$(find "$tmp/OpenClash" -maxdepth 3 -type d -name 'luci-app-openclash' | head -n1)"
  if [ -z "$src" ]; then
    echo "ERROR: luci-app-openclash directory not found in vernesong/OpenClash"
    exit 1
  fi

  cp -a "$src" ./package/luci-app-openclash
  record_commit vernesong/OpenClash "$tmp/OpenClash"
  rm -rf "$tmp"
}

import_viking_packages() {
  # Bingoguo/VIKINGYFY packages provide GecoosAC and the WOL LuCI app.
  # The WOL package was renamed from luci-app-wolplus to luci-app-wolultra.
  remove_matches "gecoosac"
  remove_matches "luci-app-wolplus"
  remove_matches "luci-app-wolultra"
  remove_matches "luci-app-timewol"
  rm -rf ./package/viking-packages

  git clone --depth=1 --single-branch --branch main \
    https://github.com/VIKINGYFY/packages.git ./package/viking-packages
  record_commit VIKINGYFY/packages ./package/viking-packages
}

import_autoreboot() {
  local tmp
  tmp="$(mktemp -d)"
  remove_matches "luci-app-autoreboot"
  git clone --depth=1 --filter=blob:none --sparse \
    https://github.com/immortalwrt/luci.git "$tmp/luci"
  git -C "$tmp/luci" sparse-checkout set applications/luci-app-autoreboot
  cp -a "$tmp/luci/applications/luci-app-autoreboot" ./package/luci-app-autoreboot
  # Normalize the feed-relative include for a directly imported package.
  sed -i 's|include ../../luci.mk|include $(TOPDIR)/feeds/luci/luci.mk|' \
    ./package/luci-app-autoreboot/Makefile
  record_commit immortalwrt/luci-autoreboot "$tmp/luci"
  rm -rf "$tmp"
}

import_airoha_npu() {
  # The former bingoguo93/luci-app-airoha-npu endpoint is no longer public.
  # Pin to a known public upstream revision supporting AN7581 and AN7583.
  local repo="rchen14b/luci-app-airoha-npu"
  local revision="14521b8414da1e98517a295d8ec267087c7dde8e"
  local dest="./package/luci-app-airoha-npu"
  local required

  remove_matches "luci-app-airoha-npu"
  git init -q "$dest"
  git -C "$dest" remote add origin "https://github.com/${repo}.git"
  if [ "$(git -C "$dest" remote get-url origin)" != "https://github.com/${repo}.git" ]; then
    echo "ERROR: wrong Airoha NPU origin; expected https://github.com/${repo}.git" >&2
    exit 1
  fi
  git -C "$dest" fetch --depth=1 origin "$revision"
  git -C "$dest" -c advice.detachedHead=false checkout --detach FETCH_HEAD

  for required in \
    Makefile \
    htdocs/luci-static/resources/view/airoha_npu/status.js \
    root/usr/libexec/rpcd/luci.airoha_npu \
    root/usr/share/luci/menu.d/luci-app-airoha-npu.json \
    root/usr/share/rpcd/acl.d/luci-app-airoha-npu.json; do
    if [ ! -f "$dest/$required" ]; then
      echo "ERROR: pinned Airoha NPU package is missing $required" >&2
      exit 1
    fi
  done
  if ! grep -Fq 'include $(TOPDIR)/feeds/luci/luci.mk' "$dest/Makefile"; then
    echo "ERROR: pinned Airoha NPU package Makefile is not feed-compatible" >&2
    exit 1
  fi
  # Drop the author's older nested packaging template to avoid duplicate scans.
  rm -rf -- "$dest/luci-app-airoha-npu"
  record_commit "$repo" "$dest"
}

echo "Importing third-party packages used by the GENERAL package set..."

import_openclash
clone_direct "luci-app-lucky" "sirpdboy/luci-app-lucky" "main"
import_viking_packages
import_airoha_npu
import_footstrap
import_autoreboot

# Connect autocore to the pinned LuCI feed before package metadata is generated.
python3 "$(dirname "$0")/integrate-temperature.py" .

# This unselected audio package has a circular codec dependency with this
# source/feed snapshot. Exclude only its installed feed symlink so the
# Kconfig parser can load a clean menu; no requested firmware package uses it.
if [ -L ./package/feeds/packages/squeezelite ]; then
  rm ./package/feeds/packages/squeezelite
fi

# The pinned packages feed retains an unused MPD Kconfig self-cycle and
# libevdev's input-support feature guard blocks libudev-zero / usbutils.
python3 "$(dirname "$0")/adjust-feed-packages.py" .

# Force package metadata to be regenerated after adding/removing package trees.
rm -rf ./tmp

echo "Third-party package import completed."
