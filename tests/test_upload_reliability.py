"""Offline tests of the installed Kurigram overlay (no credentials or network)."""
import asyncio
import hashlib
import io
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from pyrogram import StopTransmission, raw
from pyrogram.errors import FloodWait, FloodPremiumWait
from pyrogram.methods.advanced.save_file import SaveFile

PART = 512 * 1024


class FakeSession:
    def __init__(self, behavior=None):
        self.calls = []
        self.behavior = behavior

    async def invoke(self, rpc, *, sleep_threshold):
        self.calls.append((rpc.file_part, sleep_threshold))
        await asyncio.sleep(0)
        if self.behavior:
            return await self.behavior(rpc)
        return True


class FakeClient(SaveFile):
    def __init__(self, behavior=None):
        self.save_file_semaphore = asyncio.Semaphore(1)
        self.me = SimpleNamespace(is_premium=False)
        self.storage = SimpleNamespace(dc_id=self.dc_id)
        self.session = FakeSession(behavior)
        self.executor = None

    async def dc_id(self):
        return 5

    async def get_session(self, dc_id, *, is_media):
        assert dc_id == 5 and is_media
        return self.session

    def rnd_id(self):
        return 123


class UploadTests(unittest.IsolatedAsyncioTestCase):
    async def test_small_file_checksum_and_confirmed_progress(self):
        data = b"x" * (PART * 2 + 17)
        updates = []
        async def progress(current, total):
            updates.append((current, total))
        client = FakeClient()
        result = await client.save_file(io.BytesIO(data), progress=progress)
        self.assertIsInstance(result, raw.types.InputFile)
        self.assertEqual(result.parts, 3)
        self.assertEqual(result.md5_checksum, hashlib.md5(data).hexdigest())
        self.assertEqual(updates, [(PART, len(data)), (PART * 2, len(data)), (len(data), len(data))])
        self.assertEqual(client.session.calls, [(0, 0), (1, 0), (2, 0)])

    async def test_large_file_out_of_order_exact_progress(self):
        async def behavior(rpc):
            if rpc.file_part == 0:
                await asyncio.sleep(0.01)
            return True
        client = FakeClient(behavior)
        size = PART * 21 + 19
        updates = []
        result = await client.save_file(io.BytesIO(b"x" * size), progress=lambda c, t: updates.append(c))
        self.assertIsInstance(result, raw.types.InputFileBig)
        self.assertEqual(result.parts, 22)
        self.assertEqual(sorted(p for p, _ in client.session.calls), list(range(22)))
        self.assertEqual(updates, sorted(set(updates)))
        self.assertEqual(updates[-1], size)

    async def test_false_ack_fails(self):
        async def behavior(rpc):
            return False
        with self.assertRaises(OSError):
            await asyncio.wait_for(FakeClient(behavior).save_file(io.BytesIO(b"x" * PART * 8)), 2)

    async def test_worker_exception_no_deadlock(self):
        async def behavior(rpc):
            raise RuntimeError("failed part")
        with self.assertRaisesRegex(RuntimeError, "failed part"):
            await asyncio.wait_for(FakeClient(behavior).save_file(io.BytesIO(b"x" * PART * 21)), 2)

    async def test_flood_retry_same_part(self):
        attempts = 0
        async def behavior(rpc):
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                raise FloodPremiumWait(1)
            return True
        client = FakeClient(behavior)
        await asyncio.wait_for(client.save_file(io.BytesIO(b"x")), 5)
        self.assertEqual(client.session.calls, [(0, 0), (0, 0)])

    async def test_long_wait_propagates_without_retry(self):
        async def behavior(rpc):
            raise FloodWait(61)
        client = FakeClient(behavior)
        with self.assertRaises(FloodWait):
            await asyncio.wait_for(client.save_file(io.BytesIO(b"x")), 2)
        self.assertEqual(len(client.session.calls), 1)

    async def test_bounded_retry(self):
        async def behavior(rpc):
            raise FloodWait(1)
        client = FakeClient(behavior)
        with self.assertRaises(FloodWait):
            await asyncio.wait_for(client.save_file(io.BytesIO(b"x")), 10)
        self.assertEqual(client.session.calls, [(0, 0)] * 4)

    async def test_single_part_repair(self):
        client = FakeClient()
        result = await client.save_file(io.BytesIO(b"x" * (PART + 1)), file_id=77, file_part=1)
        self.assertIsNone(result)
        self.assertEqual(client.session.calls, [(1, 0)])

    async def test_repair_invalid_index(self):
        with self.assertRaises(ValueError):
            await FakeClient().save_file(io.BytesIO(b"x"), file_id=77, file_part=1)

    async def test_progress_stop_transmission(self):
        async def progress(current, total):
            raise StopTransmission()
        with self.assertRaises(StopTransmission):
            await asyncio.wait_for(FakeClient().save_file(io.BytesIO(b"x" * PART * 21), progress=progress), 2)

    async def test_cancellation_drains_tasks(self):
        entered = asyncio.Event()
        async def behavior(rpc):
            entered.set()
            await asyncio.Future()
        client = FakeClient(behavior)
        task = asyncio.create_task(client.save_file(io.BytesIO(b"x" * PART * 21)))
        await asyncio.wait_for(entered.wait(), 2)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await asyncio.wait_for(task, 2)
        self.assertFalse(client.save_file_semaphore.locked())

    async def test_source_ownership(self):
        stream = io.BytesIO(b"x")
        await FakeClient().save_file(stream)
        self.assertFalse(stream.closed)


if __name__ == "__main__":
    unittest.main()
