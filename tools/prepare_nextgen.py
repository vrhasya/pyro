"""Prepare a disposable NextGen source tree; never modify the upstream checkout."""
from pathlib import Path
import hashlib
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[1]
UPSTREAM = ROOT / "upstream/kurigram"
DEST = ROOT / ".nextgen-build/kurigram"
PIN = "ed92ab8a8ef8958d9ff909c772ff99c2ade1fdba"
VERSION = "2.2.27.dev1+nextgen"
DISTRIBUTION = "c1ph3r-pyro-nextgen"
PATCHES = {
    Path("pyrogram/__init__.py"): (
        "4fe04974ce8d8411739f3e4cb405318d05e6e0f6",
        (('__version__ = "2.2.27"', f'__version__ = "{VERSION}"'),),
    ),
    Path("pyrogram/session/session.py"): (
        "9d709fe05564a434bda5b886d303b5dc8d1406f8",
        (('log.debug("Received: %s", data)', 'log.debug("Received MTProto packet: %s", type(data.body).__name__)'),
         ('log.debug("Sent: %s", message)', 'log.debug("Sent MTProto packet: %s", type(message.body).__name__)')),
    ),
    Path("pyrogram/client.py"): (
        "80e8f36a96bf9f449fd5a770de4432bdff2c2312",
        (('log.info(update)', 'log.debug("Received update type: %s", type(update).__name__)'),
         ('log.info(updates)', 'log.debug("Received updates type: %s", type(updates).__name__)')),
    ),
}
TARGETS = {
    Path("pyrogram/methods/advanced/save_file.py"): "a4c3546d5d1bbd9588d7e83724a3181619674602",
    Path("pyrogram/methods/messages/download_media.py"): "8ad53f9a92c49a1f6de9d1d35c2b199f33810895",
    Path("pyrogram/methods/messages/_nextgen_parallel_download.py"): None,
    Path("pyrogram_styled/__init__.py"): None,
    Path("pyrogram_styled/helpers/__init__.py"): None,
    Path("pyrogram_styled/helpers/helpers.py"): None,
}


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
    for target, expected in (TARGETS | {p: v[0] for p, v in PATCHES.items()}).items():
        original = UPSTREAM / target
        if expected is None:
            if original.exists():
                raise SystemExit(f"Unexpected upstream file: {target}")
            continue
        data = original.read_bytes()
        blob = hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()
        if blob != expected:
            raise SystemExit(f"Upstream source hash mismatch: {target}")
    project = (UPSTREAM / "pyproject.toml").read_bytes()
    project_blob = hashlib.sha1(b"blob " + str(len(project)).encode() + b"\0" + project).hexdigest()
    if project_blob != "15f38ec8b93462fe1eee33882da8dec67be7bfa6":
        raise SystemExit("Upstream packaging hash mismatch")
    if DEST.exists():
        raise SystemExit("Build tree exists; use a fresh checkout or remove only .nextgen-build")
    shutil.copytree(UPSTREAM, DEST, ignore=shutil.ignore_patterns(".git", "__pycache__", ".venv"))
    for target in TARGETS:
        (DEST / target).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / "overlays" / target, DEST / target)
    for target, (_, edits) in PATCHES.items():
        path = DEST / target
        source = path.read_text(encoding="utf-8")
        for old, new in edits:
            if source.count(old) != 1:
                raise SystemExit(f"Unexpected patch target: {target}")
            source = source.replace(old, new)
        path.write_text(source, encoding="utf-8")
    config = DEST / "pyproject.toml"
    text = config.read_text(encoding="utf-8")
    for old, new in (('name = "Kurigram"', f'name = "{DISTRIBUTION}"'),
                     ('Development Status :: 5 - Production/Stable', 'Development Status :: 3 - Alpha'),
                     ('packages = ["pyrogram"]', 'packages = ["pyrogram", "pyrogram_styled"]'),
                     ('    "/pyrogram",', '    "/pyrogram",\n    "/pyrogram_styled",')):
        if text.count(old) != 1:
            raise SystemExit("Unexpected upstream package declaration")
        text = text.replace(old, new)
    config.write_text(text, encoding="utf-8")
    notice = DEST / "NOTICE"
    with notice.open("a", encoding="utf-8") as file:
        file.write("\nC1PH3R Pyro NextGen: modified distribution (2026-11-25). "
                   "Based on pinned Kurigram; upload/download, compatibility and logging patches.\n")
    print("Prepared isolated NextGen source:", DEST)


if __name__ == "__main__":
    main()
