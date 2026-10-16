"""Opt-in bounded parallel MTProto downloads for the C1PH3R beta client.

Only activated when download_media(beta_parallel=True) is explicitly requested.
The existing Pyrogram get_file implementation remains the network backend,
including Telegram DC routing, CDN decryption and CDN hash verification.
"""
import asyncio
import inspect
import logging
import math
import os
import re

log = logging.getLogger(__name__)

CHUNK_SIZE = 1024 * 1024
MIN_SIZE = 8 * CHUNK_SIZE
MAX_WORKERS = 4
CHUNKS_PER_RANGE = 4


class ParallelDownloadIncomplete(OSError):
    """A range did not return the exact bytes expected for that offset."""


async def _emit_progress(client, callback, args, current, total):
    if callback is None:
        return
    if inspect.iscoroutinefunction(callback):
        await callback(current, total, *args)
    else:
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(
            client.executor,
            lambda: callback(current, total, *args),
        )


async def _parallel_file(client, packet, workers):
    file_id, directory, file_name, in_memory, file_size, progress, progress_args = packet
    if in_memory or not isinstance(file_size, int) or file_size < MIN_SIZE:
        return await client.handle_download(packet)

    workers = max(2, min(MAX_WORKERS, int(workers)))
    directory = os.fspath(directory)
    os.makedirs(directory, exist_ok=True)
    # Match the standard Pyrogram temp / final naming behavior.
    final_path = os.path.abspath(
        re.sub(r"\\", "/", os.path.join(directory, file_name))
    )
    temp_path = final_path + ".temp"
    fd = None
    completed = 0
    cursor = 0
    progress_lock = asyncio.Lock()
    number_of_chunks = math.ceil(file_size / CHUNK_SIZE)

    async def fetch_range(start_chunk, chunk_count):
        nonlocal completed
        beginning = start_chunk * CHUNK_SIZE
        needed = min(file_size - beginning, chunk_count * CHUNK_SIZE)
        received = 0
        async for chunk in client.get_file(
            file_id, file_size, limit=chunk_count, offset=start_chunk
        ):
            if not chunk:
                raise ParallelDownloadIncomplete("Empty Telegram chunk")
            if len(chunk) > CHUNK_SIZE or received + len(chunk) > needed:
                raise ParallelDownloadIncomplete("Unexpected range size")
            # Position-based writes permit out-of-order completion without
            # holding the whole media in memory.
            view = memoryview(chunk)
            written = 0
            while written < len(view):
                n = await asyncio.to_thread(
                    os.pwrite, fd, view[written:], beginning + received + written
                )
                if n <= 0:
                    raise OSError("File write returned zero bytes")
                written += n
            received += len(chunk)
            async with progress_lock:
                completed += len(chunk)
                await _emit_progress(
                    client, progress, progress_args, completed, file_size
                )
        if received != needed:
            raise ParallelDownloadIncomplete(
                f"Range {start_chunk}: expected {needed}, got {received}"
            )

    async def worker():
        nonlocal cursor
        while cursor < number_of_chunks:
            start = cursor
            count = min(CHUNKS_PER_RANGE, number_of_chunks - start)
            cursor += count
            await fetch_range(start, count)

    try:
        fd = os.open(
            temp_path,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL,
            0o600,
        )
        await asyncio.to_thread(os.ftruncate, fd, file_size)
        # Warm up the DC media session before concurrent get_file invocations.
        await fetch_range(0, 1)
        cursor = 1
        async with asyncio.TaskGroup() as group:
            for _ in range(min(workers, max(0, number_of_chunks - 1))):
                group.create_task(worker())
        if completed != file_size:
            raise ParallelDownloadIncomplete(
                f"Download is incomplete: {completed}/{file_size}"
            )
        await asyncio.to_thread(os.fsync, fd)
        os.close(fd)
        fd = None
        os.replace(temp_path, final_path)
        return final_path
    finally:
        if fd is not None:
            os.close(fd)
        if os.path.exists(temp_path):
            os.unlink(temp_path)


async def download_media_parallel(client, packet, workers=2):
    """Try bounded parallel ranges; fall back to normal get_file on failure.

    Never use this routine for in-memory downloads. Parallel reads rely on
    standard get_file for CDN integrity handling. The beta userbot client must
    be initialized with max_concurrent_transmissions >= worker count.
    """
    file_id, directory, file_name, in_memory, file_size, progress, args = packet
    if (
        in_memory
        or not isinstance(file_size, int)
        or file_size < MIN_SIZE
        or not hasattr(os, "pwrite")
    ):
        return await client.handle_download(packet)

    # Serialize fast downloads on the same userbot account. This also bounds
    # aggregate in-flight media buffers when copy commands overlap.
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
            log.warning(
                "Beta parallel download failed (%s), reverting to standard downloader",
                exc,
            )
            return await client.handle_download(packet)
