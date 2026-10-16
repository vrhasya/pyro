"""Offline tests: no Telegram, VPS, session or production access."""
import asyncio
import importlib.util
import os
from pathlib import Path
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor

MODULE_PATH = (
    Path(__file__).resolve().parents[1]
    / "pyrogram" / "methods" / "messages" / "_beta_fast_download.py"
)
spec = importlib.util.spec_from_file_location("beta_parallel_probe", MODULE_PATH)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class DummyClient:
    def __init__(self, data, fail=False):
        self.data = data
        self.fail = fail
        self.parallel = 0
        self.max_parallel = 0
        self.fallback_calls = 0
        self.executor = ThreadPoolExecutor(max_workers=2)

    async def get_file(self, file_id, file_size, limit, offset):
        self.parallel += 1
        self.max_parallel = max(self.max_parallel, self.parallel)
        try:
            for i in range(offset, offset + limit):
                if self.fail and i >= 1:
                    return
                await asyncio.sleep(0.002)
                chunk = self.data[i * module.CHUNK_SIZE: (i + 1) * module.CHUNK_SIZE]
                if not chunk:
                    break
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
