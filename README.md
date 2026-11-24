# C1PH3R Pyro NextGen

Experimental development branch, not a production dependency.

## Pinned upstream
- Kurigram: https://github.com/kurigram-org/kurigram
- Commit: `ed92ab8a8ef8958d9ff909c772ff99c2ade1fdba` (2026-11-23 UTC)
- Source version: 2.2.27
- Telegram schema: layer 234

The upstream source is pinned as a Git submodule in `upstream/kurigram`. The branch builds an experimental modified Kurigram distribution using upload and download overlays. The pinned upstream checkout remains unmodified. The upstream license applies to its source.

## Local isolated setup (developer machine, not production VPS)

```sh
git clone --branch nextgen --single-branch --recurse-submodules https://github.com/vrhasya/pyro.git pyro-nextgen
cd pyro-nextgen
python3 -m venv .venv-nextgen
. .venv-nextgen/bin/activate
python -m pip install --upgrade pip
python tools/prepare_nextgen.py
python -m pip install './.nextgen-build/kurigram[fast]'
python tools/verify_baseline.py
python -m unittest discover -s tests -p 'test_*.py' -v
```

The verifier checks the source pin, schema layer, namespace, version and the inspected startup path. It is an offline static check, not a live Telegram or security certification.

## Development phases

1. Baseline: pin upstream and verify isolated installation.
2. Port and test upload acknowledgement, bounded retry, shared per-upload cooldown, and progress semantics against Kurigram's current media session API.
3. Port opt-in parallel download with bounded concurrency and safe fallback.
4. Design Styled compatibility and regression tests for Native Rich classes, callbacks and keyboard semantics.
5. Offline tests and benchmarks; isolated staging with dedicated non-production credentials only after approval.
6. Separate deployment approval and pinned artifacts for each production project.

No deployment workflow, no changes to existing branches, no production services, credentials, databases, or sessions. Legacy security remediation must be reviewed separately; this branch does not alter installed legacy packages.

The submodule is read-only. The build tool verifies the upstream commit and original modified source file blobs before copying the source into a disposable build tree. The overlay is not a runtime monkey patch. Use a fresh build tree for each build; never install in a production environment.

## Phase 2: Upload Reliability V2 (experimental)

- Preserves Kurigram's cached media session, semaphore, file size limits and 512 KiB parts.
- Requires a positive acknowledgement before counting each part. Progress reports exact acknowledged bytes, including out-of-order completion and the final short part.
- Retries the same part at most four times for Telegram FloodWait and FloodPremiumWait, honoring the server delay plus one second. Waits greater than 60 seconds or exhausted attempts are propagated; callers must respect the error. Cooldown is shared only by workers for a single file, not across clients or simultaneous files. Requests already in flight cannot be withdrawn.
- Failure or cancellation cancels and joins sibling tasks; a failed upload does not return an InputFile. Cached sessions remain owned by Kurigram. Caller-provided file objects remain open.
- Includes offline tests with simulated sessions; live performance and compatibility are not certified. CI is scoped to nextgen and uses no Telegram credentials.

## Phase 3: Smart Parallel Download V2 (experimental)

The standard downloader remains unchanged unless explicitly selected:

```python
# A dedicated test client must be configured with max_concurrent_transmissions=4.
path = await client.download_media(message, parallel=True, parallel_workers=4)
```

- For known-size disk downloads >= 8 MiB on systems with positional writes, use 2–4 workers capped by the client's existing transmission limit. Unknown-size, in-memory, small files, and clients configured with one transmission use the original downloader.
- Fetch 1 MiB chunks in ranges of up to four chunks via Kurigram's existing get_file method. Warm up the existing media session first; preserve upstream DC routing and CDN verification.
- Write directly into a unique temporary file, without buffering the entire file in RAM. Require correct range lengths and exact overall size; atomically replace the final path only after completion. No additional end-to-end remote digest is available for normal MTProto files.
- Progress is cumulative completed bytes, monotonic even if a range fails and the standard transfer restarts. During fallback, progress may pause until the restarted transfer catches up. Callback cancellation is respected.
- Only incomplete ranges can trigger a single automatic standard fallback, using an isolated temporary directory and exact output-size verification. Flood waits, CDN integrity failures, disk errors, cancellation and other failures are not retried by this overlay. In-flight requests cannot be withdrawn from Telegram.
- Parallel jobs on one client are serialized; other normal transfers still share Kurigram's existing semaphore. The existing standard downloader is unchanged. Concurrent callers should use distinct final paths.
- Local positional disk writes and fsync are synchronous to avoid background writes after cancellation. The implementation is bounded by the client's transmission limit; actual throughput, CPU and memory must be benchmarked separately.
- Tests use fake sessions and local temporary files. No credentials, Telegram requests, VPS or database access. The package has not yet been approved for live use.
