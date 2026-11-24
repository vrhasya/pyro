#  Pyrogram - Telegram MTProto API Client Library for Python
#  Copyright (C) 2017-present Dan <https://github.com/delivrance>
#
#  This file is part of Pyrogram.
#
#  Pyrogram is free software: you can redistribute it and/or modify
#  it under the terms of the GNU Lesser General Public License as published
#  by the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.
#
#  Pyrogram is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU Lesser General Public License for more details.
#
#  You should have received a copy of the GNU Lesser General Public License
#  along with Pyrogram.  If not, see <http://www.gnu.org/licenses/>.

from __future__ import annotations as _annotations

import asyncio
import functools
import inspect
import io
import logging
import math
import os
from hashlib import md5
from typing import TYPE_CHECKING, BinaryIO, overload

import pyrogram
from pyrogram import raw
from pyrogram.errors import FloodWait, FloodPremiumWait

if TYPE_CHECKING:
    from collections.abc import Callable

    from pyrogram._typing import PathType

log = logging.getLogger(__name__)


class SaveFile:
    # The three shapes below are what the body already does, so a caller storing the result
    #  into a required `InputFile` field is not asked to handle a `None` the arguments it
    #  passed cannot produce.
    #
    # Each repeats the implementation's `self`: a bare one reads as `SaveFile`, which is
    #  wider than `Client`, and an overload the implementation does not accept is an error.
    @overload
    async def save_file(
        self: pyrogram.Client,
        path: None,
        file_id: int | None = None,
        file_part: int = 0,
        progress: Callable | None = None,
        progress_args: tuple = (),
    ) -> None: ...

    @overload
    async def save_file(
        self: pyrogram.Client,
        path: PathType | BinaryIO,
        file_id: int,
        file_part: int = 0,
        progress: Callable | None = None,
        progress_args: tuple = (),
    ) -> None: ...

    @overload
    async def save_file(
        self: pyrogram.Client,
        path: PathType | BinaryIO,
        file_id: None = None,
        file_part: int = 0,
        progress: Callable | None = None,
        progress_args: tuple = (),
    ) -> raw.types.InputFile | raw.types.InputFileBig: ...

    async def save_file(
        self: pyrogram.Client,
        path: PathType | BinaryIO | None,
        file_id: int | None = None,
        file_part: int = 0,
        progress: Callable | None = None,
        progress_args: tuple = (),
    ) -> raw.types.InputFile | raw.types.InputFileBig | None:
        """Upload a file onto Telegram servers, without actually sending the message to anyone.
        Useful whenever an InputFile type is required.

        .. note::

            This is a utility method intended to be used **only** when working with raw
            :obj:`functions <pyrogram.raw.functions>` (i.e: a Telegram API method you wish to use which is not
            available yet in the Client class as an easy-to-use method).

        .. include:: /_includes/usable-by/users-bots.rst

        Parameters:
            path (``str`` | ``os.PathLike`` | ``BinaryIO``):
                The path of the file you want to upload that exists on your local machine or a binary file-like object
                with its attribute ".name" set for in-memory uploads.

            file_id (``int``, *optional*):
                In case a file part expired, pass the file_id and the file_part to retry uploading that specific chunk.

            file_part (``int``, *optional*):
                In case a file part expired, pass the file_id and the file_part to retry uploading that specific chunk.

            progress (``Callable``, *optional*):
                Pass a callback function to view the file transmission progress.
                The function must take *(current, total)* as positional arguments (look at Other Parameters below for a
                detailed description) and will be called back each time a new file chunk has been successfully
                transmitted.

            progress_args (``tuple``, *optional*):
                Extra custom arguments for the progress callback function.
                You can pass anything you need to be available in the progress callback scope; for example, a Message
                object or a Client instance in order to edit the message with the updated progress status.

        Other Parameters:
            current (``int``):
                The amount of bytes transmitted so far.

            total (``int``):
                The total size of the file.

            *args (``tuple``, *optional*):
                Extra custom arguments as defined in the ``progress_args`` parameter.
                You can either keep ``*args`` or add every single extra argument in your function signature.

        Returns:
            ``InputFile`` | ``None``: On success, the uploaded file is returned in form of an InputFile object. In case
            *path* is None, and in case *file_id* is given so that a single missing part is uploaded instead of the
            whole file, None is returned. A failed upload raises.

        Raises:
            RPCError: In case of a Telegram RPC error, including one that happened while a part was being sent.
        """
        # C1PH3R NextGen: verify every part and preserve Kurigram's cached media session.
        async with self.save_file_semaphore:
            if path is None:
                return None

            part_size = 512 * 1024
            owns_fp = isinstance(path, (str, os.PathLike))
            if owns_fp:
                fp = open(path, "rb")
            elif isinstance(path, io.IOBase):
                fp = path
            else:
                raise ValueError("Expected a binary file or path")

            tasks = []
            try:
                file_name = getattr(fp, "name", "file.jpg")
                fp.seek(0, os.SEEK_END)
                file_size = fp.tell()
                limit_mib = 4000 if self.me and self.me.is_premium else 2000
                if file_size <= 0 or file_size > limit_mib * 1024 * 1024:
                    raise ValueError("Invalid file size for Telegram upload")
                total = math.ceil(file_size / part_size)
                repair = file_id is not None
                if not 0 <= file_part < total or (not repair and file_part != 0):
                    raise ValueError("Invalid upload part index")
                is_big = file_size > 10 * 1024 * 1024
                file_id = self.rnd_id() if file_id is None else file_id
                checksum = md5() if not is_big and not repair else None
                session = await self.get_session(await self.storage.dc_id(), is_media=True)
                loop = asyncio.get_running_loop()
                queue = asyncio.Queue(maxsize=1)
                gate = asyncio.Lock()
                progress_lock = asyncio.Lock()
                deadline = 0.0
                confirmed = 0

                async def upload_part(rpc):
                    nonlocal deadline
                    for attempt in range(4):
                        # Recheck after waking: another worker may extend the wait.
                        while True:
                            async with gate:
                                delay = deadline - loop.time()
                            if delay <= 0:
                                break
                            await asyncio.sleep(delay)
                        try:
                            ack = await session.invoke(rpc, sleep_threshold=0)
                            if ack is not True:
                                raise OSError("Telegram did not acknowledge upload part")
                            return
                        except (FloodWait, FloodPremiumWait) as exc:
                            seconds = exc.seconds
                            if seconds is None:
                                raise
                            wait = max(1, seconds)
                            async with gate:
                                deadline = max(deadline, loop.time() + wait + 1)
                            if wait > 60 or attempt == 3:
                                raise
                            log.warning("Upload part flood wait: %s seconds", wait)

                async def worker():
                    nonlocal confirmed
                    while True:
                        item = await queue.get()
                        if item is None:
                            return
                        rpc, size = item
                        await upload_part(rpc)
                        async with progress_lock:
                            confirmed += size
                            if progress and not repair:
                                callback = functools.partial(
                                    progress, confirmed, file_size, *progress_args
                                )
                                if inspect.iscoroutinefunction(progress):
                                    await callback()
                                else:
                                    await loop.run_in_executor(self.executor, callback)

                async def producer():
                    fp.seek(part_size * file_part)
                    for index in range(file_part, file_part + 1 if repair else total):
                        expected = min(part_size, file_size - index * part_size)
                        chunk = fp.read(expected)
                        if not isinstance(chunk, bytes) or len(chunk) != expected:
                            raise OSError("Upload source changed or returned an incomplete part")
                        if checksum is not None:
                            checksum.update(chunk)
                        if is_big:
                            rpc = raw.functions.upload.SaveBigFilePart(
                                file_id=file_id, file_part=index,
                                file_total_parts=total, bytes=chunk
                            )
                        else:
                            rpc = raw.functions.upload.SaveFilePart(
                                file_id=file_id, file_part=index, bytes=chunk
                            )
                        await queue.put((rpc, len(chunk)))
                    for _ in range(worker_count):
                        await queue.put(None)

                worker_count = 4 if is_big and not repair else 1
                tasks = [asyncio.create_task(worker()) for _ in range(worker_count)]
                tasks.append(asyncio.create_task(producer()))
                # Propagate original exceptions, including StopTransmission. Cancel
                # siblings on failure so a full queue cannot strand the producer.
                await asyncio.gather(*tasks)
                expected = min(part_size, file_size - file_part * part_size) if repair else file_size
                if confirmed != expected:
                    raise OSError("Upload did not confirm the expected byte count")
                if repair:
                    return None
                if is_big:
                    return raw.types.InputFileBig(id=file_id, parts=total, name=file_name)
                return raw.types.InputFile(
                    id=file_id, parts=total, name=file_name, md5_checksum=checksum.hexdigest()
                )
            finally:
                for task in tasks:
                    if not task.done():
                        task.cancel()
                if tasks:
                    await asyncio.gather(*tasks, return_exceptions=True)
                if owns_fp:
                    fp.close()
