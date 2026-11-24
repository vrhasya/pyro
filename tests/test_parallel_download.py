"""Offline regression cases for the NextGen range downloader."""
import asyncio
import hashlib
import tempfile
import unittest
from pathlib import Path

from pyrogram import StopTransmission
from pyrogram.errors import FloodWait
from pyrogram.methods.messages._nextgen_parallel_download import (
    CHUNK_SIZE, MIN_SIZE, IncompleteRange, download_parallel,
)

C = CHUNK_SIZE


class FakeClient:
    max_concurrent_transmissions = 4
    executor = None

    def __init__(self, payload, fault=None, fallback_short=False):
        self.payload = payload
        self.fault = fault
        self.fallback_short = fallback_short
        self.calls = []
        self.standard = 0
        self.active = 0
        self.peak = 0

    async def get_file(self, file_id, file_size, *, limit, offset):
        self.calls.append((offset, limit))
        self.active += 1
        self.peak = max(self.peak, self.active)
        try:
            for index in range(offset, offset + limit):
                await asyncio.sleep(0.001 if offset != 1 else 0.003)
                if index == 2 and self.fault:
                    if self.fault == "short":
                        return
                    if self.fault == "flood":
                        raise FloodWait(30)
                    if self.fault == "hash":
                        raise RuntimeError("CDN integrity failure")
                yield self.payload[index * C:(index + 1) * C]
        finally:
            self.active -= 1

    async def handle_download(self, packet):
        self.standard += 1
        _, directory, name, memory, size, progress, args = packet
        if memory:
            return "standard-memory"
        out = Path(directory) / name
        out.parent.mkdir(parents=True, exist_ok=True)
        data = self.payload[:-1] if self.fallback_short else self.payload
        out.write_bytes(data)
        if progress:
            await progress(len(data), size, *args)
        return str(out)


class DownloadTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.data = b"".join(bytes([i]) * C for i in range(13)) + b"tail"
        self.final = self.root / "video.bin"

    def packet(self, progress=None, size=None, memory=False):
        return ("file", self.root, self.final.name, memory,
                len(self.data) if size is None else size, progress, ())

    def assert_clean(self):
        self.assertFalse(list(self.root.glob(".nextgen-*")))

    async def test_parallel_exact_content_and_progress(self):
        client = FakeClient(self.data)
        updates = []
        async def progress(current, total):
            updates.append((current, total))
        result = await download_parallel(client, self.packet(progress), 4)
        self.assertEqual(Path(result), self.final)
        self.assertEqual(hashlib.sha256(self.final.read_bytes()).digest(), hashlib.sha256(self.data).digest())
        self.assertGreater(client.peak, 1)
        self.assertLessEqual(client.peak, 4)
        self.assertEqual(client.standard, 0)
        self.assertEqual(updates[-1], (len(self.data), len(self.data)))
        self.assertEqual([p for p, _ in updates], sorted(set(p for p, _ in updates)))
        self.assert_clean()

    async def test_worker_cap(self):
        client = FakeClient(self.data)
        client.max_concurrent_transmissions = 2
        await download_parallel(client, self.packet(), 4)
        self.assertEqual(client.peak, 2)

    async def test_incomplete_range_falls_back(self):
        client = FakeClient(self.data, "short")
        updates = []
        async def progress(current, total):
            updates.append(current)
        await download_parallel(client, self.packet(progress), 4)
        self.assertEqual(client.standard, 1)
        self.assertEqual(self.final.read_bytes(), self.data)
        self.assertEqual(updates, sorted(set(updates)))
        self.assertEqual(client.active, 0)
        self.assert_clean()

    async def test_short_fallback_preserves_existing_file(self):
        client = FakeClient(self.data, "short", True)
        self.final.write_bytes(b"previous")
        with self.assertRaises(IncompleteRange):
            await download_parallel(client, self.packet(), 4)
        self.assertEqual(self.final.read_bytes(), b"previous")
        self.assert_clean()

    async def test_flood_wait_no_fallback(self):
        client = FakeClient(self.data, "flood")
        with self.assertRaises(FloodWait):
            await download_parallel(client, self.packet(), 4)
        self.assertEqual(client.standard, 0)
        self.assertFalse(self.final.exists())
        self.assertEqual(client.active, 0)
        self.assert_clean()

    async def test_integrity_error_no_fallback(self):
        client = FakeClient(self.data, "hash")
        with self.assertRaisesRegex(RuntimeError, "integrity"):
            await download_parallel(client, self.packet(), 4)
        self.assertEqual(client.standard, 0)
        self.assertFalse(self.final.exists())
        self.assert_clean()

    async def test_callback_error_no_fallback(self):
        client = FakeClient(self.data)
        async def progress(current, total):
            raise ValueError("callback failure")
        with self.assertRaisesRegex(ValueError, "callback failure"):
            await download_parallel(client, self.packet(progress))
        self.assertEqual(client.standard, 0)
        self.assert_clean()

    async def test_stop_transmission(self):
        client = FakeClient(self.data)
        async def progress(current, total):
            raise StopTransmission()
        self.assertIsNone(await download_parallel(client, self.packet(progress)))
        self.assertFalse(self.final.exists())
        self.assertEqual(client.active, 0)
        self.assert_clean()

    async def test_cancel_while_ranges_active(self):
        client = FakeClient(self.data)
        task = asyncio.create_task(download_parallel(client, self.packet(), 4))
        async def started():
            while client.active < 2:
                await asyncio.sleep(0.0001)
        await asyncio.wait_for(started(), 2)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertFalse(self.final.exists())
        self.assertEqual(client.active, 0)
        self.assertEqual(client.standard, 0)
        self.assert_clean()

    async def test_small_unknown_or_memory_uses_standard(self):
        for size, memory in [(MIN_SIZE - 1, False), (0, False), (len(self.data), True)]:
            client = FakeClient(self.data)
            await download_parallel(client, self.packet(size=size, memory=memory))
            self.assertEqual(client.standard, 1)
            self.assertFalse(client.calls)

    async def test_single_transmission_uses_standard(self):
        client = FakeClient(self.data)
        client.max_concurrent_transmissions = 1
        await download_parallel(client, self.packet(), 4)
        self.assertEqual(client.standard, 1)
        self.assertFalse(client.calls)

    async def test_invalid_worker_count(self):
        client = FakeClient(self.data)
        for workers in (0, 1, 5, True, "2"):
            with self.assertRaises(ValueError):
                await download_parallel(client, self.packet(), workers)
        self.assertFalse(client.calls)
