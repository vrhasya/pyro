# C1PH3R Pyro NextGen

Experimental development branch, not a production dependency.

## Pinned upstream
- Kurigram: https://github.com/kurigram-org/kurigram
- Commit: `ed92ab8a8ef8958d9ff909c772ff99c2ade1fdba` (2026-11-23 UTC)
- Source version: 2.2.27
- Telegram schema: layer 234

The upstream source is pinned as a Git submodule in `upstream/kurigram`. This branch is a foundation only, not yet a modified Kurigram distribution. The upstream license applies to its source.

## Local isolated setup (developer machine, not production VPS)

```sh
git clone --branch nextgen --single-branch --recurse-submodules https://github.com/vrhasya/pyro.git pyro-nextgen
cd pyro-nextgen
python3 -m venv .venv-nextgen
. .venv-nextgen/bin/activate
python -m pip install --upgrade pip
python -m pip install './upstream/kurigram[fast]'
python tools/verify_baseline.py
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

The submodule is read-only as a baseline. Before integrating modifications, import the upstream source into this branch or build a separately reviewed patch series; do not commit changes to the upstream repository.
