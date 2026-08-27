#!/usr/bin/env python3
"""Push the dataroom zip to its one-time upload URL (from dataroom_open).

    python3 room_push.py <room.zip> "<upload_url>"

Streams the file (no memory blowup on big rooms), then prints a one-line
verdict — the server re-hashes on receipt, so {"saved": true} means the
platform holds byte-identical content. A connection error means the sandbox
can't reach the upload host: relay the printed hint to the user. Stdlib only.
"""
import json
import os
import sys
import urllib.error
import urllib.request


def main():
    if len(sys.argv) != 3:
        sys.exit("usage: room_push.py <room.zip> <upload_url>")
    path, url = sys.argv[1], sys.argv[2]
    size = os.path.getsize(path)
    with open(path, "rb") as fh:
        req = urllib.request.Request(
            url, data=fh, method="POST",
            headers={"Content-Type": "application/zip",
                     "Content-Length": str(size)},
        )
        try:
            with urllib.request.urlopen(req, timeout=600) as resp:
                result = json.loads(resp.read().decode())
        except urllib.error.HTTPError as e:
            detail = e.read().decode(errors="replace")[:2000]
            try:
                detail = json.loads(detail).get("error", detail)
            except ValueError:
                pass
            print(json.dumps({"saved": False, "status": e.code, "error": detail}))
            sys.exit(1)
        except (urllib.error.URLError, OSError) as e:
            print(json.dumps({
                "saved": False,
                "error": f"could not reach the upload host: {e}",
                "hint": ("The sandbox's network allowlist is likely missing the "
                         "upload host. Tell the user to add it under Claude's "
                         "network egress settings, then retry in a new chat."),
            }))
            sys.exit(1)
    ok = bool(result.get("saved")) and result.get("bytes_received") == size
    print(json.dumps({"saved": ok, "room_id": result.get("room_id"),
                      "bytes_received": result.get("bytes_received"),
                      "size_local": size}))
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
