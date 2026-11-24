"""Prepare a disposable NextGen source tree; never modify the upstream checkout."""
from pathlib import Path
import hashlib
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[1]
UPSTREAM = ROOT / "upstream/kurigram"
DEST = ROOT / ".nextgen-build/kurigram"
PIN = "ed92ab8a8ef8958d9ff909c772ff99c2ade1fdba"
TARGET = Path("pyrogram/methods/advanced/save_file.py")
BLOB = "a4c3546d5d1bbd9588d7e83724a3181619674602"


def main():
    head = subprocess.check_output(
        ["git", "-C", str(UPSTREAM), "rev-parse", "HEAD"], text=True
    ).strip()
    if head != PIN:
        raise SystemExit("Upstream pin mismatch")
    dirty = subprocess.check_output(
        ["git", "-C", str(UPSTREAM), "status", "--porcelain", "--untracked-files=all"],
        text=True,
    )
    if dirty:
        raise SystemExit("Upstream checkout is not clean")
    data = (UPSTREAM / TARGET).read_bytes()
    blob = hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()
    if blob != BLOB:
        raise SystemExit("Upload source hash mismatch")
    if DEST.exists():
        raise SystemExit("Build tree exists; use a fresh checkout or remove only .nextgen-build")
    shutil.copytree(UPSTREAM, DEST, ignore=shutil.ignore_patterns(".git", "__pycache__", ".venv"))
    shutil.copyfile(ROOT / "overlays" / TARGET, DEST / TARGET)
    print("Prepared isolated NextGen source:", DEST)


if __name__ == "__main__":
    main()
