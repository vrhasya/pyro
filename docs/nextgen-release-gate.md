# NextGen release and staging gate

Status: experimental alpha; no production deployment authorized.

## Scope and isolation

- Keep the existing default branch 213 and all installed Navy/Styled packages unchanged.
- Never run the NextGen wheel in an existing bot environment. The new distribution
  name does not make its overlapping Python namespaces safe to co-install.
- Use a separate disposable host or container for staging, a new unprivileged OS user,
  private directory (0700), separate Python venv and private new session files (0600).
- Do not mount /root, production database directories, existing Telegram sessions,
  token files, PostgreSQL sockets, SSH keys or Docker sockets. Use dummy application
  DB fixtures only; do not copy production DBs or session strings.
- Dedicated non-production Telegram bot/account and private test chats are required for
  any live testing. Do not start live tests without explicit approval.
- No changes to service files, systemd, database schemas, application repos, or production
  credentials are part of this branch.

## Acceptance gates

1. Verify pinned upstream revision and overlay source hashes; build the alpha wheel.
2. Require successful offline CI on Python 3.12 and 3.13. Inspect test logs and
   dependency audit JSON. Resolve failed tests and vulnerabilities before progressing.
3. Record wheel SHA-256, all dependency versions and hashes from an approved wheelhouse.
   Use a separately authenticated manifest; the generated CI checksum alone does not
   authenticate a release. Keep upstream notices and license files.
4. Run tools/stage_offline.sh with the approved wheel, wheelhouse and wheel checksum.
   This creates an isolated temporary venv with no Telegram credentials and removes it
   on completion. It is an offline acceptance test, not actual live staging.
5. Review synthetic benchmark outputs. Record throughput, CPU time, process peak RSS
   and exact content integrity. Synthetic latency does not predict real network speed.
6. Only after user authorization, test in a dedicated non-production environment:
   - Start/stop and authorization using a new session only; verify DC without changing it.
   - Upload photo/video/document and media album to an authorized private test chat.
   - Download 8, 32 and 64 MiB test fixtures with standard and optional parallel modes;
     compare content digest, CPU, RSS, disk use and wall time.
   - Check cancellation, errors, UI callbacks, premium emoji, rich heading/table/divider
     and send/edit. Verify no duplicate sends and no incomplete final media.
   - Record all failures; stop on rate limits and respect the server-directed wait.
7. For each candidate application, inventory actual imports, method signatures and
   dependency constraints; run its own tests in isolated environment with dummy DB.
   Pyromod and unsupported private paths are blockers until addressed.
8. Production promotion requires a new explicit approval per service, approved version
   and dependency hashes, a maintenance window, backups and a tested rollback plan.
   Keep old virtual environment and code intact; never reuse a migrated session with
   older library without separate compatibility validation.

## Current audit findings

The inspected upstream start method has no legacy secret-handler registration.
NextGen overlays are checked for direct shell/eval calls and legacy secret imports.
Raw packet debug logging and two full update logs are reduced to class names in the
alpha build. These are targeted mitigations, not a full source/supply-chain audit.
Upstream session storage contains authorization keys and may migrate its SQLite schema
to version 7. Session files are secrets; never open production sessions with NextGen
during testing. Other upstream errors, application logs, third-party plugins and
dependency credentials can still leak information; a separate review is necessary.

Dependency audit reports only resolved third-party runtime packages, not the private
NextGen code. Results depend on public advisory coverage. Dependency floors are not
a complete reproducible lock; review and approve a wheelhouse before live use.

No release tag, PyPI publication, deployment workflow or systemd unit is created.
