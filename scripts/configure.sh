#!/usr/bin/env bash
set -euo pipefail
# Run in the PonWrt source root after feeds install and customize.sh.
CI_DIR="$(cd "$(dirname "$0")/.." && pwd)"
if [ "$#" -ne 2 ]; then
  echo "Usage: configure.sh SUBTARGET CATALOG" >&2
  exit 2
fi
SUBTARGET="$1"
CATALOG="$(realpath "$2")"
python3 "$CI_DIR/scripts/devices.py" config "$SUBTARGET" "$CATALOG" > .config
cat "$CI_DIR/config/common.config" \
    "$CI_DIR/config/general-packages.config" \
    "$CI_DIR/config/pon-packages.config" >> .config
mkdir -p logs
make defconfig 2>&1 | tee logs/defconfig.log
if grep -q 'recursive dependency detected!' logs/defconfig.log; then
  echo 'ERROR: make defconfig reported recursive Kconfig dependencies; inspect logs/defconfig.log' >&2
  exit 1
fi
python3 "$CI_DIR/scripts/validate.py" config .config "$SUBTARGET" "$CATALOG"
mkdir -p files
cp -a "$CI_DIR/files/." files/
python3 - "$CI_DIR" <<'PY'
import pathlib
import sys
ci = pathlib.Path(sys.argv[1])
actual = set(pathlib.Path('.config').read_text().splitlines())
requested = set()
for name in ['common.config', 'general-packages.config', 'pon-packages.config']:
    requested.update(line for line in (ci / 'config' / name).read_text().splitlines()
                     if line.startswith('CONFIG_PACKAGE_') and line.endswith('=y'))
dropped = sorted(requested - actual)
pathlib.Path('requested-packages-dropped.txt').write_text(''.join(x + '\n' for x in dropped))
if dropped:
    print('Optional requested symbols unavailable after make defconfig:')
    print('\n'.join(dropped))
PY
