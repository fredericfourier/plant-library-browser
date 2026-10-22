#!/usr/bin/env python3
"""Isolated tests for tools/import_watercolour_assets.py. Run: python3 tools/test_watercolour_import.py

Every test builds its own throwaway project (public repo, private masters repo, incoming bundle); nothing real is read or written.
"""
import hashlib, json, os, shutil, subprocess, tempfile, unittest
from pathlib import Path

from PIL import Image

REPO = Path(__file__).resolve().parent.parent
A = "assets/plant-watercolours/"
TODAY = "2026-10-22"


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def sh(cwd, *a, env=None):
    return subprocess.run(list(a), capture_output=True, text=True, cwd=cwd, env=env)


def make_pair(folder, pid, seed, opaque=False):
    """Real RGBA PNG + lossless WebP with genuine transparency (or an opaque one, which must be rejected)."""
    folder.mkdir(parents=True, exist_ok=True)
    im = Image.new("RGBA", (64, 48), (seed * 7 % 256, seed * 13 % 256, 90, 0))
    for x in range(16, 48):
        for y in range(10, 40):
            im.putpixel((x, y), (seed * 7 % 256, 200 - seed * 3 % 100, seed * 29 % 256, 255 if opaque or (x + y) % 3 else 128))
    if opaque:
        im.paste((seed % 256, 10, 10, 255), (0, 0, 64, 48))
    im.save(folder / f"{pid}-watercolour.png")
    im.save(folder / f"{pid}-watercolour.webp", "WEBP", lossless=True)


class ImportCase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.plb, self.bd, self.inc = self.tmp / "plb", self.tmp / "bd", self.tmp / "incoming"
        for d in (self.plb / "data", self.plb / "tools", self.plb / A, self.bd / A / "masters", self.bd / "docs/briefs", self.bd / "docs/references"):
            d.mkdir(parents=True)
        shutil.copy(REPO / "tools/botanical_status.py", self.plb / "tools")
        self.ids = ["old-plant", "new-a", "new-b", "new-c"]  # old-plant has a botanical image; the others have nothing
        (self.plb / "data/plants.json").write_text(json.dumps({"plants": [
            {"id": i, "botanicalName": f"Plantus {i}", "heightCm": 50, "spreadCm": 40} for i in self.ids]}))
        (self.plb / "data/additions.json").write_text(json.dumps({"batches": [{"date": "2026-10-01", "plantIds": self.ids}]}))
        botanical = self.plb / A / "old-plant.webp"
        botanical.write_bytes(b"RIFFWEBPbotanical")
        (self.bd / A / "masters/old-plant.png").write_bytes(b"PNGbotanical")
        self.bot_ver = {"status": "confirmed", "imageSha256": sha(botanical), "pngSha256": sha(self.bd / A / "masters/old-plant.png"),
                        "bundleMatchStatus": "filename_match_unreviewed", "importedAt": "2026-10-15T00:00:00Z", "approvedAt": "2026-10-16T00:00:00Z"}
        self.bot_asset = {"file": A + "old-plant.webp", "status": "ready", "sha256": sha(botanical), "extra": {"keep": [1, 2]}}
        (self.plb / "data/botanical-verification.json").write_text(json.dumps({"schemaVersion": 1, "plants": {"old-plant": self.bot_ver}}, indent=2) + "\n")
        (self.plb / A / "manifest.json").write_text(json.dumps({"schemaVersion": 1, "assets": {"old-plant": self.bot_asset}}, indent=2) + "\n")
        (self.bd / "docs/briefs/BOTANICAL_ASSET_BRIEF.md").write_text("b")
        (self.bd / "docs/briefs/WATERCOLOUR_B_ASSET_BRIEF.md").write_text("w")
        (self.bd / "docs/references/nepeta-watercolour-very-wet-approved.png").write_bytes(b"ref")
        self.commit_bd()

    # -- helpers
    def commit_bd(self):
        if not (self.bd / ".git").exists():
            sh(self.bd, "git", "init", "-q", "-b", "main")
        sh(self.bd, "git", "add", "-A")
        sh(self.bd, "git", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "--allow-empty", "-m", "bd")

    def importer(self, *folders, bd=True, env=None):
        e = {**os.environ, **(env or {})}
        return sh(self.tmp, "python3", str(REPO / "tools/import_watercolour_assets.py"), str(self.plb), str(self.bd) if bd else "-",
                  str(self.plb / "data/plants.json"), str(self.tmp / "report.json"), *map(str, folders), env=e)

    def snapshot(self):
        """Every file of both repos (bytes) so 'nothing changed' is exact, including stray temp files."""
        out = {}
        for root in (self.plb, self.bd):
            for f in sorted(root.rglob("*")):
                if f.is_file() and ".git" not in f.parts:
                    out[str(f.relative_to(self.tmp))] = f.read_bytes()
        return out

    def ver(self):
        return json.loads((self.plb / "data/botanical-verification.json").read_text())

    def man(self):
        return json.loads((self.plb / A / "manifest.json").read_text())

    def bundle(self, name, items, **kw):
        d = self.inc / name
        for pid, seed in items:
            make_pair(d, pid, seed, **kw)
        return d

    def approve(self, pid):
        v = self.ver()
        v["plants"][pid]["watercolour"].update({"status": "confirmed", "approvedAt": "2026-10-17T00:00:00Z"})
        (self.plb / "data/botanical-verification.json").write_text(json.dumps(v, indent=2) + "\n")

    def tool(self, kind, *a):
        return sh(self.plb, "python3", "tools/botanical_status.py", "--type", kind, *a)

    def rebuild(self):
        self.commit_bd()
        for k in ("botanical", "watercolour"):
            r = self.tool(k, "build", "--bd", str(self.bd), "--bd-ref", "HEAD")
            self.assertEqual(r.returncode, 0, r.stderr)

    def queue(self, kind="watercolour"):
        r = self.tool(kind, "queue", "50", "--json", "--today", TODAY)
        self.assertEqual(r.returncode, 0, r.stderr)
        return json.loads(r.stdout)


class WatercolourOnlyImport(ImportCase):
    def test_new_catalogue_id_without_any_botanical_record(self):
        self.assertNotIn("new-a", self.man()["assets"])
        self.assertNotIn("new-a", self.ver()["plants"])
        d = self.bundle("p1", [("new-a", 1)])
        r = self.importer(d)
        self.assertEqual(r.returncode, 0, r.stderr + r.stdout)
        # bytes preserved exactly (no crop / resize / re-encode)
        self.assertEqual((self.plb / A / "new-a-watercolour.webp").read_bytes(), (d / "new-a-watercolour.webp").read_bytes())
        self.assertEqual((self.bd / A / "masters/new-a-watercolour.png").read_bytes(), (d / "new-a-watercolour.png").read_bytes())
        m = self.man()["assets"]["new-a"]
        self.assertEqual(list(m), ["variants"], "only the watercolour variant is created; no botanical field invented")
        w = m["variants"]["watercolour"]
        self.assertEqual((w["status"], w["sha256"], w["pngSha256"], w["file"]), ("awaiting_review", sha(d / "new-a-watercolour.webp"), sha(d / "new-a-watercolour.png"), A + "new-a-watercolour.webp"))
        self.assertEqual((w["originalWidthPx"], w["originalHeightPx"], w["transparent"]), (64, 48, True))
        v = self.ver()["plants"]["new-a"]
        self.assertEqual(list(v), ["watercolour"])
        self.assertEqual(v["watercolour"]["status"], "awaiting_review")
        self.assertFalse((self.plb / A / "new-a.webp").exists(), "no botanical image is created")

    def test_botanical_record_and_status_preserved_exactly(self):
        d = self.bundle("p1", [("old-plant", 2)])
        self.assertEqual(self.importer(d).returncode, 0)
        self.assertEqual({k: v for k, v in self.ver()["plants"]["old-plant"].items() if k != "watercolour"}, self.bot_ver)
        self.assertEqual({k: v for k, v in self.man()["assets"]["old-plant"].items() if k != "variants"}, self.bot_asset)
        self.assertEqual((self.plb / A / "old-plant.webp").read_bytes(), b"RIFFWEBPbotanical")
        self.assertEqual((self.bd / A / "masters/old-plant.png").read_bytes(), b"PNGbotanical")

    def test_reimport_identical_approved_artwork_changes_nothing(self):
        d = self.bundle("p1", [("new-a", 1), ("new-b", 2)])
        self.assertEqual(self.importer(d).returncode, 0)
        self.approve("new-a")
        before = self.snapshot()
        r = self.importer(d)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.snapshot(), before, "identical re-import must not touch any file or record")
        self.assertEqual(self.ver()["plants"]["new-a"]["watercolour"]["status"], "confirmed")
        self.assertEqual(json.loads((self.tmp / "report.json").read_text())["unchanged"], ["new-a", "new-b"])
        r2 = self.importer(d, bd=False)  # without the private repo the records still prove the PNG is unchanged
        self.assertEqual(r2.returncode, 0)
        self.assertEqual(self.snapshot(), before)

    def test_replacing_approved_artwork_resets_only_watercolour_review(self):
        self.assertEqual(self.importer(self.bundle("p1", [("old-plant", 3), ("new-a", 1)])).returncode, 0)
        self.approve("old-plant"); self.approve("new-a")
        approved = json.loads(json.dumps(self.ver()["plants"]["old-plant"]["watercolour"]))
        other = self.ver()["plants"]["new-a"]
        d2 = self.bundle("p2", [("old-plant", 9)])  # changed bytes for one plant only
        self.assertEqual(self.importer(d2).returncode, 0)
        v = self.ver()["plants"]
        w = v["old-plant"]["watercolour"]
        self.assertEqual((w["status"], w["imageSha256"], "approvedAt" in w), ("awaiting_review", sha(d2 / "old-plant-watercolour.webp"), False))
        self.assertEqual({k: x for k, x in w["previous"].items() if k != "supersededAt"}, approved)
        self.assertIn("supersededAt", w["previous"])
        self.assertEqual({k: x for k, x in v["old-plant"].items() if k != "watercolour"}, self.bot_ver, "botanical review untouched")
        self.assertEqual(v["new-a"], other, "other plants' approvals untouched")
        self.assertEqual(self.man()["assets"]["old-plant"]["variants"]["watercolour"]["status"], "awaiting_review")
        self.assertEqual((self.plb / A / "old-plant-watercolour.webp").read_bytes(), (d2 / "old-plant-watercolour.webp").read_bytes())
        self.assertEqual(json.loads((self.tmp / "report.json").read_text())["replaced_existing"], ["old-plant"])

    def test_same_webp_but_changed_png_counts_as_replacement(self):
        d = self.bundle("p1", [("new-a", 1)])
        self.assertEqual(self.importer(d).returncode, 0)
        self.approve("new-a")
        im = Image.open(d / "new-a-watercolour.png").convert("RGBA")
        im = Image.merge("RGBA", (*[c.point(lambda v: 255 - v) for c in im.split()[:3]], im.split()[3]))  # same alpha, different colours
        d2 = self.inc / "p2"
        d2.mkdir()
        im.save(d2 / "new-a-watercolour.png")
        shutil.copy(d / "new-a-watercolour.webp", d2 / "new-a-watercolour.webp")  # identical WebP bytes
        self.assertEqual(self.importer(d2).returncode, 0)
        w = self.ver()["plants"]["new-a"]["watercolour"]
        self.assertEqual(w["status"], "awaiting_review")
        self.assertEqual(w["pngSha256"], sha(d2 / "new-a-watercolour.png"))
        self.assertEqual(w["previous"]["status"], "confirmed")


class FailureAtomicity(ImportCase):
    def assert_untouched(self, r, before):
        self.assertNotEqual(r.returncode, 0)
        self.assertEqual(self.snapshot(), before)

    def test_invalid_asset_writes_nothing(self):
        before = self.snapshot()
        self.assert_untouched(self.importer(self.bundle("p1", [("new-a", 1)], opaque=True)), before)
        self.assertIn("no real transparency", (self.tmp / "report.json").read_text())

    def test_one_invalid_item_among_several_blocks_all(self):
        d = self.bundle("p1", [("new-a", 1), ("new-b", 2)])
        make_pair(d, "new-c", 3, opaque=True)
        make_pair(d, "not-in-catalogue", 4)
        (d / "new-b-watercolour.webp").unlink()
        before = self.snapshot()
        self.assert_untouched(self.importer(d), before)
        rep = json.loads((self.tmp / "report.json").read_text())["problems"]
        self.assertEqual({p["id"] for p in rep}, {"new-b", "new-c", "not-in-catalogue"})
        self.assertFalse((self.plb / A / "new-a-watercolour.webp").exists(), "the valid plant was not imported either")

    def test_missing_destination_and_corrupt_records_block_before_any_write(self):
        d = self.bundle("p1", [("new-a", 1)])
        shutil.rmtree(self.bd / A / "masters")
        before = self.snapshot()
        self.assert_untouched(self.importer(d), before)
        (self.bd / A / "masters").mkdir()
        (self.plb / "data/botanical-verification.json").write_text("{not json")
        before = self.snapshot()
        self.assert_untouched(self.importer(d), before)

    def test_failure_during_apply_rolls_back_everything(self):
        self.assertEqual(self.importer(self.bundle("p0", [("new-a", 1)])).returncode, 0)
        d = self.bundle("p1", [("new-a", 7), ("new-b", 2), ("new-c", 3)])  # one replacement + two new plants
        before = self.snapshot()
        for n in (1, 3, 5, 7):
            r = self.importer(d, env={"WC_IMPORT_FAIL_AFTER_WRITES": str(n)})
            self.assert_untouched(r, before)
            self.assertIn("rolled back", r.stderr)
        self.assertEqual(self.importer(d).returncode, 0, "the same import succeeds once the fault is gone")

    def test_unwritable_new_master_target_rolls_back(self):
        d = self.bundle("p1", [("new-a", 1), ("new-b", 2)])
        (self.bd / A / "masters" / "new-b-watercolour.png").mkdir()  # a directory squats on the target: replace fails mid-apply
        before = self.snapshot()
        r = self.importer(d)
        self.assertNotEqual(r.returncode, 0)
        self.assertEqual({k for k in self.snapshot()}, {k for k in before}, "no stray or half-written files")
        self.assertFalse((self.plb / A / "new-a-watercolour.webp").exists())
        self.assertNotIn("new-a", self.man()["assets"])


class StatusIntegration(ImportCase):
    def test_rebuild_after_import_and_imported_plants_leave_the_queue(self):
        self.rebuild()
        self.assertEqual(self.queue(), ["old-plant", "new-a", "new-b", "new-c"])
        self.assertEqual(self.queue("botanical"), ["new-a", "new-b", "new-c"])
        self.assertEqual(self.tool("watercolour", "reserve", "new-a", "new-b", "--batch", "ZIP-A", "--today", TODAY).returncode, 0)
        self.assertEqual(self.queue(), ["old-plant", "new-c"])
        self.assertEqual(self.importer(self.bundle("p1", [("new-a", 1), ("new-b", 2)])).returncode, 0)
        stale = self.tool("watercolour", "queue", "5", "--today", TODAY)
        self.assertEqual((stale.returncode, stale.stdout.strip()), (2, ""), "files changed since the last build: queue must refuse")
        self.rebuild()
        for k in ("watercolour", "botanical"):
            self.assertEqual(self.tool(k, "check", "--today", TODAY).returncode, 0, self.tool(k, "check", "--today", TODAY).stderr)
        m = {p["plantId"]: p for p in json.loads((self.plb / "data/watercolour-status.json").read_text())["plants"]}
        self.assertTrue(all(m[i]["status"] == "pending_review" and m[i]["assetForm"] == "both" and "reservation" not in m[i] for i in ("new-a", "new-b")))
        self.assertEqual(self.queue(), ["old-plant", "new-c"])
        self.assertEqual(self.queue("botanical"), ["new-a", "new-b", "new-c"], "a watercolour import does not touch the botanical queue")
        self.approve("new-a")  # approval later: still never re-queued
        self.rebuild()
        self.assertEqual(self.queue(), ["old-plant", "new-c"])
        self.assertEqual(self.importer(self.bundle("p1", [("new-a", 1), ("new-b", 2)])).returncode, 0)  # identical re-import
        self.rebuild()
        self.assertEqual({p["plantId"]: p["status"] for p in json.loads((self.plb / "data/watercolour-status.json").read_text())["plants"]}["new-a"], "approved")


if __name__ == "__main__":
    unittest.main(verbosity=2)
