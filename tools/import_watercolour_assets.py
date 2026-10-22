#!/usr/bin/env python3
"""Import watercolour illustrations from `watercolours_65_part_NN_of_MM.zip` bundles (watercolour variant only).

Usage: import_watercolour_assets.py <plb-root> <bd-root|-> <data/plants.json> <report.json> <extracted-part-dir> [...]
Each part dir holds <plant-id>-watercolour.png and <plant-id>-watercolour.webp. Per plant:
  public WebP   <plb>/assets/plant-watercolours/<id>-watercolour.webp   supplied WebP, byte-for-byte
  private PNG   <bd>/assets/plant-watercolours/masters/<id>-watercolour.png   supplied PNG, byte-for-byte (skipped when <bd-root> is "-")
  manifest      assets/plant-watercolours/manifest.json  -> assets[id].variants.watercolour (file facts, sha256, status awaiting_review)
  review status data/botanical-verification.json -> plants[id].watercolour = {status: awaiting_review, imageSha256, importedAt}
A catalogue plant with no botanical image and no existing manifest/verification entry is accepted: the entries are created holding only the
watercolour variant (assets[id] = {variants: {watercolour: ...}}, plants[id] = {watercolour: ...}); no botanical field is invented.
Botanical images/records are never touched; other fields of an existing entry are preserved exactly.
Re-importing identical bytes (same WebP and same PNG) changes nothing, so an approved watercolour stays approved. Different bytes reset only the
watercolour review state to awaiting_review and keep the old state under `previous`. Nothing is cropped, scaled, recoloured or re-encoded.
Everything is validated before any production file is touched; the writes are then staged and applied together, and rolled back if any fails,
so a failed import leaves no partial changes. Exit status 1 and nothing written when any file or destination is invalid.
"""
import datetime, hashlib, json, os, shutil, sys, tempfile
from pathlib import Path

import numpy as np
from PIL import Image

sha = lambda b: hashlib.sha256(b).hexdigest()
FAIL_AFTER_ENV = "WC_IMPORT_FAIL_AFTER_WRITES"  # test hook only: raise after N applied writes to exercise the rollback


def jload(p):
    return json.loads(Path(p).read_text(encoding="utf-8"))


def fail(report_path, problems):
    Path(report_path).write_text(json.dumps({"problems": problems}, indent=1))
    print(json.dumps(problems, indent=1))
    sys.exit("validation failed; nothing written")


def collect(parts):
    found, problems = {}, []
    for part in parts:
        for png in sorted(Path(part).glob("*-watercolour.png")):
            pid = png.name[: -len("-watercolour.png")]
            if pid in found:
                problems.append({"id": pid, "problems": ["duplicate in " + part]}); continue
            found[pid] = (png, png.with_suffix(".webp"))
    return found, problems


def check_image(pid, ids, png, webp):
    pr = []
    if pid not in ids: pr.append("not a database plant id")
    if not webp.exists(): return pr + ["missing webp"]
    try:
        a, b = Image.open(png), Image.open(webp); a.load(); b.load()
        pa, pb = np.asarray(a.convert("RGBA").getchannel("A")), np.asarray(b.convert("RGBA").getchannel("A"))
        if a.mode != "RGBA" or b.mode != "RGBA": pr.append(f"mode {a.mode}/{b.mode}")
        if a.size != b.size: pr.append("png/webp size differ")
        elif not np.array_equal(pa > 8, pb > 8): pr.append("png/webp alpha masks differ")
        if pa.min() != 0 or (pa < 8).mean() < 0.05: pr.append("no real transparency (opaque background?)")
        return pr, {"w": a.width, "h": a.height, "png": sha(png.read_bytes()), "webp": sha(webp.read_bytes())}
    except Exception as e:
        return pr + ["decode: " + str(e)]


def main(argv):
    plb, bd, plants_json, report_path, *parts = argv
    plb = Path(plb); bd = None if bd == "-" else Path(bd)
    now = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    found, problems = collect(parts)
    ids = {p["id"] for p in (lambda d: d.get("plants", d))(jload(plants_json))}
    dest_dir, mpath, vpath = plb / "assets/plant-watercolours", plb / "assets/plant-watercolours/manifest.json", plb / "data/botanical-verification.json"
    master_dir = bd / "assets/plant-watercolours/masters" if bd else None
    for what, ok in (("public assets dir", dest_dir.is_dir()), ("assets manifest", mpath.is_file()), ("verification file", vpath.is_file()),
                     ("private masters dir", master_dir is None or master_dir.is_dir())):
        if not ok: problems.append({"id": None, "problems": [f"destination missing: {what}"]})
    if not found and not problems: problems.append({"id": None, "problems": ["no *-watercolour.png files found"]})
    rec = {}
    for pid, (png, webp) in sorted(found.items()):
        res = check_image(pid, ids, png, webp)
        if isinstance(res, list): problems.append({"id": pid, "problems": res}); continue
        pr, facts = res
        if pr: problems.append({"id": pid, "problems": pr}); continue
        rec[pid] = facts
    man = ver = None
    if not problems:
        try:
            man, ver = jload(mpath), jload(vpath)
            assert isinstance(man.get("assets", man), dict) and isinstance(ver.get("plants"), dict)
        except Exception as e:
            problems.append({"id": None, "problems": [f"unreadable manifest/verification json: {e}"]})
    if problems:
        fail(report_path, problems)

    # ---- plan (in memory only) -------------------------------------------------------------------------------
    assets = man.get("assets", man)
    writes = []  # (destination path, bytes)
    added, replaced, unchanged, created_records = [], [], [], []
    for pid in sorted(rec):
        png, webp = found[pid]; r = rec[pid]
        wdest = dest_dir / f"{pid}-watercolour.webp"
        pdest = master_dir / f"{pid}-watercolour.png" if master_dir else None
        old_webp = wdest.read_bytes() if wdest.is_file() else None
        cur = (ver["plants"].get(pid) or {}).get("watercolour")
        if pdest is not None and pdest.is_file():
            old_png_sha = sha(pdest.read_bytes())
        else:  # masters not visible (or absent): fall back to what the records say
            old_png_sha = (cur or {}).get("pngSha256") or ((assets.get(pid) or {}).get("variants", {}).get("watercolour") or {}).get("pngSha256")
        if old_webp is not None and sha(old_webp) == r["webp"] and old_png_sha == r["png"] and cur:
            unchanged.append(pid); continue  # identical artwork: files and records stay exactly as they are
        (replaced if old_webp is not None else added).append(pid)
        writes.append((wdest, webp.read_bytes()))
        if pdest is not None: writes.append((pdest, png.read_bytes()))
        a = assets.setdefault(pid, {})
        if "variants" not in a: created_records.append(pid)
        v = a.setdefault("variants", {}); prev = v.get("watercolour") or {}
        v["watercolour"] = {"label": "Watercolour", "file": f"assets/plant-watercolours/{pid}-watercolour.webp", "status": "awaiting_review",
            "productionReady": False, "canonicalScaleApplied": False, "originalWidthPx": r["w"], "originalHeightPx": r["h"], "transparent": True,
            "sha256": r["webp"], "pngSha256": r["png"], "warnings": []}
        entry = ver["plants"].setdefault(pid, {})  # only the watercolour key is added to an existing botanical record
        new = {"status": "awaiting_review", "imageSha256": r["webp"], "pngSha256": r["png"], "importedAt": now}
        if cur: new["previous"] = {**cur, "supersededAt": now}
        elif prev.get("sha256"): new["previous"] = {"status": prev.get("status"), "imageSha256": prev.get("sha256"), "supersededAt": now}
        entry["watercolour"] = new
    if writes:
        man["updated"] = now[:10]; ver["updated"] = now
        ver["watercolourNote"] = "plants[id].watercolour.status is awaiting_review until approved by editing this file (never automatically)."
        writes.append((mpath, (json.dumps(man, indent=2) + "\n").encode()))
        writes.append((vpath, (json.dumps(ver, indent=2) + "\n").encode()))

    # ---- apply: stage every file next to its destination, back up originals, swap in, roll back on any failure --------
    backups, staged, done = {}, [], 0
    limit = int(os.environ.get(FAIL_AFTER_ENV, "-1"))
    try:
        for dest, data in writes:
            fd, tmp = tempfile.mkstemp(dir=dest.parent, prefix=".import-", suffix=".tmp")
            with os.fdopen(fd, "wb") as f: f.write(data)
            staged.append((dest, Path(tmp)))
        for dest, tmp in staged:
            backups[dest] = dest.read_bytes() if dest.is_file() else None
        for dest, tmp in staged:
            if limit >= 0 and done >= limit: raise RuntimeError("injected failure after %d writes" % done)
            os.replace(tmp, dest); done += 1
    except BaseException as e:
        for dest, old in backups.items():
            try:
                if old is None: dest.unlink(missing_ok=True)
                else: dest.write_bytes(old)
            except OSError: pass
        for _, tmp in staged: tmp.unlink(missing_ok=True)
        Path(report_path).write_text(json.dumps({"problems": [{"id": None, "problems": [f"write failed, rolled back: {e}"]}]}, indent=1))
        sys.exit(f"import failed and was rolled back; no files changed: {e}")
    out = {"imported": len(added) + len(replaced), "added": added, "replaced_existing": replaced, "unchanged": unchanged,
           "created_records_for": created_records, "problems": []}
    Path(report_path).write_text(json.dumps(out, indent=1)); print(json.dumps({k: (len(v) if isinstance(v, list) else v) for k, v in out.items()}))
    print("replaced:", replaced)


if __name__ == "__main__":
    main(sys.argv[1:])
