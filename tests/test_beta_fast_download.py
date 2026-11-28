"""Offline tests: no Telegram, VPS, session or production access."""
import asyncio
import importlib.util
import os
from pathlib import Path
import tempfile
import unittest
import sys
import types
from unittest.mock import patch
from concurrent.futures import ThreadPoolExecutor

MODULE_PATH = (
    Path(__file__).resolve().parents[1]
    / "pyrogram" / "methods" / "messages" / "_beta_fast_download.py"
)
spec = importlib.util.spec_from_file_location("beta_parallel_probe", MODULE_PATH)
module = importlib.util.module_from_spec(spec)
# Load only the isolated module, without importing the full Telegram client.
errors = types.ModuleType("pyrogram.errors")
for name in ("FloodWait", "FloodPremiumWait", "InternalServerError", "ServiceUnavailable"):
    setattr(errors, name, type(name, (Exception,), {}))
with patch.dict(sys.modules, {"pyrogram.errors": errors, spec.name: module}):
    spec.loader.exec_module(module)


class DummyClient:
    def __init__(self, data, fail=False, failures=None):
        self.data = data
        self.fail = fail
        self.failures = dict(failures or {})
        self.offsets = []
        self.delivered = []
        self.parallel = 0
        self.max_parallel = 0
        self.fallback_calls = 0
        self.executor = ThreadPoolExecutor(max_workers=2)

    async def get_file(self, file_id, file_size, limit, offset, *, beta_strict=False):
        assert beta_strict
        self.offsets.append(offset)
        self.parallel += 1
        self.max_parallel = max(self.max_parallel, self.parallel)
        try:
            for i in range(offset, offset + limit):
                if self.fail and i >= 1:
                    return
                if self.failures.get(i, 0):
                    self.failures[i] -= 1
                    raise OSError('simulated connection interruption')
                await asyncio.sleep(0.002)
                chunk = self.data[i * module.CHUNK_SIZE: (i + 1) * module.CHUNK_SIZE]
                if not chunk:
                    break
                self.delivered.append(i)
                yield chunk
        finally:
            self.parallel -= 1

    async def handle_download(self, packet):
        self.fallback_calls += 1
        return "STANDARD_FALLBACK"


class ParallelCopyTests(unittest.IsolatedAsyncioTestCase):
    async def test_complete_file_and_monotone_progress(self):
        data = (
            b"A" * module.CHUNK_SIZE * 4 +
            b"B" * module.CHUNK_SIZE * 4 +
            b"C" * module.CHUNK_SIZE * 4 +
            b"end!"
        )
        client = DummyClient(data)
        progress = []

        async def callback(current, total):
            progress.append((current, total))

        with tempfile.TemporaryDirectory() as directory:
            packet = (object(), directory, "test.bin", False, len(data), callback, ())
            path = await module.download_media_parallel(client, packet, workers=2)
            self.assertEqual(Path(path).read_bytes(), data)
            self.assertEqual(progress[-1], (len(data), len(data)))
            self.assertEqual([n for n, _ in progress], sorted(n for n, _ in progress))
            self.assertGreaterEqual(client.max_parallel, 2)
            self.assertLessEqual(client.max_parallel, 2)
            self.assertFalse(Path(path + ".temp").exists())
            self.assertEqual(client.fallback_calls, 0)
        client.executor.shutdown(wait=True)

    async def test_short_or_in_memory_falls_back(self):
        client = DummyClient(b"A")
        with tempfile.TemporaryDirectory() as directory:
            packet = (object(), directory, "test.bin", False, 1, None, ())
            self.assertEqual(
                await module.download_media_parallel(client, packet, workers=2),
                "STANDARD_FALLBACK",
            )
            self.assertEqual(client.fallback_calls, 1)
        client.executor.shutdown(wait=True)

    async def test_resume_only_missing_chunks(self):
        size = module.CHUNK_SIZE * 9 + 17
        data = b"".join(bytes([i]) * module.CHUNK_SIZE for i in range(10))[:size]
        client = DummyClient(data, failures={2: 1})
        self.addCleanup(client.executor.shutdown, wait=True)
        progress = []

        async def callback(current, total):
            progress.append(current)

        with tempfile.TemporaryDirectory() as directory:
            packet = (object(), directory, "test.bin", False, size, callback, ())
            path = await module.download_media_parallel(client, packet, workers=2)
            self.assertEqual(Path(path).read_bytes(), data)
            self.assertEqual(sorted(client.delivered), list(range(10)))
            self.assertIn(2, client.offsets)
            self.assertEqual(progress, sorted(progress))
            self.assertEqual(progress[-1], size)
            self.assertEqual(client.fallback_calls, 0)

    async def test_sequential_recovery_retains_ranges(self):
        size = module.CHUNK_SIZE * 13
        data = b"".join(bytes([i]) * module.CHUNK_SIZE for i in range(13))
        client = DummyClient(data, failures={2: module.MAX_ATTEMPTS})
        self.addCleanup(client.executor.shutdown, wait=True)
        with tempfile.TemporaryDirectory() as directory:
            packet = (object(), directory, "test.bin", False, size, None, ())
            path = await module.download_media_parallel(client, packet, workers=2)
            self.assertEqual(Path(path).read_bytes(), data)
            self.assertEqual(sorted(client.delivered), list(range(13)))
            self.assertEqual(client.fallback_calls, 0)

    async def test_cancel_cleans_temp_without_fallback(self):
        size = module.CHUNK_SIZE * 9
        client = DummyClient(b"X" * size)
        self.addCleanup(client.executor.shutdown, wait=True)

        async def cancel(current, total):
            raise asyncio.CancelledError

        with tempfile.TemporaryDirectory() as directory:
            packet = (object(), directory, "test.bin", False, size, cancel, ())
            with self.assertRaises(asyncio.CancelledError):
                await module.download_media_parallel(client, packet, workers=2)
            self.assertFalse(Path(directory, "test.bin.temp").exists())
            self.assertEqual(client.fallback_calls, 0)

    async def test_failed_range_removes_partial_file_and_falls_back(self):
        size = module.CHUNK_SIZE * 9
        client = DummyClient(b"X" * size, fail=True)
        with tempfile.TemporaryDirectory() as directory:
            packet = (object(), directory, "test.bin", False, size, None, ())
            output = await module.download_media_parallel(client, packet, workers=2)
            self.assertEqual(output, "STANDARD_FALLBACK")
            self.assertEqual(client.fallback_calls, 1)
            self.assertFalse(Path(directory, "test.bin.temp").exists())
            self.assertFalse(Path(directory, "test.bin").exists())
        client.executor.shutdown(wait=True)


if __name__ == "__main__":
    unittest.main()
