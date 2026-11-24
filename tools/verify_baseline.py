"""Offline baseline verification. Does not connect to Telegram."""
from pathlib import Path
import importlib
import subprocess

ROOT = Path(__file__).resolve().parents[1]
UPSTREAM = ROOT / "upstream" / "kurigram"
PIN = "ed92ab8a8ef8958d9ff909c772ff99c2ade1fdba"

def check(condition, message):
    if not condition:
        raise SystemExit("FAIL: " + message)
    print("PASS: " + message)

def main():
    check((UPSTREAM / "pyrogram" / "__init__.py").is_file(), "upstream submodule initialized")
    head = subprocess.check_output(["git", "-C", str(UPSTREAM), "rev-parse", "HEAD"], text=True).strip()
    check(head == PIN, "upstream commit pin")
    schema = (UPSTREAM / "compiler/api/source/main_api.tl").read_text(encoding="utf-8")
    check(any(line.strip() == "// LAYER 234" for line in schema.splitlines()), "API layer 234")
    startup = (UPSTREAM / "pyrogram/methods/utilities/start.py").read_text(encoding="utf-8")
    check("init_secret(" not in startup, "no legacy init_secret startup call")
    pyro = importlib.import_module("pyrogram")
    check(pyro.__version__ == "2.2.27", "installed version 2.2.27")
    check(hasattr(pyro.Client, "send_rich_message"), "Native Rich send method")
    check(hasattr(pyro.types, "InputRichMessage"), "Native Rich input type")
    print("Baseline checks complete. No Telegram session started.")

if __name__ == "__main__":
    main()
