# Security Policy

## Reporting a vulnerability

Do not post exploit details, credentials, private data, or proof-of-concept attacks in a public issue. Use the repository host's private vulnerability-reporting channel when available and include the affected component, impact, reproduction conditions, and the smallest safe proof needed to verify the issue.

## Security boundaries

The MCP server treats model input as untrusted. Security-sensitive controls include:

- authenticated user identity at externally reachable tools
- owner checks for per-user valuation and extraction records
- a SELECT-only SQL guard plus database permissions
- one-time, short-lived capability URLs for bulk upload/download paths
- private blob storage for dataroom material
- response-size, row-count, and statement-timeout limits

Application guardrails are defense in depth. Production database roles should still expose only the schemas and privileges required by the server.

## Secrets

Never commit `.env`, service-role keys, database passwords, AWS credentials, customer data, or deployment runtime state. `.env.example` must contain placeholders only.
