"""Offline check: optional secret init must not register privileged handlers."""
import ast
from pathlib import Path

root = Path(__file__).resolve().parents[1]
secret = root / "pyrogram/helpers/secret.py"
start = root / "pyrogram/methods/utilities/start.py"
tree = ast.parse(secret.read_text(encoding="utf-8"))
func = next(node for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == "init_secret")
assert len(func.body) >= 1
assert isinstance(func.body[-1], ast.Return), "init_secret must return immediately"
assert isinstance(func.body[-1].value, ast.Constant) and func.body[-1].value.value is None
assert not any(isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "add_handler" for n in ast.walk(func))
assert "secret.init_secret(self)" in start.read_text(encoding="utf-8")
print("PASS: init_secret registers no handlers")
print("PASS: start.py compatibility call remains present")
print("STATIC ONLY: live safety and external execution routes not tested")
