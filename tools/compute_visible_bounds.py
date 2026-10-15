#!/usr/bin/env python3
"""Compute the visible-content bounding box (alpha > 8) of every illustration and write data/illustration-bounds.json.

Usage: compute_visible_bounds.py [plb-root]     (default: repo root). Images are only read, never modified.
Output: {"threshold":8,"bounds":{"<id>":{"botanical":{"w":W,"h":H,"box":[x0,y0,x1,y1]},"watercolour":{...}}}}
box is in image pixels, x1/y1 exclusive. Re-run whenever an illustration file changes.
"""
import json, sys
from pathlib import Path
from PIL import Image

THRESHOLD = 8
root = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parent.parent
manifest = json.loads((root / "assets/plant-watercolours/manifest.json").read_text())
assets = manifest.get("assets", manifest)


def bounds(path):
    im = Image.open(path).convert("RGBA")
    mask = im.getchannel("A").point(lambda a: 255 if a > THRESHOLD else 0)
    box = mask.getbbox()
    return {"w": im.width, "h": im.height, "box": list(box) if box else None}


out = {}
for pid, rec in sorted(assets.items()):
    ent = {}
    files = {"botanical": rec.get("file") or f"assets/plant-watercolours/{pid}.webp"}
    for name, v in (rec.get("variants") or {}).items():
        if v and v.get("file"):
            files[name] = v["file"]
    for name, f in files.items():
        p = root / f
        if p.exists():
            ent[name] = bounds(p)
    out[pid] = ent
(root / "data/illustration-bounds.json").write_text(json.dumps({"threshold": THRESHOLD, "bounds": out}, separators=(",", ":")) + "\n")
print(len(out), "plants;", sum(len(v) for v in out.values()), "images")
