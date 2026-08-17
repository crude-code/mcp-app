"""Signed export links: recognised rather than remembered.

`upload_tokens.UploadTokenStore` keeps a dict of live grants in the server
process, which is exactly right for a sandbox that redeems its URL four
seconds after minting. It is exactly wrong for a link embedded in a deal
sheet: the artifact is durable, the dict is not, and a restart turns every
embedded button into a dead one.

So a run-scoped export carries its own grant. The facts travel *inside* the
token — kind, run id, user, expiry — under an HMAC the server recomputes on
arrival. Nothing is stored, so nothing is lost on restart, and the link stays
good for as long as the run record behind it does.

Not every kind can work this way, and the split is principled rather than
partial. A `query` export's grant is an arbitrary SELECT: too large for a URL
and not something to publish in one. Those keep the in-memory ticket and its
24-hour life, because the thing being granted genuinely cannot live in the
grant. Run-scoped kinds carry four small fields and sign cleanly.

Revocation is by secret rotation — there is no per-token kill switch, which is
the cost of not keeping a list. Rotating `CC_EXPORT_SECRET` invalidates every
outstanding signed link at once.
"""
import base64
import hashlib
import hmac
import json
import os
import time

# Kinds whose whole grant fits in a URL. `query` is deliberately absent.
SIGNABLE_KINDS = ("bundle", "volumes", "parameters")

# Long enough that a deal sheet stays useful for the life of the deal it
# describes, finite so an abandoned artifact does not leave a live endpoint
# behind forever. A stale link fails with a page that says to re-export.
DEFAULT_TTL_SECONDS = 365 * 24 * 3600


class ExportTokenError(RuntimeError):
    """Malformed, tampered-with, or expired signed token."""


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def secret() -> bytes | None:
    """The signing key, or None when the deployment has not configured one.

    Absent a secret the lane still works — `export_data` falls back to the
    in-memory ticket for every kind — but nothing durable can be minted, so
    the deal sheet simply does not offer a download row. Failing visibly at
    setup beats shipping buttons that quietly expire.
    """
    raw = (os.environ.get("CC_EXPORT_SECRET") or "").strip()
    return raw.encode() if raw else None


def _sign(payload: bytes, key: bytes) -> str:
    return _b64(hmac.new(key, payload, hashlib.sha256).digest())


def mint(*, kind: str, run_id: str, user_id: int, user_slug: str,
         ttl_seconds: int = DEFAULT_TTL_SECONDS, key: bytes | None = None) -> str:
    """Facts + expiry + signature → an opaque, self-describing token."""
    key = key or secret()
    if key is None:
        raise ExportTokenError("no CC_EXPORT_SECRET configured")
    if kind not in SIGNABLE_KINDS:
        raise ExportTokenError(
            f"kind {kind!r} is not signable; expected one of {list(SIGNABLE_KINDS)}")

    payload = json.dumps(
        {"k": kind, "r": run_id, "u": user_id, "s": user_slug,
         "e": int(time.time()) + int(ttl_seconds)},
        separators=(",", ":"), sort_keys=True,
    ).encode()
    return f"{_b64(payload)}.{_sign(payload, key)}"


def looks_signed(token: str) -> bool:
    """Cheap discriminator for the route: signed tokens carry a separator,
    `secrets.token_urlsafe` output never does."""
    return "." in token


def verify(token: str, *, key: bytes | None = None) -> dict:
    """Token → its grant, or raise. Signature is checked before expiry so a
    forged token can't learn anything from the difference."""
    key = key or secret()
    if key is None:
        raise ExportTokenError("no CC_EXPORT_SECRET configured")

    head, _, sig = token.partition(".")
    if not head or not sig:
        raise ExportTokenError("not a signed export token")
    try:
        payload = _unb64(head)
    except Exception as exc:  # noqa: BLE001
        raise ExportTokenError("malformed export token") from exc

    if not hmac.compare_digest(_sign(payload, key), sig):
        raise ExportTokenError("export token signature does not verify")

    try:
        claims = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise ExportTokenError("malformed export token payload") from exc

    if int(claims.get("e", 0)) < time.time():
        raise ExportTokenError("this export link has expired")
    if claims.get("k") not in SIGNABLE_KINDS:
        raise ExportTokenError(f"unsignable kind {claims.get('k')!r} in token")

    return {"kind": claims["k"], "run_id": claims.get("r") or "",
            "user_id": claims.get("u"), "user_slug": claims.get("s") or "",
            "expires_at": int(claims["e"])}
