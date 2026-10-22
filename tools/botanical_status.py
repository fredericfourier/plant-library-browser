#!/usr/bin/env python3
"""Deterministic botanical illustration status manifest and generation queue.

  botanical_status.py build [--bd <border-designer checkout> --bd-ref <ref>]   regenerate data/botanical-status.json
  botanical_status.py check                                                      validate manifest against the repo (exit 1 on any problem)
  botanical_status.py queue [N] [--skip K] [--json]                              first N plants with status=missing, catalogue order
  botanical_status.py summary                                                    status counts
  botanical_status.py set rejected|uncertain_match <plant-id> [...] [--note T]   pin a manual status (kept by later builds)

The manifest is derived from repository state, never from memory: the catalogue (data/plants.json) fixes the plant list and order,
the published WebPs plus data/botanical-verification.json and assets/plant-watercolours/manifest.json fix what exists and what is
approved, and the private PNG masters are read from a border-designer ref when --bd is given (otherwise the recorded values are kept).
Botanical files are <id>.webp / <id>.png; watercolour files are <id>-watercolour.* and are tracked separately, never as botanical.
Only `rejected` and `uncertain_match` are manual; everything else is recomputed. Stdlib only.
"""
import argparse, datetime, hashlib, json, subprocess, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MANIFEST = ROOT / "data/botanical-status.json"
ASSETS = ROOT / "assets/plant-watercolours"
STATUSES = ("missing", "pending_review", "approved", "rejected", "uncertain_match")
MANUAL = ("rejected", "uncertain_match")
MASTER_DIR = "assets/plant-watercolours/masters"
BRIEF = "docs/briefs/BOTANICAL_ASSET_BRIEF.md"


def load(p):
    return json.loads(Path(p).read_text(encoding="utf-8"))


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def git(repo, *a):
    return subprocess.check_output(["git", "-C", str(repo), *a])


def read_masters(bd, ref):
    """{plant-id: (path, sha256)} for botanical PNG masters (not *-watercolour.png) at <ref> in the border-designer checkout."""
    out = {}
    for line in git(bd, "ls-tree", "-r", "--name-only", ref, "--", MASTER_DIR).decode().splitlines():
        name = line.rsplit("/", 1)[-1]
        if name.endswith(".png") and not name.endswith("-watercolour.png"):
            out[name[:-4]] = (line, hashlib.sha256(git(bd, "show", f"{ref}:{line}")).hexdigest())
    return out, git(bd, "rev-parse", ref).decode().strip()


def build(prev, bd=None, bd_ref=None):
    cat = load(ROOT / "data/plants.json")["plants"]
    ver = load(ROOT / "data/botanical-verification.json")["plants"]
    amf = load(ASSETS / "manifest.json")["assets"]
    added = {pid: b["date"] for b in load(ROOT / "data/additions.json")["batches"] for pid in b["plantIds"]}
    old = {p["plantId"]: p for p in (prev or {}).get("plants", [])}
    if bd:
        masters, bd_commit = read_masters(bd, bd_ref)
        repo = {"repo": "fredericfourier/border-designer", "ref": bd_ref.removeprefix("origin/"), "commit": bd_commit, "dir": MASTER_DIR}
    else:
        masters, repo = None, (prev or {}).get("pngMasters")
    brief_commit = None
    if bd:
        brief_commit = git(bd, "log", "-1", "--format=%h", bd_ref, "--", BRIEF).decode().strip()
    brief = {"repo": "fredericfourier/border-designer", "file": BRIEF,
             "version": brief_commit or (prev or {}).get("brief", {}).get("version")}
    plants = []
    for n, p in enumerate(cat, 1):
        pid = p["id"]
        webp, wc = ASSETS / f"{pid}.webp", ASSETS / f"{pid}-watercolour.webp"
        v, notes = ver.get(pid), []
        o = old.get(pid, {})
        if masters is not None:
            png_path, png_sha = masters.get(pid, (None, None))
        else:
            png_path, png_sha = o.get("pngMasterPath"), o.get("pngSha256")
        webp_sha = sha256(webp) if webp.is_file() else None
        form = {(False, False): "none", (True, False): "png_only", (False, True): "webp_only", (True, True): "both"}[(bool(png_path), bool(webp_sha))]
        vstate = v["status"] if v else "none"
        basis = None
        if v and v["status"] == "confirmed":
            basis = "explicit_approval" if v.get("approvedAt") else "auto_confirmed_on_filename_match"
        if basis == "auto_confirmed_on_filename_match":
            notes.append("confirmed by filename match only; no approval timestamp")
        problems = []
        if v and webp_sha and v.get("imageSha256") != webp_sha:
            problems.append("webp hash differs from botanical-verification.json")
        if v and png_sha and v.get("pngSha256") and v["pngSha256"] != png_sha:
            problems.append("png master hash differs from botanical-verification.json")
        if webp_sha and amf.get(pid, {}).get("sha256") not in (None, webp_sha):
            problems.append("webp hash differs from assets manifest")
        if form == "none":
            status = "missing"
        elif problems:
            status = "uncertain_match"
            notes += problems
        elif v and v["status"] == "confirmed" and form == "both":
            status = "approved"
        else:
            status = "pending_review"
            if form != "both":
                notes.append("incomplete: " + ("png master without published webp" if form == "png_only" else "webp without png master"))
        man = o.get("manualStatus")
        if man and (man.get("imageSha256") == webp_sha):
            status = man["status"]
            notes.append("manual " + man["status"] + (": " + man["note"] if man.get("note") else ""))
        qa = amf.get(pid, {}).get("status")
        if qa in ("warning", "needs-review"):
            notes.append(f"pipeline QA: {qa} (ratio error {amf[pid].get('ratioErrorRelative')})")
        if v and v.get("previous"):
            notes.append("earlier image version superseded (hash history in botanical-verification.json)")
        if status == "missing":
            notes.append("no botanical asset in either repository; new in E3 catalogue v1.0")
        stamps = [t for t in ((v or {}).get("importedAt"), (v or {}).get("approvedAt")) if t]
        rec = {
            "order": n, "plantId": pid, "botanicalName": p["botanicalName"], "status": status,
            "expectsBotanical": True, "expectsWatercolour": True, "assetForm": form,
            "pngMasterPath": png_path, "pngSha256": png_sha,
            "webpPath": f"assets/plant-watercolours/{pid}.webp" if webp_sha else None, "webpSha256": webp_sha,
            "verificationState": vstate, "approvalBasis": basis,
            "matchConfidence": (v or {}).get("bundleMatchStatus"), "pipelineQa": qa,
            "watercolour": {"status": ((v or {}).get("watercolour") or {}).get("status", "missing") if wc.is_file() else "missing",
                            "webpPath": f"assets/plant-watercolours/{pid}-watercolour.webp" if wc.is_file() else None},
            "notes": "; ".join(notes), "lastUpdated": max(stamps) if stamps else added.get(pid, "") + "T00:00:00Z",
        }
        if man and man.get("imageSha256") == webp_sha:
            rec["manualStatus"] = man
        plants.append(rec)
    counts = {s: sum(r["status"] == s for r in plants) for s in STATUSES}
    return {
        "schemaVersion": 1,
        "description": "Botanical illustration status per catalogue plant, in catalogue order. Derived from repository state by tools/botanical_status.py; "
                       "see docs/BOTANICAL_STATUS.md. Only status=missing enters the generation queue.",
        "statusDefinitions": {
            "missing": "no botanical PNG master and no botanical WebP in either repository; the only status the generation queue picks up",
            "pending_review": "an image exists (generated or imported) but is not approved in data/botanical-verification.json, or is only half published",
            "approved": "PNG master and WebP both exist, hashes agree and data/botanical-verification.json status is confirmed",
            "rejected": "manual: image rejected; regenerate only when explicitly requested",
            "uncertain_match": "manual or hash-mismatch: identity or file integrity in doubt; never counted as approved"},
        "catalogue": {"path": "data/plants.json", "count": len(cat)},
        "pngMasters": repo, "brief": brief,
        "updated": max(r["lastUpdated"] for r in plants),
        "summary": {"total": len(plants), **counts},
        "plants": plants,
    }


def dump(d):
    return json.dumps(d, indent=2, ensure_ascii=False) + "\n"


def check():
    cur = load(MANIFEST)
    errs = []
    cat = [p["id"] for p in load(ROOT / "data/plants.json")["plants"]]
    ids = [p["plantId"] for p in cur["plants"]]
    if len(set(ids)) != len(ids):
        errs.append("duplicate plantId in manifest")
    if ids != cat:
        errs.append(f"manifest ids differ from catalogue order (missing {sorted(set(cat) - set(ids))}, extra {sorted(set(ids) - set(cat))})")
    bad = [p["plantId"] for p in cur["plants"] if p["status"] not in STATUSES]
    if bad:
        errs.append(f"unknown status: {bad}")
    claimed = set()
    for p in cur["plants"]:
        pid = p["plantId"]
        w, c = p["webpPath"], p["watercolour"]["webpPath"]
        if w:
            claimed.add(w)
            if w != f"assets/plant-watercolours/{pid}.webp" or w.endswith("-watercolour.webp") or not (ROOT / w).is_file():
                errs.append(f"{pid}: bad botanical webp path {w}")
        if c:
            claimed.add(c)
            if c != f"assets/plant-watercolours/{pid}-watercolour.webp" or not (ROOT / c).is_file():
                errs.append(f"{pid}: bad watercolour webp path {c}")
        if p["pngMasterPath"] and (p["pngMasterPath"].endswith("-watercolour.png") or p["pngMasterPath"] != f"{MASTER_DIR}/{pid}.png"):
            errs.append(f"{pid}: bad png master path {p['pngMasterPath']}")
        if p["status"] == "missing" and (p["assetForm"] != "none" or w or p["pngMasterPath"]):
            errs.append(f"{pid}: status missing but an asset exists")
        if p["status"] == "approved" and (p["verificationState"] != "confirmed" or p["assetForm"] != "both"):
            errs.append(f"{pid}: approved without confirmed verification and both files")
    orphans = sorted(str(f.relative_to(ROOT)) for f in ASSETS.glob("*.webp") if str(f.relative_to(ROOT)) not in claimed)
    if orphans:
        errs.append(f"webp files not claimed by any plant: {orphans}")
    if cur["summary"] != build(cur)["summary"] or dump(build(cur)) != dump(cur):
        errs.append("manifest is stale: run `python3 tools/botanical_status.py build` (PNG master fields are kept as recorded)")
    return errs


def queue(cur, n, skip):
    return [p["plantId"] for p in cur["plants"] if p["status"] == "missing"][skip:skip + n]


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build"); b.add_argument("--bd"); b.add_argument("--bd-ref", default="origin/main")
    sub.add_parser("check"); sub.add_parser("summary")
    q = sub.add_parser("queue"); q.add_argument("n", nargs="?", type=int, default=10); q.add_argument("--skip", type=int, default=0); q.add_argument("--json", action="store_true")
    s = sub.add_parser("set"); s.add_argument("status", choices=MANUAL); s.add_argument("ids", nargs="+"); s.add_argument("--note", default="")
    a = ap.parse_args()
    prev = load(MANIFEST) if MANIFEST.is_file() else None
    if a.cmd == "build":
        MANIFEST.write_text(dump(build(prev, a.bd, a.bd_ref)), encoding="utf-8")
        print("wrote", MANIFEST.relative_to(ROOT), load(MANIFEST)["summary"])
    elif a.cmd == "check":
        errs = check()
        print("\n".join(errs) if errs else "OK: botanical status manifest is consistent", file=sys.stderr if errs else sys.stdout)
        sys.exit(1 if errs else 0)
    elif a.cmd == "summary":
        print(json.dumps(prev["summary"]))
    elif a.cmd == "queue":
        ids = queue(prev, a.n, a.skip)
        print(json.dumps(ids) if a.json else "\n".join(ids))
    elif a.cmd == "set":
        by = {p["plantId"]: p for p in prev["plants"]}
        unknown = [i for i in a.ids if i not in by]
        if unknown:
            sys.exit(f"unknown plant ids: {unknown}")
        for i in a.ids:
            by[i]["manualStatus"] = {"status": a.status, "imageSha256": by[i]["webpSha256"], "note": a.note,
                                      "setAt": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}
        MANIFEST.write_text(dump(build(prev)), encoding="utf-8")
        print(a.status, a.ids)


if __name__ == "__main__":
    main()
