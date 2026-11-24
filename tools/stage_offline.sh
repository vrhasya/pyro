#!/usr/bin/env bash
# Offline wheel acceptance only: no Telegram, systemd, VPS or existing sessions.
set -euo pipefail
umask 077
if [[ $# -ne 3 ]]; then
  echo "Usage: bash tools/stage_offline.sh WHEEL WHEELHOUSE EXPECTED_SHA256" >&2
  exit 2
fi
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
WHEEL="$(realpath -- "$1")"
WHEELHOUSE="$(realpath -- "$2")"
EXPECTED="$3"
[[ -f "$WHEEL" && -d "$WHEELHOUSE" && "$EXPECTED" =~ ^[a-fA-F0-9]{64}$ ]]
[[ "$(basename "$WHEEL")" == c1ph3r_pyro_nextgen-*.whl ]]
ACTUAL="$(sha256sum -- "$WHEEL" | cut -d' ' -f1)"
[[ "$ACTUAL" == "${EXPECTED,,}" ]] || { echo "Wheel hash mismatch" >&2; exit 1; }
STAGE="$(mktemp -d /tmp/nextgen-offline.XXXXXXXX)"
trap 'rm -rf -- "$STAGE"' EXIT
mkdir -m 700 "$STAGE/home"
PYTHON="$(command -v python3)"
# Ignore inherited app credentials, pip configuration, virtualenv and PYTHONPATH.
env -i PATH=/usr/bin:/bin HOME="$STAGE/home" "$PYTHON" -m venv "$STAGE/venv"
run() {
  env -i PATH=/usr/bin:/bin HOME="$STAGE/home" PIP_CONFIG_FILE=/dev/null \
    PIP_NO_INDEX=1 PIP_DISABLE_PIP_VERSION_CHECK=1 PYTHONNOUSERSITE=1 \
    "$STAGE/venv/bin/python" "$@"
}
cd -- "$STAGE/home"
run -m pip install --no-index --only-binary=:all: --find-links "$WHEELHOUSE" "$WHEEL[fast]"
run -m pip check
run "$ROOT/tools/verify_baseline.py"
run -m unittest discover -s "$ROOT/tests" -p 'test_*.py' -v
if find "$STAGE/home" -name '*.session*' -print -quit | grep -q .; then
  echo "Unexpected session file" >&2; exit 1
fi
echo "OFFLINE STAGING ACCEPTANCE PASS"
