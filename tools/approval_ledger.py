#!/usr/bin/env python3
"""Append-only owner-approval ledger: a visual approval belongs to the exact published WebP bytes, nothing else.

  approval_ledger.py sync                 append approvals found in data/botanical-verification.json (current and superseded versions) that the ledger lacks
  approval_ledger.py approve <botanical|watercolour> <plant-id> [...]   record a NEW owner approval for the WebP currently published (hash taken from the file)
  approval_ledger.py accept <variant> <id> --sha256 H --supersedes OLDH --basis T --at TS   record the owner's acceptance of replacement bytes (provenance kept)
  approval_ledger.py revoke <variant> <plant-id> --reason T            explicit, owner-requested revocation (the only way an approval ends)
  approval_ledger.py check [--base REF]   verify the ledger against the published files; with --base also against the ledger at REF (git rev)

Rules enforced by `check` (CI): every ledger entry is immutable (never edited, never removed, compared with --base); a ledger approval whose
imageSha256 equals the published WebP can never be dropped by a status rebuild, catalogue export, asset sync or importer run; changed WebP bytes
are NOT approved until a new entry is added. PNG master presence, provenance or checksums play no part in approval (see sourceIntegrity in the
status manifests). Stdlib only.
"""
import argparse, datetime, hashlib, json, subprocess, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LEDGER = ROOT / "data/approval-ledger.json"
VERIF = ROOT / "data/botanical-verification.json"
ASSETS = ROOT / "assets/plant-watercolours"
VARIANTS = {"botanical": "", "watercolour": "-watercolour"}
DESCRIPTION = ("Append-only record of owner visual approvals, each pinned to the exact WebP SHA-256 that was approved. Entries are never edited or "
               "removed; an approval ends only through an explicit entry in `revocations`. Approval is independent of PNG-master presence or provenance.")


def now():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def load_ledger(path=LEDGER):
    if not Path(path).is_file():
        return {"schemaVersion": 1, "description": DESCRIPTION, "entries": [], "revocations": []}
    return json.loads(Path(path).read_text(encoding="utf-8"))


def dump(d):
    return json.dumps(d, indent=2, ensure_ascii=False) + "\n"


def key(e):
    return (e["variant"], e["plantId"], e["imageSha256"])


def approved_hashes(ledger):
    """{(variant, plantId): {imageSha256 -> approvedAt}} for entries not explicitly revoked."""
    revoked = {key(r) for r in ledger.get("revocations", [])}
    out = {}
    for e in ledger["entries"]:
        if key(e) not in revoked:
            out.setdefault((e["variant"], e["plantId"]), {})[e["imageSha256"]] = e["approvedAt"]
    return out


def chain(rec):
    """Yield (record-dict) for a verification record and each superseded version under `previous`."""
    while isinstance(rec, dict):
        yield rec
        rec = rec.get("previous")


def from_verification(ver):
    found = []
    for pid, p in ver["plants"].items():
        for variant, rec in (("botanical", p if "status" in p else None), ("watercolour", p.get("watercolour"))):
            for r in chain(rec):
                if r.get("status") == "confirmed" and r.get("approvedAt") and r.get("imageSha256"):
                    # A record whose bytes were later replaced (e.g. a resolution correction) names the bytes the owner actually approved in
                    # approvedOriginalImageSha256: the approval stays pinned to those, never to the replacement bytes.
                    h = r.get("approvedOriginalImageSha256") or r["imageSha256"]
                    found.append({"plantId": pid, "variant": variant, "imageSha256": h, "approvedAt": r["approvedAt"],
                                  "source": "data/botanical-verification.json explicit approvedAt" + (" (superseded version)" if r is not rec else "")})
    return found


def sync(ledger, ver):
    have = {key(e) for e in ledger["entries"]}
    stamps = {(e["variant"], e["plantId"], e["approvedAt"]) for e in ledger["entries"]}
    # an approval timestamp already pinned to some bytes is never re-pinned to other bytes by editing a record (silent transfer)
    new = [e for e in from_verification(ver) if key(e) not in have and (e["variant"], e["plantId"], e["approvedAt"]) not in stamps]
    ledger["entries"] += sorted(new, key=lambda e: (e["variant"], e["plantId"], e["approvedAt"]))
    return new


def webp_sha(pid, variant):
    f = ASSETS / f"{pid}{VARIANTS[variant]}.webp"
    return hashlib.sha256(f.read_bytes()).hexdigest() if f.is_file() else None


def check(base=None):
    errs, ledger = [], load_ledger()
    seen = set()
    for e in ledger["entries"]:
        if key(e) in seen:
            errs.append(f"duplicate ledger entry {key(e)}")
        seen.add(key(e))
        if e["variant"] not in VARIANTS or not e.get("approvedAt") or len(e["imageSha256"]) != 64:
            errs.append(f"malformed ledger entry {e}")
    for r in ledger.get("revocations", []):
        if not (r.get("reason") and r.get("revokedAt")) or key(r) not in seen:
            errs.append(f"revocation without reason/time or without a matching entry: {r}")
    if base:
        old = subprocess.run(["git", "-C", str(ROOT), "show", f"{base}:data/approval-ledger.json"], capture_output=True, text=True)
        if old.returncode == 0:
            o = json.loads(old.stdout)
            cur = {key(e): e for e in ledger["entries"]}
            for e in o["entries"]:
                if cur.get(key(e)) != e:
                    errs.append(f"ledger entry removed or altered vs {base}: {key(e)}")
            oldrev = [json.dumps(r, sort_keys=True) for r in o.get("revocations", [])]
            currev = [json.dumps(r, sort_keys=True) for r in ledger.get("revocations", [])]
            if currev[:len(oldrev)] != oldrev:
                errs.append(f"revocation history altered vs {base}")
    ver = json.loads(VERIF.read_text(encoding="utf-8"))
    ok, revoked = approved_hashes(ledger), {key(r) for r in ledger.get("revocations", [])}
    for (variant, pid), hs in ok.items():
        cur = webp_sha(pid, variant)
        if cur and cur in hs:
            rec = ver["plants"].get(pid, {})
            rec = rec if variant == "botanical" else rec.get("watercolour")
            if not rec or rec.get("imageSha256") != cur or rec.get("status") != "confirmed" or not rec.get("approvedAt"):
                errs.append(f"{pid} ({variant}): published WebP is owner-approved in the ledger but data/botanical-verification.json no longer "
                            "shows it confirmed with approvedAt for the same hash - a tool revoked an approval; restore the record")
            elif rec["approvedAt"] != hs[cur] and not rec.get("approvedOriginalImageSha256"):
                errs.append(f"{pid} ({variant}): approvedAt in verification record differs from the ledger")
    # every explicit approval in the verification file must be in the ledger (new approvals go through `approve`)
    for pid, p in ver["plants"].items():
        for variant, rec in (("botanical", p if "status" in p else None), ("watercolour", p.get("watercolour"))):
            if rec and rec.get("status") == "confirmed" and rec.get("approvedAt") and rec.get("imageSha256") and not rec.get("approvedOriginalImageSha256"):
                if (variant, pid, rec["imageSha256"]) not in seen:
                    errs.append(f"{pid} ({variant}): verification record is confirmed for bytes {rec['imageSha256'][:12]} that the ledger has not approved "
                                "(approval never transfers to changed bytes): approve them explicitly with approval_ledger.py approve")
    return errs


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("sync")
    a_ = sub.add_parser("approve"); a_.add_argument("variant", choices=sorted(VARIANTS)); a_.add_argument("ids", nargs="+")
    r_ = sub.add_parser("revoke"); r_.add_argument("variant", choices=sorted(VARIANTS)); r_.add_argument("ids", nargs="+"); r_.add_argument("--reason", required=True)
    x_ = sub.add_parser("accept", help="record the owner's existing acceptance of replacement bytes of an already approved image, with truthful provenance")
    x_.add_argument("variant", choices=sorted(VARIANTS)); x_.add_argument("plant_id"); x_.add_argument("--sha256", required=True)
    x_.add_argument("--supersedes", required=True, help="the previously approved WebP hash this replaces"); x_.add_argument("--basis", required=True)
    x_.add_argument("--at", required=True, help="UTC time the owner's acceptance was recorded (YYYY-MM-DDTHH:MM:SSZ)")
    c_ = sub.add_parser("check"); c_.add_argument("--base")
    a = ap.parse_args()
    ledger = load_ledger()
    ledger["description"] = DESCRIPTION
    if a.cmd == "sync":
        new = sync(ledger, json.loads(VERIF.read_text(encoding="utf-8")))
        LEDGER.write_text(dump(ledger), encoding="utf-8")
        print(f"ledger: {len(ledger['entries'])} entries ({len(new)} appended)")
    elif a.cmd == "approve":
        for pid in a.ids:
            h = webp_sha(pid, a.variant)
            if not h:
                sys.exit(f"{pid}: no published {a.variant} WebP to approve")
            if h in approved_hashes(ledger).get((a.variant, pid), {}):
                print(pid, "already approved for these bytes"); continue
            ledger["entries"].append({"plantId": pid, "variant": a.variant, "imageSha256": h, "approvedAt": now(), "source": "approval_ledger.py approve (owner request)"})
            print(pid, a.variant, "approved for", h[:12])
        LEDGER.write_text(dump(ledger), encoding="utf-8")
    elif a.cmd == "accept":
        hs = approved_hashes(ledger).get((a.variant, a.plant_id), {})
        if a.supersedes not in hs:
            sys.exit(f"{a.plant_id}: {a.supersedes[:12]} is not an approved version in the ledger")
        if a.sha256 in hs:
            print(a.plant_id, "already approved for these bytes"); return
        ledger["entries"].append({"plantId": a.plant_id, "variant": a.variant, "imageSha256": a.sha256, "approvedAt": a.at,
                                  "source": "owner acceptance of replacement bytes, recorded (no new visual review)", "supersedesImageSha256": a.supersedes,
                                  "supersededApprovedAt": hs[a.supersedes], "basis": a.basis})
        LEDGER.write_text(dump(ledger), encoding="utf-8")
        print(a.plant_id, a.variant, "accepted", a.sha256[:12])
    elif a.cmd == "revoke":
        for pid in a.ids:
            h = webp_sha(pid, a.variant)
            ledger.setdefault("revocations", []).append({"plantId": pid, "variant": a.variant, "imageSha256": h, "revokedAt": now(), "reason": a.reason})
        LEDGER.write_text(dump(ledger), encoding="utf-8")
    else:
        errs = check(a.base)
        print("\n".join(errs) if errs else "OK: approval ledger consistent", file=sys.stderr if errs else sys.stdout)
        sys.exit(1 if errs else 0)


if __name__ == "__main__":
    main()
