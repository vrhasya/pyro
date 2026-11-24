"""Offline guard checks for inspected security boundaries; not a full audit."""
import ast
import importlib.util
import inspect
from importlib import metadata
from pathlib import Path
import sys
import unittest

import pyrogram
import pyrogram_styled

ROOT = Path(__file__).resolve().parents[1]
CORE = Path(pyrogram.__file__).resolve().parent
STYLED = Path(pyrogram_styled.__file__).resolve().parent


class SecurityGuards(unittest.TestCase):
    def test_distribution_identity(self):
        self.assertEqual(pyrogram.__version__, "2.2.27.dev1+nextgen")
        self.assertEqual(metadata.version("c1ph3r-pyro-nextgen"), pyrogram.__version__)
        self.assertIs(pyrogram.Client, pyrogram_styled.Client)
        self.assertNotEqual(sys.prefix, sys.base_prefix)

    def test_namespace_ownership(self):
        mapping = metadata.packages_distributions()
        for namespace in ("pyrogram", "pyrogram_styled"):
            self.assertEqual({n.lower().replace("_", "-") for n in mapping.get(namespace, [])},
                             {"c1ph3r-pyro-nextgen"})

    def test_no_legacy_secret_module(self):
        self.assertFalse((CORE / "helpers/secret.py").exists())
        self.assertFalse((STYLED / "helpers/secret.py").exists())
        self.assertNotIn("init_secret", inspect.getsource(pyrogram.Client.start))

    def test_no_shell_or_eval_in_custom_overlays(self):
        for source in (ROOT / "overlays").rglob("*.py"):
            tree = ast.parse(source.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.Call):
                    name = node.func.id if isinstance(node.func, ast.Name) else (
                        node.func.attr if isinstance(node.func, ast.Attribute) else "")
                    self.assertNotIn(name, {"exec", "eval", "system", "Popen",
                                            "create_subprocess_shell", "init_secret"},
                                     f"Unexpected execution call in {source.name}")
                if isinstance(node, (ast.Import, ast.ImportFrom)):
                    names = [a.name for a in node.names]
                    if isinstance(node, ast.ImportFrom):
                        names.append(node.module or "")
                    self.assertFalse(any(n.split(".")[-1] == "secret" for n in names))

    def test_packet_logs_omit_payloads(self):
        source = (CORE / "session/session.py").read_text(encoding="utf-8")
        self.assertNotIn('log.debug("Received: %s", data)', source)
        self.assertNotIn('log.debug("Sent: %s", message)', source)
        self.assertIn('type(data.body).__name__', source)
        self.assertIn('type(message.body).__name__', source)
        client = (CORE / "client.py").read_text(encoding="utf-8")
        self.assertNotIn("log.info(update)", client)
        self.assertNotIn("log.info(updates)", client)

    def test_installed_overlays_match_reviewed_sources(self):
        for path in (ROOT / "overlays").rglob("*.py"):
            relative = path.relative_to(ROOT / "overlays")
            installed = (CORE.parent / relative)
            self.assertEqual(path.read_bytes(), installed.read_bytes(), str(relative))

    def test_no_deploy_workflow(self):
        workflow = ROOT / ".github/workflows/nextgen-baseline.yml"
        data = workflow.read_text(encoding="utf-8")
        self.assertIn("branches: [nextgen]", data)
        self.assertIn("contents: read", data)
        self.assertNotIn("secrets.", data)
        self.assertNotIn("self-hosted", data)
