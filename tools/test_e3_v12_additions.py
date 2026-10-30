#!/usr/bin/env python3
"""Checks for the three E3 v1.2-candidate plants added to the browser catalogue (run: python3 tools/test_e3_v12_additions.py).

Data-only checks: ids, working sizes, conditional suitability wording, 'Newly added' batch, and missing-illustration status in both manifests and the queues.
The illustration ZIP build is covered by .github/workflows/verify-illustrations-zip.yml."""
import json, subprocess, sys, unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
NEW = {"sarcococca-hookeriana-var-humilis": (60, 90, ["creamy-white", "December to March", "dry shade"]),
       "hydrangea-incrediball": (125, 125, ["reliably moist", "Not for dry sites"]),
       "astilbe-weisse-gloria": (70, 45, ["moist", "drought intolerant"])}
load = lambda p: json.loads((ROOT / p).read_text(encoding="utf-8"))


class Additions(unittest.TestCase):
    def setUp(self): self.plants = load("data/plants.json")["plants"]; self.by = {p["id"]: p for p in self.plants}

    def test_ids_unique_and_count(self):
        ids = [p["id"] for p in self.plants]
        self.assertEqual(len(ids), len(set(ids))); self.assertGreaterEqual(len(ids), 108); self.assertTrue(set(NEW) <= set(ids))
        names = [p["botanicalName"] for p in self.plants]; self.assertEqual(len(names), len(set(names)))

    def test_working_sizes_and_conditions_in_description(self):
        for i, (h, w, words) in NEW.items():
            p = self.by[i]; self.assertEqual((p["heightCm"], p["spreadCm"]), (h, w)); self.assertIn("not an exact mature measurement", p["description"])
            for word in words: self.assertIn(word, p["description"], i)

    def test_in_newly_added_batch(self):
        b = [x for x in load("data/additions.json")["batches"] if set(NEW) <= set(x["plantIds"])]
        self.assertEqual(len(b), 1); self.assertEqual(sorted(b[0]["plantIds"]), sorted(NEW))

    def test_illustrations_missing_in_every_record(self):
        assets = load("assets/plant-watercolours/manifest.json")["assets"]
        for i in NEW: self.assertNotIn(i, assets)
        for f in ("data/botanical-status.json", "data/watercolour-status.json"):
            rows = {p["plantId"]: p for p in load(f)["plants"]}
            for i in NEW: self.assertEqual((rows[i]["status"], rows[i]["assetForm"]), ("missing", "none"), (f, i))

    def test_queues_list_them(self):
        for t in ("botanical", "watercolour"):
            r = subprocess.run([sys.executable, str(ROOT / "tools/botanical_status.py"), "--type", t, "queue", "10"], capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stderr); self.assertTrue(set(NEW) <= set(r.stdout.split()), (t, r.stdout))


if __name__ == "__main__": unittest.main(verbosity=2)
