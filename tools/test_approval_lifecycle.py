#!/usr/bin/env python3
"""Approval-lifecycle regression: an owner approval belongs to the exact published WebP bytes.

Proves, for BOTH illustration types, that a status rebuild, catalogue export, asset-manifest sync, missing/stale/absent PNG masters or a CI run
cannot revoke an approval for unchanged bytes, that changed WebP bytes are never approved until a new approval is recorded, and that a future
plant follows the same lifecycle. Sandboxes symlink the real WebPs; nothing in the repository is modified. Run: python3 tools/test_approval_lifecycle.py
"""
import functools, hashlib, http.server, json, os, shutil, subprocess, sys, tempfile, threading, unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
A = "assets/plant-watercolours"
ENV = dict(os.environ, GIT_CONFIG_GLOBAL="/dev/null", GIT_CONFIG_SYSTEM="/dev/null", GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@e.invalid",
           GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@e.invalid")
SFX = {"botanical": "", "watercolour": "-watercolour"}


def sh(cwd, *a, check=False):
    r = subprocess.run(a, cwd=cwd, env=ENV, text=True, capture_output=True)
    if check and r.returncode:
        raise AssertionError(f"{a}: {r.stderr}")
    return r


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


class Sandbox(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.r = self.tmp / "plb"
        (self.r / A).mkdir(parents=True)
        for d in ("data", "tools"):
            shutil.copytree(REPO / d, self.r / d, ignore=shutil.ignore_patterns("__pycache__"))
        for f in (REPO / A).iterdir():
            (self.r / A / f.name).symlink_to(f) if f.suffix == ".webp" else shutil.copy(f, self.r / A / f.name)
        sh(self.r, "git", "init", "-q", check=True); sh(self.r, "git", "add", "-A"); sh(self.r, "git", "commit", "-qm", "base", check=True)

    def js(self, rel):
        return json.loads((self.r / rel).read_text())

    def save(self, rel, d):
        (self.r / rel).write_text(json.dumps(d, indent=2) + "\n")

    def status(self, kind, *a):
        pre = ["--type", kind]
        return sh(self.r, sys.executable, "tools/botanical_status.py", *pre, *a)

    def rebuild(self, kind, *a):
        r = self.status(kind, "build", *a)
        self.assertEqual(r.returncode, 0, r.stderr)
        return {p["plantId"]: p for p in self.js(f"data/{kind}-status.json" if kind == "watercolour" else "data/botanical-status.json")["plants"]}

    def ledger(self, *a):
        return sh(self.r, sys.executable, "tools/approval_ledger.py", *a)


class RealData(Sandbox):
    def test_all_explicit_approvals_are_permanent_and_manifests_fresh(self):
        for kind in ("botanical", "watercolour"):
            m = self.rebuild(kind)
            self.assertEqual(len(m), 108)
            self.assertEqual({p["status"] for p in m.values()}, {"approved"}, kind)
            self.assertTrue(all(p["visualApproval"]["approvedImageSha256"] == p["webpSha256"] for p in m.values()))
            self.assertEqual(self.status(kind, "check").returncode, 0, self.status(kind, "check").stderr)
        self.assertEqual(self.ledger("check").returncode, 0)

    def test_committed_manifests_equal_a_rebuild(self):
        for kind, f in (("botanical", "botanical-status.json"), ("watercolour", "watercolour-status.json")):
            before = (self.r / "data" / f).read_text()
            self.rebuild(kind)
            self.assertEqual((self.r / "data" / f).read_text(), before, f"{f} is stale")

    def test_ledger_covers_every_current_approval_hash(self):
        led = self.js("data/approval-ledger.json")
        have = {(e["variant"], e["plantId"], e["imageSha256"]) for e in led["entries"]}
        for kind in SFX:
            for pid in self.js("data/plants.json") and [p["id"] for p in self.js("data/plants.json")["plants"]]:
                self.assertIn((kind, pid, sha(self.r / A / f"{pid}{SFX[kind]}.webp")), have, (kind, pid))


class Lifecycle(Sandbox):
    def each(self, fn):
        for kind in SFX:
            with self.subTest(kind=kind):
                fn(kind)

    def test_png_masters_never_decide_approval(self):
        def go(kind):
            bd = self.tmp / f"bd-{kind}"
            (bd / "assets/plant-watercolours/masters").mkdir(parents=True)
            (bd / "assets/plant-watercolours/masters" / f"acanthus-mollis{SFX[kind]}.png").write_bytes(b"not the recorded master")
            (bd / "docs/references").mkdir(parents=True); (bd / "docs/references/nepeta-watercolour-very-wet-approved.png").write_bytes(b"ref")
            sh(bd, "git", "init", "-q"); sh(bd, "git", "add", "-A"); sh(bd, "git", "commit", "-qm", "m")
            m = self.rebuild(kind, "--bd", str(bd), "--bd-ref", "HEAD")
            self.assertEqual({p["status"] for p in m.values()}, {"approved"})
            self.assertIn(m["acanthus-mollis"]["sourceIntegrity"]["state"], ("master_hash_mismatch", "master_stale"))
            self.assertEqual(m["achillea-moonshine"]["sourceIntegrity"]["state"], "master_not_registered")  # no master at all
            self.assertEqual(self.status(kind, "check").returncode, 0)
            self.assertEqual(self.rebuild(kind)["acanthus-mollis"]["status"], "approved")
        self.each(go)

    def test_status_rebuild_catalogue_export_and_asset_sync_cannot_revoke(self):
        def go(kind):
            cat = self.js("data/plants.json"); cat["plants"].reverse(); cat["updated"] = "2099-01-01"; cat["plants"][0]["extraField"] = 1
            self.save("data/plants.json", cat)                                   # catalogue export
            man = self.js(f"{A}/manifest.json"); man["updated"] = "2099-01-01"; self.save(f"{A}/manifest.json", man)   # asset sync
            m = self.rebuild(kind)
            self.assertEqual({p["status"] for p in m.values()}, {"approved"})
        self.each(go)

    def test_record_reset_cannot_revoke_but_ci_flags_it(self):
        def go(kind):
            v = self.js("data/botanical-verification.json")
            rec = v["plants"]["acanthus-mollis"]
            tgt = rec if kind == "botanical" else rec["watercolour"]
            tgt["status"] = "pending_review" if kind == "botanical" else "awaiting_review"
            tgt.pop("approvedAt")                                               # a buggy tool strips the approval from the record
            self.save("data/botanical-verification.json", v)
            self.assertEqual(self.rebuild(kind)["acanthus-mollis"]["status"], "approved", "ledger keeps the approval for unchanged bytes")
            r = self.ledger("check")
            self.assertNotEqual(r.returncode, 0)
            self.assertIn("acanthus-mollis", r.stderr)
            sh(self.r, "git", "checkout", "-q", "--", "data/botanical-verification.json")
        self.each(go)

    def test_changed_webp_bytes_need_a_new_approval_and_history_is_kept(self):
        def go(kind):
            f = self.r / A / f"acanthus-mollis{SFX[kind]}.webp"
            old = sha(f)
            data = f.read_bytes(); f.unlink(); f.write_bytes(data + b"\0")        # changed bytes (symlink replaced by a private copy)
            m = self.rebuild(kind)
            p = m["acanthus-mollis"]
            self.assertNotEqual(p["status"], "approved")
            self.assertEqual(p["visualApproval"]["state"], "approval_for_other_bytes")
            self.assertIsNone(p["manualApprovalAt"])
            self.assertEqual(self.status(kind, "queue", "5").returncode, 0)
            self.assertEqual(self.ledger("approve", kind, "acanthus-mollis").returncode, 0)
            led = self.js("data/approval-ledger.json")["entries"]
            self.assertTrue(any(e["imageSha256"] == old and e["plantId"] == "acanthus-mollis" and e["variant"] == kind for e in led), "old approval kept")
            new = [e for e in led if e["plantId"] == "acanthus-mollis" and e["variant"] == kind and e["imageSha256"] == sha(f)]
            self.assertEqual(len(new), 1)
            f.unlink(); f.symlink_to(REPO / A / f.name)
            self.assertEqual(self.rebuild(kind)["acanthus-mollis"]["status"], "approved", "the original approved bytes are still approved")
        self.each(go)

    def test_ledger_is_append_only_against_a_base_ref(self):
        led = self.js("data/approval-ledger.json")
        self.assertEqual(self.ledger("check", "--base", "HEAD").returncode, 0)
        e = led["entries"].pop(5); self.save("data/approval-ledger.json", led)
        r = self.ledger("check", "--base", "HEAD"); self.assertNotEqual(r.returncode, 0); self.assertIn("removed or altered", r.stderr)
        led["entries"].insert(5, {**e, "approvedAt": "2099-01-01T00:00:00Z"}); self.save("data/approval-ledger.json", led)
        self.assertNotEqual(self.ledger("check", "--base", "HEAD").returncode, 0)

    def test_future_plant_follows_the_same_lifecycle(self):
        def go(kind):
            cat = self.js("data/plants.json"); new = dict(cat["plants"][0]); new["id"] = "future-plant"; new["botanicalName"] = "Futurus plantus"
            cat["plants"].append(new); self.save("data/plants.json", cat)
            src = REPO / A / f"acanthus-mollis{SFX[kind]}.webp"
            (self.r / A / f"future-plant{SFX[kind]}.webp").write_bytes(src.read_bytes() + b"\1")
            man = self.js(f"{A}/manifest.json"); man["assets"]["future-plant"] = {"file": f"{A}/future-plant.webp"}; self.save(f"{A}/manifest.json", man)
            m = self.rebuild(kind)
            self.assertEqual(m["future-plant"]["status"], "pending_review")      # published but never approved by anyone
            self.assertEqual(m["future-plant"]["visualApproval"]["state"], "not_approved")
            self.assertEqual(self.ledger("approve", kind, "future-plant").returncode, 0)
            self.assertEqual(self.rebuild(kind)["future-plant"]["status"], "approved")
            self.assertEqual(self.rebuild(kind)["future-plant"]["sourceIntegrity"]["state"], "master_not_registered")
        self.each(go)

    def test_replacement_bytes_accepted_with_provenance_keep_one_authoritative_approval(self):
        """The owner's existing acceptance of replacement bytes (e.g. CP9.1 resolution correction) is recorded against the exact new hash."""
        f = self.r / A / "acanthus-mollis-watercolour.webp"
        old = sha(f)
        data = f.read_bytes(); f.unlink(); f.write_bytes(data + b"\2"); new = sha(f)
        v = self.js("data/botanical-verification.json")            # a CP9.1-style record: re-pinned to the new bytes, original approval named
        w = v["plants"]["acanthus-mollis"]["watercolour"]
        w["approvedOriginalImageSha256"], w["imageSha256"] = w["imageSha256"], new
        self.save("data/botanical-verification.json", v)
        self.assertNotEqual(self.rebuild("watercolour")["acanthus-mollis"]["status"], "approved")      # changed bytes: not approved yet
        self.assertNotEqual(self.ledger("sync").returncode, 1)
        self.assertEqual(len([e for e in self.js("data/approval-ledger.json")["entries"] if e["imageSha256"] == new]), 0, "sync never re-pins an approval")
        bad = self.ledger("accept", "watercolour", "acanthus-mollis", "--sha256", new, "--supersedes", "f" * 64, "--basis", "x", "--at", "2026-11-03T10:48:21Z")
        self.assertNotEqual(bad.returncode, 0)
        ok = self.ledger("accept", "watercolour", "acanthus-mollis", "--sha256", new, "--supersedes", old, "--basis", "owner confirmation", "--at", "2026-11-03T10:48:21Z")
        self.assertEqual(ok.returncode, 0, ok.stderr)
        p = self.rebuild("watercolour")["acanthus-mollis"]
        self.assertEqual((p["status"], p["manualApprovalAt"]), ("approved", "2026-11-03T10:48:21Z"))
        e = [e for e in self.js("data/approval-ledger.json")["entries"] if e["imageSha256"] == new][0]
        self.assertEqual((e["supersedesImageSha256"], e["supersededApprovedAt"]), (old, "2026-10-28T07:15:53Z"))   # honest provenance, the superseded approval timestamp is kept
        self.assertEqual(self.ledger("check", "--base", "HEAD").returncode, 0, self.ledger("check").stderr)

    def test_provenance_warnings_are_non_blocking(self):
        for kind in SFX:
            m = self.rebuild(kind)
            w = [p for p in m.values() if p["sourceIntegrity"]["state"] not in ("ok", "record_unpinned")]
            self.assertTrue(w, "the real data still has maintenance warnings")
            self.assertTrue(all(p["sourceIntegrity"]["blocking"] is False and p["status"] == "approved" for p in w))
            self.assertEqual(self.status(kind, "check").returncode, 0)

    def test_corrected_cp91_bytes_are_recorded_in_the_real_ledger(self):
        acc = [e for e in self.js("data/approval-ledger.json")["entries"] if e.get("supersedesImageSha256")]
        self.assertEqual(len(acc), 12)
        self.assertTrue(all(e["variant"] == "watercolour" and e["approvedAt"] == "2026-11-03T10:48:21Z" and "cmsg_" in e["basis"] for e in acc))

    def test_explicit_revocation_is_the_only_way_to_end_an_approval(self):
        r = self.ledger("revoke", "watercolour", "acanthus-mollis", "--reason", "owner asked")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.rebuild("watercolour")["acanthus-mollis"]["status"], "pending_review")
        self.assertEqual(self.rebuild("botanical")["acanthus-mollis"]["status"], "approved")


try:
    from playwright.sync_api import sync_playwright
except ImportError:  # pragma: no cover
    sync_playwright = None


class Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *a):
        pass


@unittest.skipIf(sync_playwright is None, "playwright not installed")
class BrowserLabels(unittest.TestCase):
    """The browser pins the approved look to bytes too: ledger-approved bytes show no label, changed bytes show it again."""

    def test_labels(self):
        tmp = Path(tempfile.mkdtemp()); self.addCleanup(shutil.rmtree, tmp, True)
        (tmp / A).mkdir(parents=True); (tmp / "data").mkdir()
        shutil.copy(REPO / "index.html", tmp / "index.html")
        ids = ["p-ok", "p-changed", "p-new", "p-reset"]
        (tmp / "data/plants.json").write_text(json.dumps({"schemaVersion": 1, "updated": "x", "plants": [
            {"id": i, "botanicalName": f"Plantus {i}", "commonName": i, "type": "perennial", "heightCm": 60, "spreadCm": 40, "light": ["full_sun"], "description": "d"} for i in ids]}))
        (tmp / "data/additions.json").write_text(json.dumps({"batches": []}))
        h = {i: hashlib.sha256(i.encode()).hexdigest() for i in ids}
        assets, ver = {}, {}
        for i in ids:
            (tmp / A / f"{i}-watercolour.webp").write_bytes(b"x")
            assets[i] = {"variants": {"watercolour": {"label": "Watercolour", "file": f"{A}/{i}-watercolour.webp", "sha256": h[i]}}}
        ver["p-ok"] = {"watercolour": {"status": "confirmed", "imageSha256": h["p-ok"], "approvedAt": "t"}}
        ver["p-changed"] = {"watercolour": {"status": "confirmed", "imageSha256": "0" * 64, "approvedAt": "t"}}      # approved OTHER bytes
        ver["p-new"] = {"watercolour": {"status": "awaiting_review", "imageSha256": h["p-new"]}}
        ver["p-reset"] = {"watercolour": {"status": "awaiting_review", "imageSha256": h["p-reset"]}}                  # record reset, ledger still approves
        (tmp / A / "manifest.json").write_text(json.dumps({"schemaVersion": 1, "updated": "x", "assets": assets}))
        (tmp / "data/botanical-verification.json").write_text(json.dumps({"plants": ver}))
        (tmp / "data/approval-ledger.json").write_text(json.dumps({"entries": [
            {"variant": "watercolour", "plantId": "p-ok", "imageSha256": h["p-ok"], "approvedAt": "t"},
            {"variant": "watercolour", "plantId": "p-reset", "imageSha256": h["p-reset"], "approvedAt": "t"},
            {"variant": "watercolour", "plantId": "p-changed", "imageSha256": "0" * 64, "approvedAt": "t"}], "revocations": []}))
        srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(Quiet, directory=str(tmp)))
        threading.Thread(target=srv.serve_forever, daemon=True).start(); self.addCleanup(srv.shutdown)
        with sync_playwright() as pw:
            exe = next((str(c) for c in sorted(Path("/opt/pw-browsers").glob("chromium-*/chrome-linux/chrome"))), None)
            try:
                b = pw.chromium.launch(executable_path=exe) if exe else pw.chromium.launch()
            except Exception as e:  # pragma: no cover
                self.skipTest(f"chromium unavailable: {e}")
            pg = b.new_page(); pg.goto(f"http://127.0.0.1:{srv.server_address[1]}/index.html"); pg.wait_for_selector(".card")
            pg.select_option("#variant", "watercolour"); pg.wait_for_timeout(200)
            lab = lambda i: pg.locator(f'.card[data-id="{i}"] [data-needs-verification]').count()
            self.assertEqual((lab("p-ok"), lab("p-changed"), lab("p-new"), lab("p-reset")), (0, 1, 1, 0))
            b.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
