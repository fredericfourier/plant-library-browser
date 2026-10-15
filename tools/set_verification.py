#!/usr/bin/env python3
"""Set the botanical verification status of plants in data/botanical-verification.json.

Usage: set_verification.py confirmed|pending_review <plant-id> [<plant-id> ...]
Approving ("confirmed") only takes effect for the image currently pinned in the record; the record keeps its imageSha256.
"""
import json, sys, datetime
from pathlib import Path

f = Path(__file__).resolve().parent.parent / "data/botanical-verification.json"
status, ids = sys.argv[1], sys.argv[2:]
assert status in ("confirmed", "pending_review") and ids
d = json.loads(f.read_text())
for i in ids:
    r = d["plants"][i]
    r["status"] = status
    if status == "confirmed":
        r["approvedAt"] = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    else:
        r.pop("approvedAt", None)
f.write_text(json.dumps(d, indent=2) + "\n")
print(status, ids)
