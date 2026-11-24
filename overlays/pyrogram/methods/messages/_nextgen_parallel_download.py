"""Opt-in bounded parallel download for the pinned Kurigram backend.

No session or DC overrides; all ranges pass through Client.get_file.
"""
import asyncio
from contextlib import aclosing
import functools
import inspect
import logging
import os
from pathlib import Path
import tempfile

from pyrogram import StopTransmission

log = logging.getLogger(__name__)
CHUNK_SIZE = 1024 * 1024
MIN_SIZE = 8 * CHUNK_SIZE
MAX_WORKERS = 4
CHUNKS_PER_RANGE = 4


class IncompleteRange(OSError):
    """A range ended early or returned bytes outside its expected size."""


async def download_parallel(client, packet, workers=2):
    file_id, directory, file_name, in_memory, file_size, progress, args = packet
    if (
        in_memory or not isinstance(file_size, int) or file_size < MIN_SIZE
        or not hasattr(os, "pwrite")
        or getattr(client, "max_concurrent_transmissions", 1) < 2
    ):
        return await client.handle_download(packet)

    workers = min(MAX_WORKERS, workers, client.max_concurrent_transmissions)
    lock = getattr(client, "_nextgen_parallel_lock", None)
    if lock is None:
        lock = client._nextgen_parallel_lock = asyncio.Lock()
    async with lock:
        final = Path(os.path.abspath(os.path.join(directory, file_name).replace("\\", "/")))
        final.parent.mkdir(parents=True, exist_ok=True)
        high_water = 0
        progress_lock = asyncio.Lock()

        async def emit(current, total):
            nonlocal high_water
            async with progress_lock:
                current = min(current, file_size)
                if current <= high_water:
                    return
                if progress:
                    callback = functools.partial(progress, current, file_size, *args)
                    if inspect.iscoroutinefunction(progress):
                        await callback()
                    else:
                        await asyncio.get_running_loop().run_in_executor(client.executor, callback)
                high_water = current

        fd, temp_name = tempfile.mkstemp(prefix=".nextgen-", suffix=".part", dir=final.parent)
        temp = Path(temp_name)
        tasks = []
        completed = 0
        cursor = 0
        count = (file_size + CHUNK_SIZE - 1) // CHUNK_SIZE
        fallback = False
        try:
            os.ftruncate(fd, file_size)

            async def fetch(start, length):
                nonlocal completed
                position = start * CHUNK_SIZE
                expected = min(length * CHUNK_SIZE, file_size - position)
                received = 0
                stream = client.get_file(file_id, file_size, limit=length, offset=start)
                async with aclosing(stream):
                    async for chunk in stream:
                        remaining = expected - received
                        if not chunk or len(chunk) != min(CHUNK_SIZE, remaining):
                            raise IncompleteRange("Unexpected range chunk length")
                        view = memoryview(chunk)
                        written = 0
                        # Positional writes do not share a file cursor. Keep them synchronous
                        # so cancellation cannot close/reuse an fd while a thread is writing.
                        while written < len(view):
                            n = os.pwrite(fd, view[written:], position + received + written)
                            if n <= 0:
                                raise OSError("Positional write returned zero bytes")
                            written += n
                        received += len(chunk)
                        completed += len(chunk)
                        await emit(completed, file_size)
                if received != expected:
                    raise IncompleteRange("Range ended before expected byte count")

            async def worker():
                nonlocal cursor
                while cursor < count:
                    start = cursor
                    length = min(CHUNKS_PER_RANGE, count - cursor)
                    cursor += length
                    await fetch(start, length)

            # Warm up the cached DC media session before parallel range requests.
            await fetch(0, 1)
            cursor = 1
            tasks = [asyncio.create_task(worker()) for _ in range(min(workers, count - 1))]
            # Gather propagates the original exception. Cancel/join siblings below.
            await asyncio.gather(*tasks)
            if completed != file_size:
                raise IncompleteRange("Parallel download did not receive all bytes")
            os.fsync(fd)
            os.replace(temp, final)
            return str(final)
        except IncompleteRange:
            # Only an incomplete range is eligible for automatic fallback.
            # Flood waits, hash failures, permission errors, disk errors and
            # callback exceptions must not trigger a second network transfer.
            fallback = True
        except StopTransmission:
            return None
        finally:
            for task in tasks:
                if not task.done():
                    task.cancel()
            if tasks:
                results = await asyncio.gather(*tasks, return_exceptions=True)
                if fallback:
                    # Do not hide a concurrent FloodWait or other non-range failure.
                    for result in results:
                        if isinstance(result, BaseException) and not isinstance(
                            result, (IncompleteRange, asyncio.CancelledError)
                        ):
                            fallback = False
                            if isinstance(result, StopTransmission):
                                return None
                            # Cleanup still runs before this exception is raised.
                            os.close(fd)
                            temp.unlink(missing_ok=True)
                            raise result
            os.close(fd)
            temp.unlink(missing_ok=True)

        if fallback:
            log.warning("Incomplete parallel range; reverting to standard downloader")
            # A private directory prevents standard .temp names colliding with
            # another transfer, and an incomplete fallback never replaces final.
            with tempfile.TemporaryDirectory(prefix=".nextgen-fallback-", dir=final.parent) as work:
                result = await client.handle_download(
                    (file_id, work, "payload", False, file_size, emit, ())
                )
                if result is None:
                    return None
                path = Path(result)
                if path != Path(work) / "payload" or path.stat().st_size != file_size:
                    raise IncompleteRange("Standard fallback did not return a complete file")
                with path.open("rb") as handle:
                    os.fsync(handle.fileno())
                await emit(file_size, file_size)
                os.replace(path, final)
                return str(final)
