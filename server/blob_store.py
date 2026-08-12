"""Room zips at rest: Supabase Storage, service-role key auth.

Chosen over S3 because the service-role key (already in the server env for
identity) is guaranteed storage rights, while the AWS keys were provisioned
for SES and may be SES-scoped. Plain REST via httpx — no new dependency.

Sync on purpose: upload handlers call it through asyncio.to_thread so a
multi-hundred-MB push to storage never blocks the event loop the MCP
endpoint shares. Objects are keyed rooms/<sha256>.zip — content-addressed,
so a duplicate upload overwrites with identical bytes (x-upsert)."""

import os

import httpx


class BlobStoreError(RuntimeError):
    pass


class SupabaseBlobStore:
    def __init__(self, bucket: str = "datarooms") -> None:
        self.bucket = bucket
        self._base = (os.environ.get("SUPABASE_URL") or "").rstrip("/")
        self._key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or ""
        self._bucket_checked = False

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self._key}"}

    def configured(self) -> bool:
        return bool(self._base and self._key)

    def ensure_bucket(self) -> None:
        """Create the private bucket if missing; no-op when it exists."""
        if self._bucket_checked:
            return
        resp = httpx.post(
            f"{self._base}/storage/v1/bucket",
            headers=self._headers(),
            json={"id": self.bucket, "name": self.bucket, "public": False},
            timeout=30.0,
        )
        # 409 (or Supabase's 400 "already exists") both mean the bucket is there.
        if resp.status_code not in (200, 201) and "exist" not in resp.text.lower():
            raise BlobStoreError(f"bucket setup failed ({resp.status_code}): {resp.text[:300]}")
        self._bucket_checked = True

    def put_file(self, key: str, path: str, *, content_type: str = "application/zip") -> None:
        """Stream a local file into the bucket under `key` (upsert)."""
        if not self.configured():
            raise BlobStoreError("SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY not set")
        self.ensure_bucket()
        with open(path, "rb") as fh:
            resp = httpx.post(
                f"{self._base}/storage/v1/object/{self.bucket}/{key}",
                headers={**self._headers(), "Content-Type": content_type,
                         "x-upsert": "true"},
                content=fh,
                timeout=httpx.Timeout(30.0, write=600.0),
            )
        if resp.status_code not in (200, 201):
            raise BlobStoreError(f"blob put failed ({resp.status_code}): {resp.text[:300]}")
