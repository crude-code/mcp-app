# Contributing

Crude Code keeps the reasoning layer in the host model and the server deterministic. Prefer changes that make that boundary easier to verify rather than adding parallel implementations.

## Before changing code

1. Identify the existing canonical path for the behavior.
2. Tie the change to a concrete bug, requirement, measurement, or contract.
3. Avoid adding a second implementation when the existing one can be corrected.
4. For a bug fix, add a regression test that fails on the old behavior.

## Validation

Run:

```bash
python -m pytest -q
cd renderer
npm ci
npm run build
npm run lint
```

Tests requiring external credentials or network access are skipped unless explicitly enabled.

## Pull requests

Keep changes narrow. Explain what behavior changed, why the prior behavior was wrong, and which tests prove the correction. Deleting obsolete code is preferred to preserving unused compatibility paths without evidence that they are still needed.

For public contributions, follow `REPO_BOUNDARY.md`; do not include deployment infrastructure, secrets, licensed data, or customer/deal-room material.
