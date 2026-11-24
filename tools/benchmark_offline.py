"""Deterministic offline transfer benchmark; simulated latency, no Telegram access."""
import argparse
import asyncio
import hashlib
import io
import json
from pathlib import Path
import resource
import tempfile
import time
from types import SimpleNamespace

import pyrogram
from pyrogram.methods.advanced.save_file import SaveFile

MIB = 1024 * 1024


class FakeUploadSession:
    def __init__(self, delay):
        self.delay = delay
        self.parts = {}
        self.active = self.peak = 0

    async def invoke(self, rpc, **kwargs):
        self.active += 1
        self.peak = max(self.peak, self.active)
        try:
            await asyncio.sleep(self.delay)
            if rpc.file_part in self.parts:
                raise AssertionError("Unexpected duplicate upload part")
            self.parts[rpc.file_part] = hashlib.sha256(rpc.bytes).digest()
            return True
        finally:
            self.active -= 1


class FakeClient(SaveFile):
    max_concurrent_transmissions = 4
    executor = None

    def __init__(self, source, delay):
        self.source = source
        self.delay = delay
        self.save_file_semaphore = asyncio.Semaphore(1)
        self.get_file_semaphore = asyncio.Semaphore(4)
        self.storage = SimpleNamespace(dc_id=self.dc_id)
        self.me = SimpleNamespace(is_premium=False)
        self.session = FakeUploadSession(delay)
        self.active = self.peak = 0

    async def dc_id(self):
        return 5

    async def get_session(self, dc_id, *, is_media):
        assert dc_id == 5 and is_media
        return self.session

    def rnd_id(self):
        return 123

    async def get_file(self, file_id, file_size=0, limit=0, offset=0,
                       progress=None, progress_args=()):
        async with self.get_file_semaphore:
            self.active += 1
            self.peak = max(self.peak, self.active)
            try:
                with self.source.open("rb") as f:
                    f.seek(offset * MIB)
                    current = offset * MIB
                    for _ in range(limit or (file_size + MIB - 1) // MIB + 1):
                        chunk = f.read(MIB)
                        if not chunk:
                            break
                        await asyncio.sleep(self.delay)
                        yield chunk
                        current += len(chunk)
                        if progress:
                            await progress(current, file_size, *progress_args)
            finally:
                self.active -= 1

    async def handle_download(self, packet):
        return await pyrogram.Client.handle_download(self, packet)


def digest(path):
    with path.open("rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()


async def benchmark(mode, mib, delay):
    with tempfile.TemporaryDirectory(prefix="nextgen-benchmark-") as tmp:
        root = Path(tmp)
        source = root / "input.bin"
        with source.open("wb") as f:
            for i in range(mib):
                f.write(bytes([i % 251]) * MIB)
            f.write(b"last-short-part")
        size = source.stat().st_size
        client = FakeClient(source, delay)
        samples = []

        async def measure(label, operation, peak, validate):
            start_cpu, start_wall = time.process_time(), time.perf_counter()
            result = await operation()
            elapsed = time.perf_counter() - start_wall
            cpu = time.process_time() - start_cpu
            validate(result)
            samples.append(dict(operation=label, bytes=size, wall_seconds=round(elapsed, 6),
                                cpu_seconds=round(cpu, 6), mib_per_second=round(size / MIB / elapsed, 3),
                                observed_peak_workers=peak(),
                                process_peak_rss_kib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
                                integrity="PASS"))

        def verify_upload(result):
            expected = {}
            with source.open("rb") as f:
                index = 0
                while chunk := f.read(512 * 1024):
                    expected[index] = hashlib.sha256(chunk).digest()
                    index += 1
            assert result.parts == len(expected)
            assert client.session.parts == expected

        await measure("upload", lambda: client.save_file(source),
                      lambda: client.session.peak, verify_upload)

        async def download(workers):
            client.peak = 0
            name = f"download-{workers}.bin"
            packet = (None, root, name, False, size, None, ())
            if workers == 1:
                return await client.handle_download(packet)
            from pyrogram.methods.messages._nextgen_parallel_download import download_parallel
            return await download_parallel(client, packet, workers)

        def verify_download(result):
            assert result is not None
            assert digest(Path(result)) == digest(source)

        for workers in ([1, 2, 4] if mode == "nextgen" else [1]):
            await measure(f"download-{workers}", lambda: download(workers),
                          lambda: client.peak, verify_download)

        return dict(mode=mode, version=pyrogram.__version__,
                    simulated_latency_ms=delay * 1000, measurements=samples)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["baseline", "nextgen"], required=True)
    parser.add_argument("--mib", type=int, choices=[16, 32, 64], default=32)
    parser.add_argument("--delay-ms", type=int, choices=[1, 5, 10], default=5)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.mode == "nextgen":
        assert "+nextgen" in pyrogram.__version__
    else:
        assert pyrogram.__version__ == "2.2.27"
    result = asyncio.run(benchmark(args.mode, args.mib, args.delay_ms / 1000))
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
