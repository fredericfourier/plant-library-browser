#!/usr/bin/env python3
"""Tests for the botanical/watercolour illustration status queue (tools/botanical_status.py).

Run: python3 tools/test_illustration_status.py

Three kinds of test, so normal repository changes (a batch gets imported, the catalogue grows) never cause false failures:
  * Fixture tests  - a synthetic catalogue, assets, border-designer repo and git remote built in a temp dir; all counts and IDs
                     are the fixture's own constants. Simulated reservations and imports run here.
  * Live tests     - invariants of the real repository data, derived from the files at run time (never hard-coded counts or IDs).
  * Frozen regression - the 51-check botanical script runs against a pinned baseline commit, see the review package notes;
                     it is deliberately not part of this file.
The real repository is never written.
"""
import hashlib, json, shutil, subprocess, tempfile, unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
TODAY = "2026-10-22"
A = "assets/plant-watercolours/"


def sha(data):
    return hashlib.sha256(data if isinstance(data, bytes) else Path(data).read_bytes()).hexdigest()


def run(cwd, *a):
    return subprocess.run(list(a), capture_output=True, text=True, cwd=cwd)


def git(cwd, *a):
    r = run(cwd, "git", "-c", "user.name=t", "-c", "user.email=t@t", *a)
    assert r.returncode == 0, (a, r.stderr)
    return r.stdout


class Tool:
    """Runs the repository's tools/botanical_status.py inside a given checkout."""

    def __init__(self, root, kind):
        self.root, self.kind = Path(root), kind

    def __call__(self, *args):
        pre = ["--type", self.kind] if self.kind else []
        return run(self.root, "python3", str(self.root / "tools/botanical_status.py"), *pre, *args)

    def q(self, n=10, *extra, today=TODAY):
        r = self("queue", str(n), "--json", "--today", today, *extra)
        assert r.returncode == 0, r.stderr
        return json.loads(r.stdout)

    def manifest(self):
        name = "watercolour" if self.kind == "watercolour" else "botanical"
        return json.loads((self.root / f"data/{name}-status.json").read_text())

    def status(self):
        return {p["plantId"]: p for p in self.manifest()["plants"]}

    def mpath(self):
        return self.root / f"data/{'watercolour' if self.kind == 'watercolour' else 'botanical'}-status.json"


class Fixture:
    """Synthetic project: 8 plants with assets in assorted states + 24 with none, a border-designer repo, a bare remote."""
    APPROVED_BOTH = ["e01", "e02", "e03", "e04"]
    MISSING = [f"m{n:02d}" for n in range(1, 25)]
    # e05 botanical filename-match only (wc approved) | e06 wc awaiting_review | e07 botanical only | e08 watercolour only
    EXISTING = APPROVED_BOTH + ["e05", "e06", "e07", "e08"]

    def __init__(self, tmp):
        self.tmp = Path(tmp)
        self.plb, self.bd, self.origin = self.tmp / "plb", self.tmp / "bd", self.tmp / "origin.git"
        self.ids = self.EXISTING + self.MISSING  # catalogue order: existing first, then the 24 additions
        for d in ("data", "tools", "docs"):
            (self.plb / d).mkdir(parents=True, exist_ok=True)
        for f in (REPO / "tools").glob("*.py"):
            shutil.copy(f, self.plb / "tools" / f.name)
        (self.plb / A).mkdir(parents=True)
        (self.plb / "data/plants.json").write_text(json.dumps({"plants": [
            {"id": i, "botanicalName": f"Plantus {i}", "commonName": f"plant {i}", "heightCm": 40 + n * 5, "spreadCm": 30 + n * 3}
            for n, i in enumerate(self.ids)]}))
        (self.plb / "data/additions.json").write_text(json.dumps({"batches": [{"date": "2026-10-01", "plantIds": self.ids}]}))
        (self.plb / "data/botanical-verification.json").write_text(json.dumps({"schemaVersion": 1, "plants": {}}))
        (self.plb / A / "manifest.json").write_text(json.dumps({"schemaVersion": 1, "assets": {}}))
        (self.bd / "docs/briefs").mkdir(parents=True)
        (self.bd / "docs/references").mkdir(parents=True)
        (self.bd / A / "masters").mkdir(parents=True)
        (self.bd / "docs/briefs/BOTANICAL_ASSET_BRIEF.md").write_text("botanical brief")
        (self.bd / "docs/briefs/WATERCOLOUR_B_ASSET_BRIEF.md").write_text("watercolour brief")
        (self.bd / "docs/references/nepeta-watercolour-very-wet-approved.png").write_bytes(b"refpng")
        git(self.bd, "init", "-q", "-b", "main")
        for i in self.APPROVED_BOTH:
            self.add("botanical", i, approved=True)
            self.add("watercolour", i, approved=True)
        self.add("botanical", "e05", approved=False, confirmed=True)  # filename match only
        self.add("watercolour", "e05", approved=True)
        self.add("botanical", "e06", approved=True)
        self.add("watercolour", "e06", approved=False)
        self.add("botanical", "e07", approved=True)
        self.add("watercolour", "e08", approved=True)
        self.commit_bd()
        git(self.tmp, "init", "-q", "--bare", "-b", "main", str(self.origin))
        git(self.plb, "init", "-q", "-b", "main")
        git(self.plb, "remote", "add", "origin", str(self.origin))
        self.build()
        git(self.plb, "add", "-A")
        git(self.plb, "commit", "-q", "-m", "fixture baseline")
        git(self.plb, "push", "-q", "-u", "origin", "main")

    def add(self, kind, pid, approved, confirmed=None):
        """Simulate importing one image: WebP in the public repo, PNG master in the private repo, verification + asset manifest records."""
        sfx = "-watercolour" if kind == "watercolour" else ""
        webp, png = b"RIFFWEBP" + (pid + kind).encode(), b"PNG" + (pid + kind).encode()
        (self.plb / A / f"{pid}{sfx}.webp").write_bytes(webp)
        (self.bd / A / "masters" / f"{pid}{sfx}.png").write_bytes(png)
        vp, mp = self.plb / "data/botanical-verification.json", self.plb / A / "manifest.json"
        ver, man = json.loads(vp.read_text()), json.loads(mp.read_text())
        rec = {"imageSha256": sha(webp), "pngSha256": sha(png), "importedAt": "2026-10-15T00:00:00Z"}
        if approved:
            rec["approvedAt"] = "2026-10-16T00:00:00Z"
        status = "confirmed" if (approved or confirmed) else ("awaiting_review" if kind == "watercolour" else "pending_review")
        pr = ver["plants"].setdefault(pid, {})
        asset = man["assets"].setdefault(pid, {})
        if kind == "watercolour":
            pr["watercolour"] = {"status": status, **rec}
            asset.setdefault("variants", {})["watercolour"] = {"file": f"{A}{pid}-watercolour.webp", "status": "awaiting_review", "sha256": sha(webp)}
        else:
            pr.update({"status": status, "bundleMatchStatus": "filename_match_unreviewed", **rec})
            asset.update({"file": f"{A}{pid}.webp", "status": "ready", "sha256": sha(webp)})
        vp.write_text(json.dumps(ver, indent=2) + "\n")
        mp.write_text(json.dumps(man, indent=2) + "\n")

    def commit_bd(self):
        git(self.bd, "add", "-A")
        git(self.bd, "commit", "-q", "--allow-empty", "-m", "bd")

    def build(self):
        for k in ("botanical", "watercolour"):
            r = Tool(self.plb, k)("build", "--bd", str(self.bd), "--bd-ref", "HEAD")
            assert r.returncode == 0, r.stderr

    def tool(self, kind):
        return Tool(self.plb, kind)

    def commit_push(self, msg="status"):
        git(self.plb, "add", "-A")
        git(self.plb, "commit", "-q", "--allow-empty", "-m", msg)
        git(self.plb, "push", "-q")

    def import_batch(self, ids, approve=False):
        """The whole post-delivery step: images land in both repos, the manifest is rebuilt from border-designer, committed and pushed."""
        for i in ids:
            self.add("watercolour", i, approved=approve)
        self.commit_bd()
        self.build()
        self.commit_push("import " + ",".join(ids[:2]))


class FixtureCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, True)
        self.fx = Fixture(tmp)
        self.wc, self.bot = self.fx.tool("watercolour"), self.fx.tool(None)
        self.wc_missing = [i for i in self.fx.ids if i not in {"e01", "e02", "e03", "e04", "e05", "e06", "e08"}]  # e07 has no watercolour
        self.bot_missing = [i for i in self.fx.ids if i not in {"e01", "e02", "e03", "e04", "e05", "e06", "e07"}]  # e08 has no botanical


class QueueSelection(FixtureCase):
    def test_A_botanical_baseline(self):  # A
        self.assertEqual(self.bot("check", "--today", TODAY).returncode, 0)
        self.assertEqual(self.bot.q(200), self.bot_missing)
        self.assertEqual(self.bot.q(10), self.bot_missing[:10])
        s = self.bot.manifest()["summary"]
        self.assertEqual((s["approved"], s["pending_review"], s["missing"]), (6, 1, len(self.bot_missing)))  # e01-e04, e06, e07 | e05
        self.assertEqual(self.bot.status()["e05"]["approvalBasis"], "filename_match_only")
        self.assertEqual(self.bot.status()["e05"]["status"], "pending_review")
        self.assertNotIn("e05", self.bot.q(200))
        before = self.bot.mpath().read_bytes()
        self.assertEqual(self.bot("build").returncode, 0)  # rebuild without --bd keeps recorded master fields: byte-identical
        self.assertEqual(self.bot.mpath().read_bytes(), before)

    def test_B_C_queue_is_exactly_the_plants_without_watercolour_and_never_existing(self):  # B, C
        got = self.wc.q(200)
        self.assertEqual(got, self.wc_missing)
        self.assertFalse(set(got) & {"e01", "e02", "e03", "e04", "e05", "e06", "e08"})
        self.assertEqual(self.wc("check", "--today", TODAY).returncode, 0)

    def test_D_pending_review_and_half_imports_never_selected(self):  # D
        st = self.wc.status()
        self.assertEqual((st["e06"]["status"], st["e01"]["status"]), ("pending_review", "approved"))
        pid = self.fx.MISSING[0]
        (self.fx.plb / A / f"{pid}-watercolour.webp").write_bytes(b"RIFFWEBPx")
        stale = self.wc("queue", "5", "--today", TODAY)
        self.assertEqual((stale.returncode, stale.stdout.strip()), (2, ""))
        self.wc("build")
        self.assertEqual(self.wc.status()[pid]["status"], "pending_review")
        self.assertNotIn(pid, self.wc.q(200))
        ver = json.loads((self.fx.plb / "data/botanical-verification.json").read_text())  # withdrawn approval -> pending_review, never missing
        ver["plants"]["e01"]["watercolour"].pop("approvedAt")
        ver["plants"]["e01"]["watercolour"]["status"] = "awaiting_review"
        (self.fx.plb / "data/botanical-verification.json").write_text(json.dumps(ver, indent=2) + "\n")
        self.wc("build")
        self.assertEqual(self.wc.status()["e01"]["status"], "pending_review")
        self.assertNotIn("e01", self.wc.q(200))

    def test_E_reservation_protects_and_expires_safely(self):  # E
        first = self.wc.q(10)
        r = self.wc("reserve", *first, "--batch", "WC-ZIP-A", "--source", "a.zip", "--today", TODAY)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertFalse(set(self.wc.q(10)) & set(first))
        st = self.wc.status()
        self.assertTrue(all(st[i]["status"] == "pending_review" and st[i]["assetForm"] == "none" for i in first))
        self.assertNotEqual(self.wc("reserve", first[0], "--batch", "B2", "--today", TODAY).returncode, 0)
        late = self.wc("queue", "10", "--today", "2026-12-31")
        self.assertEqual((late.returncode, late.stdout.strip()), (2, ""))
        self.assertEqual(self.wc("check", "--today", "2026-12-31").returncode, 1)
        self.assertEqual(self.wc("renew", "--batch", "WC-ZIP-A", "--today", "2026-12-31").returncode, 0)
        self.assertEqual(self.wc("check", "--today", "2026-12-31").returncode, 0)
        self.wc("release", "--batch", "WC-ZIP-A")
        self.assertEqual(self.wc.q(10), first, "release restores the queue exactly")

    def test_F_deterministic_catalogue_order(self):  # F
        a = self.wc.q(200)
        self.assertEqual(a, self.wc.q(200))
        self.assertEqual(a, sorted(a, key=self.fx.ids.index))
        self.assertEqual(self.wc.q(10, "--skip", "10"), a[10:20])

    def test_G_filenames_use_exact_catalogue_ids(self):  # G
        out = self.wc("queue", "10", "--detail", "--today", TODAY)
        self.assertEqual(out.returncode, 0, out.stderr)
        cat = {p["id"]: p for p in json.loads((self.fx.plb / "data/plants.json").read_text())["plants"]}
        for row in json.loads(out.stdout):
            pid = row["plantId"]
            self.assertIn(pid, cat)
            self.assertEqual(row["pngFilename"], f"{pid}-watercolour.png")
            self.assertEqual(row["webpFilename"], f"{pid}-watercolour.webp")
            self.assertEqual(row["pngMasterPath"], f"{A}masters/{pid}-watercolour.png")
            self.assertEqual((row["heightCm"], row["spreadCm"]), (cat[pid]["heightCm"], cat[pid]["spreadCm"]))
            self.assertEqual((row["illustrationType"], row["status"]), ("watercolour", "missing"))
            self.assertEqual(row["brief"]["file"], "docs/briefs/WATERCOLOUR_B_ASSET_BRIEF.md")
            self.assertEqual(row["referenceImage"]["file"], "docs/references/nepeta-watercolour-very-wet-approved.png")
            self.assertEqual(row["referenceImage"]["sha256"], sha(b"refpng"))
        bot = json.loads(self.bot("queue", "3", "--detail", "--today", TODAY).stdout)
        self.assertTrue(all(b["pngFilename"] == b["plantId"] + ".png" and b["illustrationType"] == "botanical" for b in bot))

    def test_H_statuses_are_independent(self):  # H
        bot0, wc0 = self.bot.mpath().read_bytes(), self.wc.mpath().read_bytes()
        self.assertEqual(self.wc.status()["e07"]["status"], "missing")  # approved botanical, no watercolour
        self.assertEqual(self.bot.status()["e07"]["status"], "approved")
        self.assertEqual(self.bot.status()["e08"]["status"], "missing")  # approved watercolour, no botanical
        self.assertEqual(self.wc.status()["e08"]["status"], "approved")
        self.assertEqual(self.bot("check", "--today", TODAY).returncode, 0, "watercolour-only record must not break botanical build/check")
        self.assertIn("e07", self.wc.q(200))
        self.assertIn("e08", self.bot.q(200))
        ids = [i for i in self.bot.q(200) if i != "e08"][:3]  # e08 is botanical-missing but watercolour-approved
        self.assertEqual(self.bot("reserve", *ids, "--batch", "BOT-A", "--today", TODAY).returncode, 0)
        self.assertEqual(self.wc.mpath().read_bytes(), wc0)
        self.assertTrue(set(ids) <= set(self.wc.q(200)))
        self.bot("release", "--batch", "BOT-A")
        self.assertEqual(self.bot.mpath().read_bytes(), bot0)
        wcs = self.wc.q(2)
        self.wc("reserve", *wcs, "--batch", "WC-A", "--today", TODAY)
        self.assertEqual(self.bot.mpath().read_bytes(), bot0)
        self.assertEqual(self.bot.q(200), self.bot_missing)
        # a botanical file appearing does not make a watercolour present
        pid = self.fx.MISSING[5]
        (self.fx.plb / A / f"{pid}.webp").write_bytes(b"RIFFWEBPbot")
        self.assertEqual(self.wc("check", "--today", TODAY).returncode, 0)
        self.assertIn(pid, self.wc.q(200))
        self.assertEqual(self.bot("check", "--today", TODAY).returncode, 1)

    def test_I_batch_sizes(self):  # I
        total = len(self.wc_missing)
        for n in (0, 1, 7, 10, total, total + 20):
            self.assertEqual(len(self.wc.q(n)), min(n, total))
        self.assertEqual(self.wc.q(10, "--skip", str(total - 4)), self.wc_missing[-4:])
        self.assertEqual(len(set(self.wc.q(total + 20))), total, "never padded with duplicates")
        self.wc("reserve", *self.wc.q(total - 4), "--batch", "WC-ALL", "--today", TODAY)
        self.assertEqual(len(self.wc.q(10)), 4, "fewer than requested when fewer remain")

    def test_J_rerun_without_change_is_idempotent(self):  # J
        first = self.wc.q(10)
        self.assertEqual(self.wc.q(10), first)
        self.wc("reserve", *first, "--batch", "WC-J", "--today", TODAY)
        second = self.wc.q(10)
        self.assertFalse(set(first) & set(second))
        self.assertEqual(self.wc.q(10), second)
        self.assertEqual(self.wc("reserve", *first, "--batch", "WC-J2", "--today", TODAY).returncode, 1)

    def test_catalogue_growth_blocks_stale_queue(self):
        p = self.fx.plb / "data/plants.json"
        d = json.loads(p.read_text())
        d["plants"].append({**d["plants"][0], "id": "zz-new-plant"})
        p.write_text(json.dumps(d))
        out = self.wc("queue", "10", "--today", TODAY)
        self.assertEqual((out.returncode, out.stdout.strip()), (2, ""))
        self.assertIn("zz-new-plant", out.stderr)


class Lifecycle(FixtureCase):
    """Whole cycle: queue -> generate -> deliver -> reserve -> commit -> next queue -> import -> rebuild."""

    def flags(self):
        return ["--bd", str(self.fx.bd), "--bd-ref", "HEAD", "--require-synced", "--today", TODAY]

    def test_batches_reserve_import_and_never_requeue(self):
        total = len(self.wc_missing)
        a = self.wc("queue", "10", "--json", *self.flags())
        self.assertEqual(a.returncode, 0, a.stderr)
        batch_a = json.loads(a.stdout)
        self.assertEqual(batch_a, self.wc_missing[:10])
        # generate + deliver happen outside the repo; then reserve (uncommitted) ...
        self.assertEqual(self.wc("reserve", *batch_a, "--batch", "ZIP-A", "--source", "a.zip", "--today", TODAY).returncode, 0)
        # ... an uncommitted reservation cannot be presented as synchronised
        blocked = self.wc("queue", "10", "--json", *self.flags())
        self.assertEqual((blocked.returncode, blocked.stdout.strip()), (2, ""))
        self.assertIn("uncommitted", blocked.stderr)
        self.assertEqual(self.wc("sync").returncode, 3)
        git(self.fx.plb, "add", "-A"); git(self.fx.plb, "commit", "-q", "-m", "reserve ZIP-A")  # committed but not pushed
        self.assertEqual(self.wc("sync").returncode, 3)
        self.assertIn("not pushed", self.wc("sync").stderr)
        git(self.fx.plb, "push", "-q")
        self.assertEqual(self.wc("sync").returncode, 0)
        nxt = json.loads(self.wc("queue", "10", "--json", *self.flags()).stdout)
        self.assertFalse(set(nxt) & set(batch_a))
        self.assertEqual(nxt, self.wc_missing[10:20])
        # import the 10 delivered images into the fixture and rebuild
        self.fx.import_batch(batch_a)
        st = self.wc.status()
        self.assertTrue(all(st[i]["status"] == "pending_review" and "reservation" not in st[i] and st[i]["assetForm"] == "both" for i in batch_a))
        self.assertEqual(self.wc("check", "--today", TODAY).returncode, 0)
        remaining = self.wc.q(200)
        self.assertEqual(len(remaining), total - 10)
        self.assertEqual(remaining, self.wc_missing[10:])
        self.assertEqual(self.wc.manifest()["summary"]["missing"], total - 10)
        # approving later never re-queues either; neither does a second rebuild
        self.fx.import_batch(self.wc_missing[10:20], approve=True)
        self.assertFalse(set(self.wc.q(200)) & set(batch_a + self.wc_missing[10:20]))
        self.assertEqual(self.wc.q(10), self.wc_missing[20:])
        self.assertEqual(self.wc("build", "--bd", str(self.fx.bd), "--bd-ref", "HEAD").returncode, 0)
        self.assertEqual(self.wc.q(200), self.wc_missing[20:])
        # fewer than the batch size remain, then none
        last = self.wc.q(10)
        self.fx.import_batch(last)
        self.assertEqual(self.wc.q(10), [])
        # the botanical queue was untouched by all of it
        self.assertEqual(self.bot.q(200), self.bot_missing)
        self.assertEqual(self.bot("check", "--today", TODAY).returncode, 0)

    def test_other_session_behind_upstream_is_stopped(self):
        s2 = self.fx.tmp / "session2"
        git(self.fx.tmp, "clone", "-q", str(self.fx.origin), str(s2))
        ids = self.wc.q(10)
        self.wc("reserve", *ids, "--batch", "ZIP-A", "--today", TODAY)
        self.fx.commit_push("reserve ZIP-A")
        other = Tool(s2, "watercolour")
        git(s2, "fetch", "-q")  # session 2 knows about the push but has not merged it
        stale = other("queue", "10", "--json", "--require-synced", "--today", TODAY)
        self.assertEqual((stale.returncode, stale.stdout.strip()), (2, ""))
        self.assertIn("upstream has newer changes", stale.stderr)
        self.assertTrue(set(other.q(10)) & set(ids), "without the sync gate the old clone would hand out reserved IDs")
        git(s2, "pull", "-q", "--ff-only")
        fresh = json.loads(other("queue", "10", "--json", "--require-synced", "--today", TODAY).stdout)
        self.assertFalse(set(fresh) & set(ids))

    def test_png_master_refresh_gate(self):
        pid = self.fx.MISSING[3]
        self.fx.commit_bd()
        (self.fx.bd / A / "masters" / f"{pid}-watercolour.png").write_bytes(b"PNGnew")  # master appears in border-designer only
        self.fx.commit_bd()
        plain = self.wc("queue", "30", "--json", "--today", TODAY)
        self.assertIn(pid, json.loads(plain.stdout), "without --bd the private repo cannot be seen: documented limitation")
        gated = self.wc("queue", "30", "--json", "--bd", str(self.fx.bd), "--bd-ref", "HEAD", "--today", TODAY)
        self.assertEqual((gated.returncode, gated.stdout.strip()), (2, ""))
        self.assertIn(pid, gated.stderr)
        self.assertIn("build --bd", gated.stderr)
        self.wc("build", "--bd", str(self.fx.bd), "--bd-ref", "HEAD")
        self.assertEqual(self.wc.status()[pid]["status"], "pending_review")
        ok = self.wc("queue", "30", "--json", "--bd", str(self.fx.bd), "--bd-ref", "HEAD", "--today", TODAY)
        self.assertEqual(ok.returncode, 0, ok.stderr)
        self.assertNotIn(pid, json.loads(ok.stdout))
        # a border-designer commit that changes nothing relevant does not block the queue
        self.fx.commit_bd()
        self.assertEqual(self.wc("queue", "3", "--bd", str(self.fx.bd), "--bd-ref", "HEAD", "--today", TODAY).returncode, 0)


class LiveRepository(unittest.TestCase):
    """Invariants of the real data, computed from the files at run time: valid before and after any batch import."""

    def setUp(self):
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, True)
        self.r = Path(tmp) / "r"
        self.r.mkdir()
        for d in ("data", "tools", "docs"):
            shutil.copytree(REPO / d, self.r / d)
        (self.r / "assets").mkdir()
        shutil.copytree(REPO / A, self.r / A)
        self.cat = [p["id"] for p in json.loads((self.r / "data/plants.json").read_text())["plants"]]
        self.files = {f.name for f in (self.r / A).glob("*.webp")}

    def test_manifests_consistent_with_files(self):
        for kind in (None, "watercolour"):
            t = Tool(self.r, kind)
            self.assertEqual(t("check", "--today", TODAY).returncode, 0, t("check", "--today", TODAY).stderr)
            self.assertEqual([p["plantId"] for p in t.manifest()["plants"]], self.cat)

    def test_queues_equal_plants_without_files(self):
        for kind, sfx in ((None, ".webp"), ("watercolour", "-watercolour.webp")):
            t = Tool(self.r, kind)
            expected = [i for i in self.cat if f"{i}{sfx}" not in self.files and t.status()[i]["status"] == "missing"]
            self.assertEqual(t.q(len(self.cat) + 5), expected)
            self.assertTrue(all(f"{i}{sfx}" not in self.files for i in expected))
            self.assertEqual(t.q(10), expected[:10])
            s = t.manifest()["summary"]
            self.assertEqual(s["missing"], len(expected))
            self.assertEqual(sum(s[k] for k in ("missing", "pending_review", "approved", "rejected", "uncertain_match")), len(self.cat))

    def test_default_type_is_botanical_and_rebuild_is_stable(self):
        self.assertEqual(Tool(self.r, None).q(200), Tool(self.r, "botanical").q(200))
        for kind in (None, "watercolour"):
            t = Tool(self.r, kind)
            before = t.mpath().read_bytes()
            self.assertEqual(t("build").returncode, 0)
            self.assertEqual(t.mpath().read_bytes(), before)


if __name__ == "__main__":
    unittest.main(verbosity=2)
