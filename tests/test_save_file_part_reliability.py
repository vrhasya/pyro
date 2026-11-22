"""Offline regression tests for acknowledged MTProto multipart uploads."""
import asyncio
import importlib
import io
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch


save_file_module = importlib.import_module(
    "pyrogram_styled.methods.advanced.save_file"
)
PART = 512 * 1024


class FakeFloodPremiumWait(Exception):
    def __init__(self, value):
        self.value = value
        super().__init__(str(value))


class FakeFloodWait(FakeFloodPremiumWait):
    pass


class FakeSession:
    behavior = {}
    instances = []

    def __init__(self, *_args, **_kwargs):
        self.calls = []
        self.started = False
        self.stopped = False
        self.instances.append(self)

    async def start(self):
        self.started = True

    async def stop(self):
        self.stopped = True

    async def invoke(self, rpc, *, sleep_threshold=10):
        self.calls.append((rpc.file_part, sleep_threshold))
        results = self.behavior.get(rpc.file_part, [])
        outcome = results.pop(0) if results else True
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome


def fake_raw():
    make_rpc = lambda **kwargs: SimpleNamespace(**kwargs)
    return SimpleNamespace(
        functions=SimpleNamespace(
            upload=SimpleNamespace(
                SaveBigFilePart=make_rpc,
                SaveFilePart=make_rpc,
            )
        ),
        types=SimpleNamespace(
            InputFile=make_rpc,
            InputFileBig=make_rpc,
        ),
    )


class SaveFileReliabilityTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        FakeSession.behavior = {}
        FakeSession.instances = []
        self.patches = [
            patch.object(save_file_module, "Session", FakeSession),
            patch.object(save_file_module, "raw", fake_raw()),
            patch.object(save_file_module, "FloodPremiumWait", FakeFloodPremiumWait),
            patch.object(save_file_module, "FloodWait", FakeFloodWait),
        ]
        for p in self.patches:
            p.start()
            self.addCleanup(p.stop)

    def client(self):
        return SimpleNamespace(
            save_file_semaphore=asyncio.Semaphore(1),
            me=SimpleNamespace(is_premium=False),
            rnd_id=lambda: 987654321,
            loop=asyncio.get_running_loop(),
            executor=None,
            storage=SimpleNamespace(
                dc_id=AsyncMock(return_value=2),
                auth_key=AsyncMock(return_value=b"auth"),
                test_mode=AsyncMock(return_value=False),
            ),
        )

    async def test_success_acknowledges_every_part_before_returning(self):
        updates = []

        async def progress(current, total):
            updates.append((current, total))

        payload = b"x" * (PART * 2 + 3)
        result = await save_file_module.SaveFile.save_file(
            self.client(), io.BytesIO(payload), progress=progress
        )
        self.assertEqual(result.parts, 3)
        self.assertEqual(
            [part for part, _ in FakeSession.instances[0].calls], [0, 1, 2]
        )
        self.assertEqual(updates[-1], (len(payload), len(payload)))
        self.assertTrue(FakeSession.instances[0].stopped)

    async def test_worker_failure_never_returns_an_input_file(self):
        FakeSession.behavior = {1: [OSError("upload part failed")]}
        with self.assertRaises(OSError):
            await save_file_module.SaveFile.save_file(
                self.client(), io.BytesIO(b"x" * (PART * 3))
            )
        self.assertTrue(FakeSession.instances[0].stopped)

    async def test_false_acknowledgement_is_an_error(self):
        FakeSession.behavior = {0: [False]}
        with self.assertRaises(OSError):
            await save_file_module.SaveFile.save_file(
                self.client(), io.BytesIO(b"x" * 30)
            )

    async def test_premium_flood_wait_retries_same_part(self):
        FakeSession.behavior = {0: [FakeFloodPremiumWait(13), True]}
        with patch.object(
            save_file_module.asyncio, "sleep", new_callable=AsyncMock
        ) as sleep:
            result = await save_file_module.SaveFile.save_file(
                self.client(), io.BytesIO(b"x" * 100)
            )
        self.assertEqual(result.parts, 1)
        self.assertEqual([p for p, _ in FakeSession.instances[0].calls], [0, 0])
        self.assertEqual([t for _, t in FakeSession.instances[0].calls], [0, 0])
        self.assertEqual(sleep.await_count, 1)
        self.assertGreater(sleep.await_args.args[0], 13)

    async def test_flood_wait_retries_are_bounded(self):
        FakeSession.behavior = {0: [FakeFloodPremiumWait(13) for _ in range(4)]}
        with patch.object(
            save_file_module.asyncio, "sleep", new_callable=AsyncMock
        ) as sleep:
            with self.assertRaises(FakeFloodPremiumWait):
                await save_file_module.SaveFile.save_file(
                    self.client(), io.BytesIO(b"x" * 100)
                )
        self.assertEqual(len(FakeSession.instances[0].calls), 4)
        self.assertEqual(sleep.await_count, 3)

    async def test_one_part_repair_waits_for_acknowledgement(self):
        result = await save_file_module.SaveFile.save_file(
            self.client(), io.BytesIO(b"x" * (PART * 3)),
            file_id=42, file_part=1,
        )
        self.assertIsNone(result)
        self.assertEqual(FakeSession.instances[0].calls, [(1, 0)])

    async def test_one_part_repair_propagates_failure(self):
        FakeSession.behavior = {1: [OSError("part repair failed")]}
        with self.assertRaises(OSError):
            await save_file_module.SaveFile.save_file(
                self.client(), io.BytesIO(b"x" * (PART * 3)),
                file_id=42, file_part=1,
            )

    async def test_large_file_premium_flood_wait_recovers_all_parts(self):
        # Real JOB #58 failed on files larger than 10 MiB (four upload workers).
        # A retry must preserve each part number and complete every part.
        FakeSession.behavior = {
            0: [FakeFloodPremiumWait(13), True],
            1: [FakeFloodPremiumWait(13), True],
        }
        payload = b"x" * (10 * 1024 * 1024 + 1)
        with patch.object(
            save_file_module.asyncio, "sleep", new_callable=AsyncMock
        ) as sleep:
            result = await save_file_module.SaveFile.save_file(
                self.client(), io.BytesIO(payload)
            )
        parts = [part for part, _ in FakeSession.instances[0].calls]
        self.assertEqual(result.parts, 21)
        self.assertEqual(parts.count(0), 2)
        self.assertEqual(parts.count(1), 2)
        self.assertEqual(set(parts), set(range(21)))
        self.assertGreaterEqual(sleep.await_count, 2)
        self.assertTrue(FakeSession.instances[0].stopped)

    async def test_large_file_acknowledges_all_parts(self):
        payload = b"x" * (10 * 1024 * 1024 + 1)
        result = await save_file_module.SaveFile.save_file(
            self.client(), io.BytesIO(payload)
        )
        self.assertEqual(result.parts, 21)
        self.assertEqual(len(FakeSession.instances[0].calls), 21)
        self.assertTrue(FakeSession.instances[0].stopped)


if __name__ == "__main__":
    unittest.main()
