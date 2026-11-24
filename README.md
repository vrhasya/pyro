# C1PH3R Pyro NextGen

Experimental development branch, not a production dependency.

## Pinned upstream
- Kurigram: https://github.com/kurigram-org/kurigram
- Commit: `ed92ab8a8ef8958d9ff909c772ff99c2ade1fdba` (2026-11-23 UTC)
- Source version: 2.2.27
- Telegram schema: layer 234

The upstream source is pinned as a Git submodule in `upstream/kurigram`. The branch builds an experimental modified Kurigram distribution using a reviewed upload overlay. The pinned upstream checkout remains unmodified. The upstream license applies to its source.

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
python -m unittest discover -s tests -p 'test_upload_reliability.py' -v
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

The submodule is read-only. The build tool verifies the upstream commit and original upload file blob before copying the source into a disposable build tree. The overlay is not a runtime monkey patch. Use a fresh build tree for each build; never install in a production environment.

## Phase 2: Upload Reliability V2 (experimental)

- Preserves Kurigram's cached media session, semaphore, file size limits and 512 KiB parts.
- Requires a positive acknowledgement before counting each part. Progress reports exact acknowledged bytes, including out-of-order completion and the final short part.
- Retries the same part at most four times for Telegram FloodWait and FloodPremiumWait, honoring the server delay plus one second. Waits greater than 60 seconds or exhausted attempts are propagated; callers must respect the error. Cooldown is shared only by workers for a single file, not across clients or simultaneous files. Requests already in flight cannot be withdrawn.
- Failure or cancellation cancels and joins sibling tasks; a failed upload does not return an InputFile. Cached sessions remain owned by Kurigram. Caller-provided file objects remain open.
- Includes offline tests with simulated sessions; live performance and compatibility are not certified. CI is scoped to nextgen and uses no Telegram credentials.
