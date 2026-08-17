# Repository Boundary

Crude Code is designed so the model-facing domain layer can be published without publishing private data or deployment infrastructure.

## Public application boundary

The public application snapshot may contain:

- `server/` — MCP tools, valuation math, map hydration, and local persistence contracts
- `renderer/` — client renderer source
- `prompts/` — model-facing tool/system instructions and public schema descriptions
- `skills/` — public workflow bundles
- `utils/` — generic runtime helpers and SQL guardrails
- `tests/` — tests that run without private data or credentials
- `README.md`, `LICENSE`, `SECURITY.md`, `CONTRIBUTING.md`
- `.env.example` with placeholders only
- `.github/workflows/ci.yml`

## Never publish from the working/deployment tree

A public release must not contain:

- `.env`, credentials, tokens, private keys, database dumps, logs, or runtime state
- raw or derived licensed/vendor datasets
- customer or deal-room files, extracted private deal data, or real PII
- private data-pipeline/ingestion connector code
- host-specific deployment or provisioning material, including `deploy.sh`, `deploy-dev.sh`, `deploy/`, and deployment workflows
- machine-specific paths, SSH/SSM provisioning details, instance identifiers, or private infrastructure topology

## Important: this working tree is not a public-release artifact

The full working checkout currently carries operational deployment files because they are used to run Crude Code. Do **not** publish the tree verbatim. Produce a separate public snapshot and run `PUBLIC_RELEASE_CHECKLIST.md` against that snapshot.

The boundary is about data and operational exposure, not hiding the deterministic analytics logic. Public code should remain runnable against a user-supplied database whose schema matches the documented public contracts.
