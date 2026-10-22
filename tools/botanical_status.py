#!/usr/bin/env python3
"""Deterministic botanical illustration status manifest and generation queue.

  botanical_status.py [--type botanical|watercolour] build [--bd <border-designer checkout> --bd-ref <ref>]   regenerate data/botanical-status.json
  botanical_status.py check                                                      validate manifest against the repo (exit 1 on any problem)
  botanical_status.py queue [N] [--skip K] [--json]                              first N plants still to generate (status missing), catalogue order; refuses stale manifests
  botanical_status.py summary                                                    status counts
  botanical_status.py set rejected|uncertain_match <plant-id> [...] [--note T]   pin a manual status (kept by later builds)
  botanical_status.py reserve <plant-id> [...] --batch B [--source ZIP] [--days N]   record a delivered generation package (not yet imported)
  botanical_status.py release (<plant-id> [...] | --batch B)                     drop a reservation (ZIP lost or rejected): back to missing
  botanical_status.py renew (<plant-id> [...] | --batch B) [--days N]            extend a reservation
  botanical_status.py reservations                                               list reservations (active / expired)

A reservation marks a plant generated-but-not-imported: status pending_review with assetForm none, skipped by `queue` (default expiry 14 days).
`queue` and `reserve` refuse to run (exit 2, no IDs) when the manifest is stale against the catalogue or files; `queue` also refuses while any
reservation is expired, and `check` fails: expired reservations are never re-queued automatically, they need an explicit `renew`, `release`,
or import followed by `build`. Importing the image clears the reservation automatically.
`approved` requires an explicit manual approval (approvedAt in data/botanical-verification.json); a record confirmed by filename match only
stays pending_review with approvalBasis=filename_match_only. This tool never writes data/botanical-verification.json.

The manifest is derived from repository state, never from memory: the catalogue (data/plants.json) fixes the plant list and order,
the published WebPs plus data/botanical-verification.json and assets/plant-watercolours/manifest.json fix what exists and what is
approved, and the private PNG masters are read from a border-designer ref when --bd is given (otherwise the recorded values are kept).
Botanical files are <id>.webp / <id>.png; watercolour files are <id>-watercolour.* and are tracked separately, never as botanical.
`--type watercolour` (before the subcommand) runs the same machinery over the watercolour variant: manifest data/watercolour-status.json, files
<id>-watercolour.webp / <id>-watercolour.png, approval from plants[id].watercolour in data/botanical-verification.json. The default type is
botanical and its behaviour and manifest are unchanged. The two statuses never read each other's files. `queue N --detail` prints the generation
metadata (dimensions, brief, reference image, expected filenames) for each queued plant.
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
WC_BRIEF = "docs/briefs/WATERCOLOUR_B_ASSET_BRIEF.md"
WC_REFERENCE = "docs/references/nepeta-watercolour-very-wet-approved.png"
# Per-variant naming. Module-level so every command shares one selection; set once from --type in main().
VARIANTS = {
    "botanical": {"suffix": "", "manifest": "data/botanical-status.json", "brief": BRIEF, "word": "botanical"},
    "watercolour": {"suffix": "-watercolour", "manifest": "data/watercolour-status.json", "brief": WC_BRIEF, "word": "watercolour"},
}
V = VARIANTS["botanical"]


def set_variant(name):
    global V, MANIFEST
    V = VARIANTS[name]
    MANIFEST = ROOT / V["manifest"]


def is_wc():
    return V["suffix"] != ""
RESERVE_DAYS = 14


def load(p):
    return json.loads(Path(p).read_text(encoding="utf-8"))


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def git(repo, *a):
    return subprocess.check_output(["git", "-C", str(repo), *a])


def read_masters(bd, ref):
    """{plant-id: (path, sha256)} for PNG masters of the active variant at <ref> in the border-designer checkout.

    Botanical: <id>.png (never *-watercolour.png). Watercolour: <id>-watercolour.png only."""
    out = {}
    sfx = V["suffix"]
    for line in git(bd, "ls-tree", "-r", "--name-only", ref, "--", MASTER_DIR).decode().splitlines():
        name = line.rsplit("/", 1)[-1]
        if not name.endswith(sfx + ".png") or (not sfx and name.endswith("-watercolour.png")):
            continue
        out[name[:-len(sfx + ".png")]] = (line, hashlib.sha256(git(bd, "show", f"{ref}:{line}")).hexdigest())
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
        brief_commit = git(bd, "log", "-1", "--format=%h", bd_ref, "--", V["brief"]).decode().strip()
    brief = {"repo": "fredericfourier/border-designer", "file": V["brief"],
             "version": brief_commit or (prev or {}).get("brief", {}).get("version")}
    if is_wc():
        ref_sha = hashlib.sha256(git(bd, "show", f"{bd_ref}:{WC_REFERENCE}")).hexdigest() if bd else (prev or {}).get("brief", {}).get("referenceImage", {}).get("sha256")
        brief["referenceImage"] = {"repo": "fredericfourier/border-designer", "file": WC_REFERENCE, "sha256": ref_sha}
    plants = []
    for n, p in enumerate(cat, 1):
        pid = p["id"]
        webp, wc = ASSETS / f"{pid}{V['suffix']}.webp", ASSETS / f"{pid}-watercolour.webp"
        v, notes = ver.get(pid), []
        asset = amf.get(pid, {})
        if is_wc():  # watercolour approval and file facts live under the watercolour variant only
            v = (v or {}).get("watercolour")
            asset = asset.get("variants", {}).get("watercolour", {})
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
            basis = "explicit_manual_approval" if v.get("approvedAt") else "filename_match_only"
        if basis == "filename_match_only":
            notes.append(f"manual {V['word']} approval absent: confirmed in botanical-verification.json by filename match only; "
                         "not a verified match, keeps its image, not regenerated")
        problems = []
        if v and webp_sha and v.get("imageSha256") != webp_sha:
            problems.append("webp hash differs from botanical-verification.json")
        if v and png_sha and v.get("pngSha256") and v["pngSha256"] != png_sha:
            problems.append("png master hash differs from botanical-verification.json")
        if webp_sha and asset.get("sha256") not in (None, webp_sha):
            problems.append("webp hash differs from assets manifest")
        if form == "none":
            status = "missing"
        elif problems:
            status = "uncertain_match"
            notes += problems
        elif basis == "explicit_manual_approval" and form == "both":
            status = "approved"
        else:
            status = "pending_review"
            if form != "both":
                notes.append("incomplete: " + ("png master without published webp" if form == "png_only" else "webp without png master"))
        res = o.get("reservation") if form == "none" else None
        if status == "missing" and res:
            status = "pending_review"
            notes.append(f"reserved: generated in batch {res['batchId']}, not yet imported (expires {res['expiresAt']})")
        man = o.get("manualStatus")
        if man and (man.get("imageSha256") == webp_sha):
            status = man["status"]
            notes.append("manual " + man["status"] + (": " + man["note"] if man.get("note") else ""))
        qa = asset.get("status")
        if qa in ("warning", "needs-review"):
            notes.append(f"pipeline QA: {qa} (ratio error {asset.get('ratioErrorRelative')})")
        if v and v.get("previous"):
            notes.append("earlier image version superseded (hash history in botanical-verification.json)")
        if status == "missing":
            notes.append(f"no {V['word']} asset in either repository; new in E3 catalogue v1.0")
        stamps = [t for t in ((v or {}).get("importedAt"), (v or {}).get("approvedAt")) if t]
        rec = {
            "order": n, "plantId": pid, "botanicalName": p["botanicalName"], "status": status,
            "expectsBotanical": True, "expectsWatercolour": True, "assetForm": form,
            "pngMasterPath": png_path, "pngSha256": png_sha,
            "webpPath": f"assets/plant-watercolours/{pid}{V['suffix']}.webp" if webp_sha else None, "webpSha256": webp_sha,
            "verificationState": vstate, "approvalBasis": basis,
            "matchConfidence": (v or {}).get("bundleMatchStatus"), "pipelineQa": qa,
            "watercolour": {"status": ((v or {}).get("watercolour") or {}).get("status", "missing") if wc.is_file() else "missing",
                            "webpPath": f"assets/plant-watercolours/{pid}-watercolour.webp" if wc.is_file() else None},
            "manualApprovalAt": (v or {}).get("approvedAt") if basis == "explicit_manual_approval" else None,
            "notes": "; ".join(notes),
            "lastUpdated": max(stamps) if stamps else (res["reservedAt"] if res else added.get(pid, "")) + "T00:00:00Z",
        }
        if is_wc():  # variant-neutral record: drop the botanical-shaped cross-reference keys, mark the type
            for k in ("expectsBotanical", "matchConfidence", "watercolour"):
                rec.pop(k)
            rec["illustrationType"] = "watercolour"
        if res:
            rec["reservation"] = res
        if man and man.get("imageSha256") == webp_sha:
            rec["manualStatus"] = man
        plants.append(rec)
    counts = {s: sum(r["status"] == s for r in plants) for s in STATUSES}
    counts["reserved_not_imported"] = sum("reservation" in r for r in plants)
    counts["filename_match_only"] =sum(r["approvalBasis"] == "filename_match_only" for r in plants)
    out = {
        "schemaVersion": 1,
        "description": "Botanical illustration status per catalogue plant, in catalogue order. Derived from repository state by tools/botanical_status.py; "
                       "see docs/BOTANICAL_STATUS.md. Only status=missing enters the generation queue.",
        "statusDefinitions": {
            "missing": "no botanical PNG master and no botanical WebP in either repository and no reservation; the status the generation queue picks up",
            "pending_review": "not approved by a person: a generated image delivered but not imported yet (reservation, assetForm none), an imported image "
                              "awaiting approval, an image confirmed by filename match only (approvalBasis=filename_match_only), or a half-published image",
            "approved": "PNG master and WebP both exist, hashes agree and data/botanical-verification.json carries an explicit manual approval (approvedAt)",
            "rejected": "manual: image rejected; regenerate only when explicitly requested",
            "uncertain_match": "manual or hash-mismatch: identity or file integrity in doubt; never counted as approved"},
        "catalogue": {"path": "data/plants.json", "count": len(cat)},
        "pngMasters": repo, "brief": brief,
        "updated": max(r["lastUpdated"] for r in plants),
        "summary": {"total": len(plants), **counts},
        "plants": plants,
    }
    if is_wc():
        keep = ("tools/botanical_status.py", "data/botanical-verification.json")  # file names are not variant words
        def word(t):
            for i, k in enumerate(keep):
                t = t.replace(k, f"@@{i}@@")
            t = t.replace("Botanical", "Watercolour").replace("botanical", "watercolour")
            t = t.replace("@@1@@ carries", "@@1@@ plants[id].watercolour carries")
            for i, k in enumerate(keep):
                t = t.replace(f"@@{i}@@", k)
            return t
        out["illustrationType"] = "watercolour"
        out["description"] = word(out["description"])
        out["statusDefinitions"] = {k: word(t) for k, t in out["statusDefinitions"].items()}
    return out


def dump(d):
    return json.dumps(d, indent=2, ensure_ascii=False) + "\n"


def today_str(a=None):
    return getattr(a, "today", None) or datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d")


def expired(p, today):
    return "reservation" in p and p["reservation"]["expiresAt"] < today


def check(today):
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
        w, c = p["webpPath"], p.get("watercolour", {}).get("webpPath")
        if is_wc():
            w, c = None, w  # a watercolour manifest only vouches for watercolour files
        if w:
            claimed.add(w)
            if w != f"assets/plant-watercolours/{pid}.webp" or w.endswith("-watercolour.webp") or not (ROOT / w).is_file():
                errs.append(f"{pid}: bad botanical webp path {w}")
        if c:
            claimed.add(c)
            if c != f"assets/plant-watercolours/{pid}-watercolour.webp" or not (ROOT / c).is_file():
                errs.append(f"{pid}: bad watercolour webp path {c}")
        if p["pngMasterPath"] and (p["pngMasterPath"] != f"{MASTER_DIR}/{pid}{V['suffix']}.png" or (not is_wc() and p["pngMasterPath"].endswith("-watercolour.png"))):
            errs.append(f"{pid}: bad png master path {p['pngMasterPath']}")
        if is_wc():
            claimed.add(f"assets/plant-watercolours/{pid}.webp")  # botanical files are another manifest's concern, not orphans
        if p["status"] == "missing" and (p["assetForm"] != "none" or w or c or p["pngMasterPath"]):
            errs.append(f"{pid}: status missing but an asset exists")
        if p["status"] == "approved" and (p["approvalBasis"] != "explicit_manual_approval" or not p["manualApprovalAt"] or p["assetForm"] != "both"):
            errs.append(f"{pid}: approved without explicit manual approval and both files")
        r = p.get("reservation")
        if r:
            if p["assetForm"] != "none" or p["status"] != "pending_review":
                errs.append(f"{pid}: reservation on a plant that is not reserved-and-not-imported")
            if not (r.get("batchId") and r.get("reservedAt") and r.get("expiresAt") and r["reservedAt"] <= r["expiresAt"]):
                errs.append(f"{pid}: malformed reservation {r}")
            elif r["expiresAt"] < today:
                errs.append(f"{pid}: reservation from batch {r['batchId']} expired {r['expiresAt']}: import it, `renew`, or `release` it")
        elif p["status"] == "pending_review" and p["assetForm"] == "none":
            errs.append(f"{pid}: pending_review with no files and no reservation")
    orphans = sorted(str(f.relative_to(ROOT)) for f in ASSETS.glob("*.webp") if str(f.relative_to(ROOT)) not in claimed)
    if orphans:
        errs.append(f"webp files not claimed by any plant: {orphans}")
    if cur["summary"] != build(cur)["summary"] or dump(build(cur)) != dump(cur):
        errs.append(f"manifest is stale: run `python3 tools/botanical_status.py{' --type watercolour' if is_wc() else ''} build` (PNG master fields are kept as recorded)")
    return errs


def stop(msg):
    print(msg, file=sys.stderr)
    sys.exit(2)


def require_fresh(cur, today=None):
    """Refuse to act on a manifest that no longer matches the repository (exit 2 with the fix). With `today`, also refuse expired reservations."""
    cat = [p["id"] for p in load(ROOT / "data/plants.json")["plants"]]
    ids = [p["plantId"] for p in cur["plants"]]
    problems = []
    if ids != cat:
        new, gone = [i for i in cat if i not in ids], [i for i in ids if i not in cat]
        problems.append(f"the catalogue (data/plants.json, {len(cat)} plants) and the manifest ({len(ids)}) differ"
                        + (f"; not in manifest: {', '.join(new)}" if new else "") + (f"; not in catalogue: {', '.join(gone)}" if gone else ""))
    elif dump(build(cur)) != dump(cur):
        problems.append("files or verification records changed since the manifest was built")
    if problems:
        stop("STOP: botanical status manifest is stale: " + "; ".join(problems) + ".\n"
                 "Run `python3 tools/botanical_status.py" + (" --type watercolour" if is_wc() else "") + " build --bd <border-designer checkout>`, review `git diff " + V["manifest"] + "`, "
                 "commit it, then repeat this command. No IDs were returned.")
    if today:
        late = [p for p in cur["plants"] if expired(p, today)]
        if late:
            stop("STOP: expired reservations must be reconciled before the queue can be trusted: "
                     + "; ".join(f"{p['plantId']} (batch {p['reservation']['batchId']}, expired {p['reservation']['expiresAt']})" for p in late)
                     + ".\nA generated package may still exist: import the images and `build`, or `renew --batch <B>`, or `release --batch <B>` "
                       "if the package is lost or rejected. No IDs were returned.")


def queue(cur, n, skip):
    """Plants still to generate: status missing, in catalogue order. Reserved plants (active or expired) are never returned."""
    return [p["plantId"] for p in cur["plants"] if p["status"] == "missing"][skip:skip + n]


def detail(cur, ids):
    """Generation metadata for queued plants: catalogue facts, expected filenames, brief and reference image."""
    by = {p["id"]: p for p in load(ROOT / "data/plants.json")["plants"]}
    rec = {p["plantId"]: p for p in cur["plants"]}
    brief = cur["brief"]
    out = []
    for pid in ids:
        c, h, w = by[pid], by[pid]["heightCm"], by[pid]["spreadCm"]
        entry = {
            "plantId": pid, "order": rec[pid]["order"], "botanicalName": c["botanicalName"], "commonName": c.get("commonName"),
            "illustrationType": V["word"], "heightCm": h, "spreadCm": w,
            "spreadToHeightRatio": round(w / h, 3), "proportions": f"{w} cm spread x {h} cm height (spread:height = {w / h:.2f}:1)",
            "status": rec[pid]["status"],
            "brief": {"file": brief["file"], "version": brief["version"]},
            "pngFilename": f"{pid}{V['suffix']}.png", "webpFilename": f"{pid}{V['suffix']}.webp",
            "pngMasterPath": f"{MASTER_DIR}/{pid}{V['suffix']}.png", "webpPath": f"assets/plant-watercolours/{pid}{V['suffix']}.webp",
            "catalogueRecordPath": f"data/plants.json#{pid}",
        }
        if brief.get("referenceImage"):
            entry["referenceImage"] = brief["referenceImage"]
        if "watercolourEnvelope" in c and is_wc():
            entry["watercolourEnvelope"] = c["watercolourEnvelope"]
        out.append(entry)
    return out


def pick(prev, a):
    by = {p["plantId"]: p for p in prev["plants"]}
    ids = list(a.ids) + [p["plantId"] for p in prev["plants"] if a.batch and p.get("reservation", {}).get("batchId") == a.batch and p["plantId"] not in a.ids]
    unknown = [i for i in ids if i not in by]
    if unknown or not ids:
        sys.exit(f"unknown or no plant ids: {unknown or '(none given)'}")
    return by, ids


def add_days(date, days):
    return (datetime.date.fromisoformat(date) + datetime.timedelta(days=days)).isoformat()


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--type", choices=sorted(VARIANTS), default="botanical", help="illustration variant (default botanical)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    day = lambda x: x.add_argument("--today", help="override today's date (YYYY-MM-DD), for tests")
    b = sub.add_parser("build"); b.add_argument("--bd"); b.add_argument("--bd-ref", default="origin/main")
    day(sub.add_parser("check")); sub.add_parser("summary"); day(sub.add_parser("reservations"))
    q = sub.add_parser("queue"); q.add_argument("n", nargs="?", type=int, default=10); q.add_argument("--skip", type=int, default=0); q.add_argument("--json", action="store_true")
    q.add_argument("--detail", action="store_true", help="print generation metadata for each queued plant as JSON"); day(q)
    s = sub.add_parser("set"); s.add_argument("status", choices=MANUAL); s.add_argument("ids", nargs="+"); s.add_argument("--note", default="")
    r = sub.add_parser("reserve"); r.add_argument("ids", nargs="+"); r.add_argument("--batch", required=True); r.add_argument("--source", default="")
    r.add_argument("--days", type=int, default=RESERVE_DAYS); day(r)
    for name in ("release", "renew"):
        x = sub.add_parser(name); x.add_argument("ids", nargs="*"); x.add_argument("--batch")
        if name == "renew":
            x.add_argument("--days", type=int, default=RESERVE_DAYS); day(x)
    a = ap.parse_args()
    set_variant(a.type)
    prev = load(MANIFEST) if MANIFEST.is_file() else None
    today = today_str(a)
    save = lambda d: MANIFEST.write_text(dump(d), encoding="utf-8")
    if a.cmd == "build":
        save(build(prev, a.bd, a.bd_ref))
        print("wrote", MANIFEST.relative_to(ROOT), load(MANIFEST)["summary"])
    elif a.cmd == "check":
        errs = check(today)
        print("\n".join(errs) if errs else "OK: botanical status manifest is consistent", file=sys.stderr if errs else sys.stdout)
        sys.exit(1 if errs else 0)
    elif a.cmd == "summary":
        print(json.dumps(prev["summary"]))
    elif a.cmd == "queue":
        require_fresh(prev, today)
        ids = queue(prev, a.n, a.skip)
        if a.detail:
            print(json.dumps(detail(prev, ids), indent=2, ensure_ascii=False))
        else:
            print(json.dumps(ids) if a.json else "\n".join(ids))
    elif a.cmd == "reservations":
        for p in prev["plants"]:
            if "reservation" in p:
                x = p["reservation"]
                print(p["plantId"], x["batchId"], x["reservedAt"], x["expiresAt"], "EXPIRED" if expired(p, today) else "active", x.get("source", ""), sep="\t")
    elif a.cmd == "set":
        by = {p["plantId"]: p for p in prev["plants"]}
        unknown = [i for i in a.ids if i not in by]
        if unknown:
            sys.exit(f"unknown plant ids: {unknown}")
        for i in a.ids:
            by[i]["manualStatus"] = {"status": a.status, "imageSha256": by[i]["webpSha256"], "note": a.note,
                                      "setAt": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}
        save(build(prev))
        print(a.status, a.ids)
    elif a.cmd == "reserve":
        require_fresh(prev)
        by = {p["plantId"]: p for p in prev["plants"]}
        unknown = [i for i in a.ids if i not in by]
        if unknown:
            sys.exit(f"unknown plant ids: {unknown}")
        refused = [f"{i} ({by[i]['status']}{', reserved in batch ' + by[i]['reservation']['batchId'] if 'reservation' in by[i] else ''})"
                   for i in a.ids if by[i]["status"] != "missing"]
        if refused:
            sys.exit("only plants with status missing can be reserved (renew or release an existing reservation first); refused: " + "; ".join(refused))
        for i in a.ids:
            by[i]["reservation"] = {"batchId": a.batch, "source": a.source, "reservedAt": today, "expiresAt": add_days(today, a.days)}
            by[i]["status"] = "missing"  # let build re-derive pending_review from the reservation
        save(build(prev))
        print(f"reserved {len(a.ids)} plants in batch {a.batch} until {add_days(today, a.days)}:", ", ".join(a.ids))
    elif a.cmd in ("release", "renew"):
        by, ids = pick(prev, a)
        none = [i for i in ids if "reservation" not in by[i]]
        if none:
            sys.exit(f"no reservation on: {none}")
        for i in ids:
            if a.cmd == "release":
                del by[i]["reservation"]
            else:
                by[i]["reservation"]["expiresAt"] = add_days(today, a.days)
        save(build(prev))
        print(a.cmd + "d", ", ".join(ids))


if __name__ == "__main__":
    main()
