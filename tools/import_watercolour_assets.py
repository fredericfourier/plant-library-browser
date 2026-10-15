#!/usr/bin/env python3
"""Import watercolour illustrations from `watercolours_65_part_NN_of_MM.zip` bundles (watercolour variant only).

Usage: import_watercolour_assets.py <plb-root> <bd-root|-> <data/plants.json> <report.json> <extracted-part-dir> [...]
Each part dir holds <plant-id>-watercolour.png and <plant-id>-watercolour.webp. Per plant:
  public WebP   <plb>/assets/plant-watercolours/<id>-watercolour.webp   supplied WebP, byte-for-byte
  private PNG   <bd>/assets/plant-watercolours/masters/<id>-watercolour.png   supplied PNG, byte-for-byte (skipped when <bd-root> is "-")
  manifest      assets/plant-watercolours/manifest.json  -> assets[id].variants.watercolour (file facts, sha256, status awaiting_review)
  review status data/botanical-verification.json -> plants[id].watercolour = {status: awaiting_review, imageSha256, importedAt}
Botanical images/records are never touched. Re-importing identical bytes leaves the record alone; different bytes reset it to
awaiting_review and keep the old state under `previous`. Nothing is cropped, scaled, recoloured or re-encoded.
"""
import hashlib, json, shutil, sys, datetime
from pathlib import Path
import numpy as np
from PIL import Image

plb, bd, plants_json, report_path, *parts = sys.argv[1:]
plb = Path(plb); bd = None if bd == "-" else Path(bd)
ids = {p["id"] for p in (lambda d: d.get("plants", d))(json.loads(Path(plants_json).read_text()))}
now = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
sha = lambda b: hashlib.sha256(b).hexdigest()
found, problems = {}, []
for part in parts:
    for png in sorted(Path(part).glob("*-watercolour.png")):
        pid = png.name[: -len("-watercolour.png")]
        webp = png.with_suffix(".webp")
        if pid in found:
            problems.append({"id": pid, "problems": ["duplicate in " + part]}); continue
        found[pid] = (png, webp)
rec, ok = {}, []
for pid, (png, webp) in sorted(found.items()):
    pr = []
    if pid not in ids: pr.append("not a database plant id")
    if not webp.exists(): pr.append("missing webp")
    else:
        try:
            a, b = Image.open(png), Image.open(webp); a.load(); b.load()
            pa, pb = np.asarray(a.convert("RGBA").getchannel("A")), np.asarray(b.convert("RGBA").getchannel("A"))
            if a.mode != "RGBA" or b.mode != "RGBA": pr.append(f"mode {a.mode}/{b.mode}")
            if a.size != b.size: pr.append("png/webp size differ")
            elif not np.array_equal(pa > 8, pb > 8): pr.append("png/webp alpha masks differ")
            if pa.min() != 0 or (pa < 8).mean() < 0.05: pr.append("no real transparency (opaque background?)")
        except Exception as e: pr.append("decode: " + str(e))
    if pr: problems.append({"id": pid, "problems": pr}); continue
    rec[pid] = {"w": a.width, "h": a.height, "png": sha(png.read_bytes()), "webp": sha(webp.read_bytes())}; ok.append(pid)
if problems:
    Path(report_path).write_text(json.dumps({"problems": problems}, indent=1)); print(json.dumps(problems, indent=1)); sys.exit("validation failed; nothing written")

mpath, vpath = plb / "assets/plant-watercolours/manifest.json", plb / "data/botanical-verification.json"
man, ver = json.loads(mpath.read_text()), json.loads(vpath.read_text())
assets = man.get("assets", man); replaced, added, unchanged = [], [], []
for pid in ok:
    png, webp = found[pid]; r = rec[pid]; dest = plb / f"assets/plant-watercolours/{pid}-watercolour.webp"
    old = dest.read_bytes() if dest.exists() else None
    if old is not None and sha(old) == r["webp"]: unchanged.append(pid)
    else: (replaced if old is not None else added).append(pid)
    shutil.copyfile(webp, dest)
    if bd: shutil.copyfile(png, bd / f"assets/plant-watercolours/masters/{pid}-watercolour.png")
    a = assets[pid]; v = a.setdefault("variants", {}); prev = v.get("watercolour") or {}
    v["watercolour"] = {"label": "Watercolour", "file": f"assets/plant-watercolours/{pid}-watercolour.webp", "status": "awaiting_review",
        "productionReady": False, "canonicalScaleApplied": False, "originalWidthPx": r["w"], "originalHeightPx": r["h"], "transparent": True,
        "sha256": r["webp"], "pngSha256": r["png"], "warnings": []}
    cur = ver["plants"][pid].get("watercolour")
    if cur and cur.get("imageSha256") == r["webp"]: continue
    new = {"status": "awaiting_review", "imageSha256": r["webp"], "pngSha256": r["png"], "importedAt": now}
    if cur: new["previous"] = {**cur, "supersededAt": now}
    elif prev.get("sha256"): new["previous"] = {"status": prev.get("status"), "imageSha256": prev.get("sha256"), "supersededAt": now}
    ver["plants"][pid]["watercolour"] = new
man["updated"] = now[:10]; ver["updated"] = now
ver["watercolourNote"] = "plants[id].watercolour.status is awaiting_review until approved by editing this file (never automatically)."
mpath.write_text(json.dumps(man, indent=2) + "\n"); vpath.write_text(json.dumps(ver, indent=2) + "\n")
out = {"imported": len(ok), "added": added, "replaced_existing": replaced, "unchanged": unchanged, "problems": []}
Path(report_path).write_text(json.dumps(out, indent=1)); print(json.dumps({k: (len(v) if isinstance(v, list) else v) for k, v in out.items()}))
print("replaced:", replaced)
