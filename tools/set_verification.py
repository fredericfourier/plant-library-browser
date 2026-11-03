#!/usr/bin/env python3
"""Set the botanical verification status of plants in data/botanical-verification.json.

Usage: set_verification.py confirmed|pending_review <plant-id> [<plant-id> ...]
Approving ("confirmed") only takes effect for the image currently pinned in the record; the record keeps its imageSha256, and the approval is
appended to data/approval-ledger.json (tools/approval_ledger.py), where it stays for those exact WebP bytes.
Setting "pending_review" on a plant whose published bytes are owner-approved is refused: an approval is only ended by
`approval_ledger.py revoke <variant> <id> --reason ...` at the owner's request. Approval never transfers to changed bytes.
"""
import json, sys, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import approval_ledger

f = Path(__file__).resolve().parent.parent / "data/botanical-verification.json"
status, ids = sys.argv[1], sys.argv[2:]
assert status in ("confirmed", "pending_review") and ids
d = json.loads(f.read_text())
ledger = approval_ledger.load_ledger()
for i in ids:
    r = d["plants"][i]
    if status == "confirmed":
        if r.get("imageSha256") != approval_ledger.webp_sha(i, "botanical"):
            sys.exit(f"{i}: the record is pinned to different bytes than the published WebP; re-import or fix the record first (approval never transfers)")
        r["status"] = status
        r["approvedAt"] = r.get("approvedAt") or datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    else:
        if r.get("imageSha256") in approval_ledger.approved_hashes(ledger).get(("botanical", i), {}):
            sys.exit(f"{i}: the published bytes are owner-approved in the ledger; use approval_ledger.py revoke for an explicit revocation")
        r["status"] = status
        r.pop("approvedAt", None)
f.write_text(json.dumps(d, indent=2) + "\n")
if status == "confirmed":
    approval_ledger.sync(ledger, d)
    approval_ledger.LEDGER.write_text(approval_ledger.dump(ledger), encoding="utf-8")
print(status, ids)
