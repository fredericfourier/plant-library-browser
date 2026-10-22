#!/usr/bin/env python3
"""Tests for the botanical/watercolour illustration status queue (tools/botanical_status.py).

Run: python3 tools/test_illustration_status.py
Every test works on a throwaway copy of the repository data; the real repository is never written.
"""
import hashlib, json, shutil, subprocess, sys, tempfile, unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
TODAY = "2026-10-22"
BOT_FIRST_10 = ["delphinium-black-knight", "alcea-rosea-halo-white", "lupinus-the-governor", "lupinus-gallery-blue",
                "hydrangea-paniculata-little-lime", "syringa-meyeri-palibin", "centaurea-montana", "lychnis-coronaria",
                "polemonium-caeruleum", "linaria-purpurea"]


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.r = self.tmp / "r"
        self.r.mkdir()
        for d in ("data", "tools", "docs"):
            shutil.copytree(REPO / d, self.r / d)
        (self.r / "assets").mkdir()
        shutil.copytree(REPO / "assets/plant-watercolours", self.r / "assets/plant-watercolours")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.cat = [p["id"] for p in json.loads((self.r / "data/plants.json").read_text())["plants"]]

    def run_tool(self, kind, *args):
        a = ["python3", str(self.r / "tools/botanical_status.py")] + (["--type", kind] if kind else []) + list(args)
        return subprocess.run(a, capture_output=True, text=True, cwd=self.r)

    def q(self, kind, n=10, *extra):
        out = self.run_tool(kind, "queue", str(n), "--json", "--today", TODAY, *extra)
        self.assertEqual(out.returncode, 0, out.stderr)
        return json.loads(out.stdout)

    def wc_files(self):
        return {f.name[:-len("-watercolour.webp")] for f in (self.r / "assets/plant-watercolours").glob("*-watercolour.webp")}

    def bot_files(self):
        return {f.name[:-5] for f in (self.r / "assets/plant-watercolours").glob("*.webp") if not f.name.endswith("-watercolour.webp")}

    def manifest(self, kind):
        return self.r / ("data/watercolour-status.json" if kind == "watercolour" else "data/botanical-status.json")

    def status(self, kind):
        return {p["plantId"]: p for p in json.loads(self.manifest(kind).read_text())["plants"]}


class BotanicalUnchanged(Base):
    def test_A_botanical_queue_and_manifest_unchanged(self):  # A
        self.assertEqual(self.run_tool(None, "check", "--today", TODAY).returncode, 0)
        self.assertEqual(self.q(None), BOT_FIRST_10)
        self.assertEqual(self.q("botanical"), BOT_FIRST_10)
        self.assertEqual(len(self.q(None, 200)), 34)
        self.assertEqual(sha(self.manifest("botanical")), sha(REPO / "data/botanical-status.json"))
        s = json.loads(self.manifest("botanical").read_text())["summary"]
        self.assertEqual((s["approved"], s["pending_review"], s["missing"]), (32, 39, 34))

    def test_A_botanical_rebuild_is_byte_identical_apart_from_recorded_commit(self):  # A
        before = self.manifest("botanical").read_text()
        self.assertEqual(self.run_tool(None, "build").returncode, 0)  # no --bd: keeps recorded master fields
        self.assertEqual(self.manifest("botanical").read_text(), before)


class WatercolourQueue(Base):
    def setUp(self):
        super().setUp()
        self.assertTrue(self.manifest("watercolour").is_file(), "data/watercolour-status.json missing")

    def test_B_queue_is_exactly_the_plants_without_watercolour_files(self):  # B
        expected = [i for i in self.cat if i not in self.wc_files()]
        self.assertEqual(self.q("watercolour", 200), expected)
        self.assertEqual(len(expected), 34)
        self.assertEqual(self.run_tool("watercolour", "check", "--today", TODAY).returncode, 0)

    def test_C_existing_watercolours_never_selected(self):  # C
        got = set(self.q("watercolour", 200))
        self.assertFalse(got & self.wc_files())
        st = self.status("watercolour")
        for pid in self.wc_files():
            self.assertNotEqual(st[pid]["status"], "missing", pid)

    def test_D_pending_review_never_selected(self):  # D
        pid = next(i for i in self.cat if i not in self.wc_files())
        # an imported-but-unapproved half (webp only) and a verification record awaiting review
        (self.r / f"assets/plant-watercolours/{pid}-watercolour.webp").write_bytes(b"RIFFWEBPx")
        stale = self.run_tool("watercolour", "queue", "5", "--today", TODAY)
        self.assertEqual((stale.returncode, stale.stdout.strip()), (2, ""), "stale manifest must refuse, no ids")
        self.assertEqual(self.run_tool("watercolour", "build").returncode, 0)
        self.assertEqual(self.status("watercolour")[pid]["status"], "pending_review")
        self.assertNotIn(pid, self.q("watercolour", 200))
        # an approved plant whose approval is withdrawn (awaiting_review) becomes pending_review, never missing
        ver = json.loads((self.r / "data/botanical-verification.json").read_text())
        victim = "geranium-rozanne"
        ver["plants"][victim]["watercolour"].pop("approvedAt")
        ver["plants"][victim]["watercolour"]["status"] = "awaiting_review"
        (self.r / "data/botanical-verification.json").write_text(json.dumps(ver, indent=2) + "\n")
        self.run_tool("watercolour", "build")
        self.assertEqual(self.status("watercolour")[victim]["status"], "pending_review")
        self.assertNotIn(victim, self.q("watercolour", 200))

    def test_E_generated_but_unimported_is_protected(self):  # E
        first = self.q("watercolour", 10)
        r = self.run_tool("watercolour", "reserve", *first, "--batch", "WC-ZIP-A", "--source", "a.zip", "--today", TODAY)
        self.assertEqual(r.returncode, 0, r.stderr)
        again = self.q("watercolour", 10)
        self.assertFalse(set(again) & set(first))
        self.assertNotIn(first[0], self.q("watercolour", 200))
        st = self.status("watercolour")
        self.assertTrue(all(st[i]["status"] == "pending_review" and st[i]["assetForm"] == "none" for i in first))
        over = self.run_tool("watercolour", "reserve", first[0], "--batch", "WC-ZIP-B", "--today", TODAY)
        self.assertNotEqual(over.returncode, 0, "a reserved plant cannot be reserved again")
        expired = self.run_tool("watercolour", "queue", "10", "--today", "2026-12-31")
        self.assertEqual((expired.returncode, expired.stdout.strip()), (2, ""), "expired reservation blocks the queue")
        self.run_tool("watercolour", "release", "--batch", "WC-ZIP-A")
        self.assertEqual(self.q("watercolour", 10), first, "release restores the queue exactly")

    def test_F_deterministic_catalogue_order(self):  # F
        a, b = self.q("watercolour", 34), self.q("watercolour", 34)
        self.assertEqual(a, b)
        self.assertEqual(a, sorted(a, key=self.cat.index))
        self.assertEqual(self.q("watercolour", 10), a[:10])
        self.assertEqual(self.q("watercolour", 10, "--skip", "10"), a[10:20])

    def test_G_filenames_use_exact_catalogue_ids(self):  # G
        out = self.run_tool("watercolour", "queue", "10", "--detail", "--today", TODAY)
        self.assertEqual(out.returncode, 0, out.stderr)
        rows = json.loads(out.stdout)
        cat = {p["id"]: p for p in json.loads((self.r / "data/plants.json").read_text())["plants"]}
        for row in rows:
            pid = row["plantId"]
            self.assertIn(pid, cat)
            self.assertEqual(row["pngFilename"], f"{pid}-watercolour.png")
            self.assertEqual(row["webpFilename"], f"{pid}-watercolour.webp")
            self.assertEqual(row["pngMasterPath"], f"assets/plant-watercolours/masters/{pid}-watercolour.png")
            self.assertEqual((row["heightCm"], row["spreadCm"]), (cat[pid]["heightCm"], cat[pid]["spreadCm"]))
            self.assertEqual(row["illustrationType"], "watercolour")
            self.assertEqual(row["brief"]["file"], "docs/briefs/WATERCOLOUR_B_ASSET_BRIEF.md")
            self.assertEqual(row["referenceImage"]["file"], "docs/references/nepeta-watercolour-very-wet-approved.png")
            self.assertEqual(row["status"], "missing")
        bot = json.loads(self.run_tool("botanical", "queue", "3", "--detail", "--today", TODAY).stdout)
        self.assertTrue(all(b["pngFilename"] == b["plantId"] + ".png" and b["illustrationType"] == "botanical" for b in bot))

    def test_H_statuses_are_independent(self):  # H
        bot_before, wc_before = sha(self.manifest("botanical")), sha(self.manifest("watercolour"))
        # botanical reservation leaves the watercolour manifest and queue alone
        ids = self.q(None, 3)
        self.assertEqual(self.run_tool(None, "reserve", *ids, "--batch", "BOT-A", "--today", TODAY).returncode, 0)
        self.assertEqual(sha(self.manifest("watercolour")), wc_before)
        self.assertEqual(self.run_tool("watercolour", "check", "--today", TODAY).returncode, 0)
        self.assertTrue(set(ids) <= set(self.q("watercolour", 200)), "a botanical reservation must not hide a missing watercolour")
        self.run_tool(None, "release", "--batch", "BOT-A")
        self.assertEqual(sha(self.manifest("botanical")), bot_before)
        # a watercolour reservation leaves botanical alone
        wc = self.q("watercolour", 2)
        self.run_tool("watercolour", "reserve", *wc, "--batch", "WC-A", "--today", TODAY)
        self.assertEqual(sha(self.manifest("botanical")), bot_before)
        self.assertEqual(self.q(None, 10), BOT_FIRST_10)
        # approved botanical (explicit approval) does not imply an approved watercolour, and vice versa
        pid = next(i for i in self.cat if i not in self.wc_files() and i not in wc)
        (self.r / f"assets/plant-watercolours/{pid}.webp").write_bytes(b"RIFFWEBPbot")  # botanical file appears
        self.assertEqual(self.run_tool("watercolour", "check", "--today", TODAY).returncode, 0)
        self.assertIn(pid, self.q("watercolour", 200), "a botanical image must not make a watercolour 'present'")
        # a watercolour-only file does not leave the plant botanical-complete
        other = next(i for i in self.cat if i not in self.wc_files() and i not in wc and i != pid)
        (self.r / f"assets/plant-watercolours/{other}-watercolour.webp").write_bytes(b"RIFFWEBPwc")
        self.run_tool("watercolour", "build")
        self.assertNotIn(other, self.q("watercolour", 200))
        self.assertEqual(self.status("botanical")[other]["status"], "missing", "watercolour file is not a botanical asset")
        self.assertEqual(self.run_tool(None, "check", "--today", TODAY).returncode, 1, "botanical check sees the stray files; no silent merge")

    def test_I_batch_size_respected(self):  # I
        for n in (0, 1, 7, 10, 34):
            self.assertEqual(len(self.q("watercolour", n)), n)
        self.assertEqual(len(self.q("watercolour", 50)), 34)
        self.assertEqual(self.q("watercolour", 10, "--skip", "30"), self.q("watercolour", 34)[30:])
        self.assertEqual(len(set(self.q("watercolour", 50))), 34, "no duplicates / padding")
        # fewer than requested when fewer remain
        self.run_tool("watercolour", "reserve", *self.q("watercolour", 30), "--batch", "WC-30", "--today", TODAY)
        self.assertEqual(len(self.q("watercolour", 10)), 4)

    def test_J_rerun_without_status_change_never_reallocates(self):  # J
        first = self.q("watercolour", 10)
        self.assertEqual(self.q("watercolour", 10), first, "same ids until a status change is recorded")
        self.run_tool("watercolour", "reserve", *first, "--batch", "WC-J", "--today", TODAY)
        second = self.q("watercolour", 10)
        self.assertFalse(set(first) & set(second))
        self.assertEqual(self.q("watercolour", 10), second)
        self.assertEqual(self.run_tool("watercolour", "reserve", *first, "--batch", "WC-J2", "--today", TODAY).returncode, 1)

    def test_catalogue_growth_blocks_stale_queue(self):
        d = json.loads((self.r / "data/plants.json").read_text())
        d["plants"].append({**d["plants"][0], "id": "zz-new-plant"})
        (self.r / "data/plants.json").write_text(json.dumps(d))
        out = self.run_tool("watercolour", "queue", "10", "--today", TODAY)
        self.assertEqual((out.returncode, out.stdout.strip()), (2, ""))
        self.assertIn("zz-new-plant", out.stderr)


if __name__ == "__main__":
    unittest.main(verbosity=2)
