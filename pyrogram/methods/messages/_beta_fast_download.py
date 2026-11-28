"""Opt-in bounded MTProto download with in-process range recovery.

Network requests, DC routing, and CDN verification remain in get_file.
Completed chunks are retained in the private sparse file until the job ends.
No cross-process resume or changes to the default downloader.
"""
import asyncio
from contextlib import aclosing
from dataclasses import dataclass
import inspect
import logging
import math
import os
import re

from pyrogram.errors import FloodWait, FloodPremiumWait, InternalServerError, ServiceUnavailable

log = logging.getLogger(__name__)

CHUNK_SIZE = 1024 * 1024
MIN_SIZE = 8 * CHUNK_SIZE
MAX_WORKERS = 4
CHUNKS_PER_RANGE = 4
MAX_ATTEMPTS = 3


class ParallelDownloadIncomplete(OSError):
    """A range did not return the expected bytes."""


@dataclass
class _Range:
    next_chunk: int
    stop: int


async def _emit_progress(client, callback, args, current, total):
    if callback is None:
        return
    if inspect.iscoroutinefunction(callback):
        await callback(current, total, *args)
    else:
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(client.executor, lambda: callback(current, total, *args))


async def _disk_call(func, *args):
    # A cancelled await of to_thread does not stop the OS write. Drain it
    # before any worker can close/reuse the shared descriptor.
    task = asyncio.create_task(asyncio.to_thread(func, *args))
    try:
        return await asyncio.shield(task)
    except asyncio.CancelledError:
        await asyncio.gather(task, return_exceptions=True)
        raise


async def _parallel_file(client, packet, workers):
    file_id, directory, file_name, in_memory, file_size, progress, progress_args = packet
    if in_memory or not isinstance(file_size, int) or file_size < MIN_SIZE:
        return await client.handle_download(packet)

    workers = max(2, min(MAX_WORKERS, int(workers)))
    directory = os.fspath(directory)
    os.makedirs(directory, exist_ok=True)
    final_path = os.path.abspath(re.sub(r"\\", "/", os.path.join(directory, file_name)))
    temp_path = final_path + ".temp"
    fd = None
    owns_temp = False
    completed = 0
    cursor = 1
    degraded = False
    failed = []
    cooldown_until = 0.0
    progress_lock = asyncio.Lock()
    number_of_chunks = math.ceil(file_size / CHUNK_SIZE)

    async def wait_for_cooldown():
        while True:
            delay = cooldown_until - asyncio.get_running_loop().time()
            if delay <= 0:
                return
            await asyncio.sleep(delay)

    async def fetch_range(part):
        """Resume at the next verified, fully written chunk."""
        nonlocal completed, cooldown_until
        failures = 0
        while part.next_chunk < part.stop:
            await wait_for_cooldown()
            starting = part.next_chunk
            try:
                async with aclosing(client.get_file(
                    file_id, file_size, limit=part.stop - part.next_chunk,
                    offset=part.next_chunk, beta_strict=True
                )) as stream:
                    async for chunk in stream:
                        if part.next_chunk >= part.stop:
                            raise ParallelDownloadIncomplete("Unexpected extra Telegram chunk")
                        position = part.next_chunk * CHUNK_SIZE
                        expected = min(CHUNK_SIZE, file_size - position)
                        if len(chunk) != expected:
                            raise ParallelDownloadIncomplete(
                                f"Chunk {part.next_chunk}: expected {expected}, got {len(chunk)}"
                            )
                        view = memoryview(chunk)
                        written = 0
                        while written < len(view):
                            n = await _disk_call(os.pwrite, fd, view[written:], position + written)
                            if n <= 0:
                                raise OSError("File write returned zero bytes")
                            written += n
                        # Count once, only after the entire chunk is written.
                        part.next_chunk += 1
                        async with progress_lock:
                            completed += len(chunk)
                            await _emit_progress(client, progress, progress_args, completed, file_size)
                if part.next_chunk == part.stop:
                    return True
                raise ParallelDownloadIncomplete(f"Range ended at chunk {part.next_chunk}")
            except (FloodWait, FloodPremiumWait) as exc:
                # Respect the server wait, including across the other workers'
                # next requests; never treat it as a stall or retry immediately.
                delay = max(1, int(getattr(exc, "value", 1) or 1))
                cooldown_until = max(cooldown_until, asyncio.get_running_loop().time() + delay + 1)
                log.warning("Beta recovery | FloodWait=%ss | next_chunk=%s", delay, part.next_chunk)
                await wait_for_cooldown()
            except (OSError, InternalServerError, ServiceUnavailable) as exc:
                if part.next_chunk == part.stop:
                    return True
                failures = 1 if part.next_chunk > starting else failures + 1
                log.warning("Beta recovery | chunk=%s | attempt=%s/%s | %s",
                            part.next_chunk, failures, MAX_ATTEMPTS, type(exc).__name__)
                if failures >= MAX_ATTEMPTS:
                    return False
                await asyncio.sleep(min(2 ** (failures - 1), 4))
        return True

    async def worker():
        nonlocal cursor, degraded
        while not degraded and cursor < number_of_chunks:
            start = cursor
            cursor = min(cursor + CHUNKS_PER_RANGE, number_of_chunks)
            part = _Range(start, cursor)
            if not await fetch_range(part):
                failed.append(part)
                degraded = True
                return

    try:
        fd = os.open(temp_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        owns_temp = True
        await _disk_call(os.ftruncate, fd, file_size)
        # Warm the media session before opening simultaneous range requests.
        if not await fetch_range(_Range(0, 1)):
            raise ParallelDownloadIncomplete("Media session warmup failed")
        async with asyncio.TaskGroup() as group:
            for _ in range(min(workers, max(0, number_of_chunks - 1))):
                group.create_task(worker())

        if degraded:
            log.warning("Beta recovery | switching to sequential ranges | retained=%s/%s",
                        completed, file_size)
            # Retry only the unfilled tails of failed ranges and ranges not
            # yet assigned. Successful out-of-order chunks stay on disk.
            for part in failed:
                if not await fetch_range(part):
                    raise ParallelDownloadIncomplete(f"Recovery exhausted at chunk {part.next_chunk}")
            while cursor < number_of_chunks:
                start = cursor
                cursor = min(cursor + CHUNKS_PER_RANGE, number_of_chunks)
                if not await fetch_range(_Range(start, cursor)):
                    raise ParallelDownloadIncomplete(f"Recovery exhausted at range {start}")

        if completed != file_size:
            raise ParallelDownloadIncomplete(f"Download incomplete: {completed}/{file_size}")
        await _disk_call(os.fsync, fd)
        os.close(fd)
        fd = None
        os.replace(temp_path, final_path)
        owns_temp = False
        return final_path
    finally:
        if fd is not None:
            os.close(fd)
        if owns_temp and os.path.exists(temp_path):
            os.unlink(temp_path)


async def download_media_parallel(client, packet, workers=2):
    """Try recovery in-place, then use the original downloader on failure."""
    file_id, directory, file_name, in_memory, file_size, progress, args = packet
    if in_memory or not isinstance(file_size, int) or file_size < MIN_SIZE or not hasattr(os, "pwrite"):
        return await client.handle_download(packet)

    lock = getattr(client, "_beta_parallel_download_lock", None)
    if lock is None:
        lock = asyncio.Lock()
        client._beta_parallel_download_lock = lock

    async with lock:
        try:
            return await _parallel_file(client, packet, workers)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            log.warning("Beta recovery exhausted (%s); restarting with standard downloader", exc)
            await _emit_progress(client, progress, args, 0, file_size)
            result = await client.handle_download(packet)
            if not result:
                return None
            # The legacy get_file can end early after logging an RPC error.
            # Reject incomplete standard fallback results in beta mode.
            expected = os.path.abspath(re.sub(r"\\", "/", os.path.join(directory, file_name)))
            if os.path.abspath(os.fspath(result)) != expected:
                log.error("Beta recovery | unexpected fallback path")
                return None
            if not os.path.isfile(expected) or os.path.getsize(expected) != file_size:
                log.error("Beta recovery | incomplete standard fallback; discarding")
                if os.path.isfile(expected):
                    os.unlink(expected)
                return None
            return result
