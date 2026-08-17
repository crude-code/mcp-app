# Public Release Checklist

Run this against the **release snapshot**, not the private working/deployment tree.

## Hard blockers

- [ ] No `.env`, credentials, secrets, API keys, private keys, DB URLs with real credentials, or runtime logs.
- [ ] No licensed/vendor raw data, customer files, dataroom contents, private extractions, or database dumps.
- [ ] No private ingestion/data-pipeline code.
- [ ] No `deploy.sh`, `deploy-dev.sh`, `deploy/`, or deployment-only GitHub workflows.
- [ ] No machine/user-specific absolute paths, instance IDs, SSH configuration, or provisioning commands.
- [ ] `.env.example` contains placeholders only.

## Code and contract checks

- [ ] `python -m pytest -q` passes with credential-dependent tests skipped when credentials are absent.
- [ ] `cd renderer && npm ci && npm run build && npm run lint` passes.
- [ ] Server and renderer versions agree (`tests/test_version_drift.py`).
- [ ] Prompt/schema/tool contracts agree (`tests/test_schema_drift.py`).
- [ ] Frozen viewer/payload contracts agree.
- [ ] SQL guard regression tests pass, including blocked-schema and dynamic-SQL cases.
- [ ] Every externally reachable per-user read/write path enforces ownership.

## Documentation checks

- [ ] README describes only functionality actually present in the public snapshot.
- [ ] `CLAUDE.md` contains no operational secrets or claims about files removed from the public snapshot.
- [ ] `REPO_BOUNDARY.md`, `SECURITY.md`, and `CONTRIBUTING.md` are included.
- [ ] Search for old branding, vendor/licensed-data claims, internal usernames, real email addresses, and customer names.

## Final review

- [ ] Review the exact release archive/file list before publishing.
- [ ] Run a secret scanner on the release snapshot and its Git history.
- [ ] Confirm the release can be understood without access to the private sibling data-pipeline repository.
