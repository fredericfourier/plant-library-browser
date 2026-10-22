#!/usr/bin/env python3
"""Browser regression for per-variant illustration availability in index.html. Run: python3 tools/test_browser_availability.py

Serves a throwaway 4-plant site (copy of the real index.html + synthetic data/images) and drives it with headless Chromium (Playwright):
  both | botanical only | watercolour only | neither.
Skipped (not failed) when Playwright/Chromium is unavailable. Nothing real is read apart from index.html.
"""
import functools, http.server, json, shutil, tempfile, threading, unittest
from pathlib import Path

from PIL import Image

try:
    from playwright.sync_api import sync_playwright
except ImportError:  # pragma: no cover
    sync_playwright = None

REPO = Path(__file__).resolve().parent.parent
A = "assets/plant-watercolours/"
IDS = {"both": "p-both", "bot": "p-bot", "wc": "p-wc", "none": "p-none"}


def make_site(root):
    (root / A).mkdir(parents=True)
    (root / "data").mkdir()
    shutil.copy(REPO / "index.html", root / "index.html")
    plants = [{"id": i, "botanicalName": f"Plantus {k}", "commonName": k, "type": "perennial", "heightCm": 60, "spreadCm": 40, "light": ["full_sun"],
               "description": "d"} for k, i in IDS.items()]
    (root / "data/plants.json").write_text(json.dumps({"schemaVersion": 1, "updated": "2026-10-22", "plants": plants}))
    (root / "data/botanical-verification.json").write_text(json.dumps({"plants": {}}))
    (root / "data/additions.json").write_text(json.dumps({"batches": []}))
    im = Image.new("RGBA", (40, 60), (0, 0, 0, 0))
    for x in range(10, 30):
        for y in range(10, 55):
            im.putpixel((x, y), (30, 140, 60, 255))
    assets = {}
    for k in ("both", "bot"):
        im.save(root / A / f"{IDS[k]}.webp", "WEBP", lossless=True)
        assets[IDS[k]] = {"file": f"{A}{IDS[k]}.webp", "status": "ready"}
    for k in ("both", "wc"):
        im.save(root / A / f"{IDS[k]}-watercolour.webp", "WEBP", lossless=True)
        assets.setdefault(IDS[k], {}).setdefault("variants", {})["watercolour"] = {"label": "Watercolour", "file": f"{A}{IDS[k]}-watercolour.webp", "status": "awaiting_review", "sha256": "ab" * 32}
    (root / A / "manifest.json").write_text(json.dumps({"schemaVersion": 1, "updated": "2026-10-22", "assets": assets}))


class Quiet(http.server.SimpleHTTPRequestHandler):
    log = None

    def log_message(self, fmt, *a):
        pass


@unittest.skipIf(sync_playwright is None, "playwright not installed")
class Availability(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp())
        make_site(cls.tmp)
        h = functools.partial(Quiet, directory=str(cls.tmp))
        cls.srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), h)
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
        cls.pw = sync_playwright().start()
        try:
            exe = next((str(c) for c in sorted(Path("/opt/pw-browsers").glob("chromium-*/chrome-linux/chrome"))), None)
            cls.browser = cls.pw.chromium.launch(executable_path=exe) if exe else cls.pw.chromium.launch()
        except Exception as e:  # pragma: no cover
            cls.pw.stop(); cls.srv.shutdown()
            raise unittest.SkipTest(f"chromium unavailable: {e}")

    @classmethod
    def tearDownClass(cls):
        cls.browser.close(); cls.pw.stop(); cls.srv.shutdown(); shutil.rmtree(cls.tmp, True)

    def setUp(self):
        self.page = self.browser.new_page(viewport={"width": 1300, "height": 900})
        self.reqs, self.errors = [], []
        self.page.on("request", lambda r: self.reqs.append(r.url))
        self.page.on("pageerror", lambda e: self.errors.append(str(e)))
        self.page.goto(f"http://127.0.0.1:{self.srv.server_address[1]}/index.html")
        self.page.wait_for_selector(".card")
        self.addCleanup(self.page.close)

    def card(self, key):
        return self.page.locator(f'.card[data-id="{IDS[key]}"]')

    def art(self, key):
        return self.card(key).locator(".art")

    def mode(self, v):
        self.page.select_option("#variant", v)
        self.page.wait_for_timeout(150)

    def requested(self, name):
        return [u for u in self.reqs if name in u.split("?")[0]]

    def test_botanical_mode(self):
        self.assertEqual(self.page.locator(".card").count(), 4, "all four plants stay in the catalogue")
        self.assertIn("p-both.webp", self.art("both").locator("img").get_attribute("src"))
        self.assertIn("p-bot.webp", self.art("bot").locator("img").get_attribute("src"))
        self.assertEqual(self.art("wc").locator("img").count(), 0)
        self.assertIn("Botanical missing", self.art("wc").inner_text())
        self.assertIn("Watercolour: available", self.art("wc").inner_text())
        self.assertIn("No illustrations yet", self.art("none").inner_text())
        self.assertEqual(self.requested("p-wc.webp"), [], "a nonexistent botanical image is never requested")
        self.assertEqual(self.requested("p-none"), [])

    def test_watercolour_mode(self):
        self.mode("watercolour")
        self.assertEqual(self.page.locator(".card").count(), 4)
        self.assertIn("p-both-watercolour.webp", self.art("both").locator("img").get_attribute("src"))
        self.assertIn("p-wc-watercolour.webp", self.art("wc").locator("img").get_attribute("src"))
        self.assertEqual(self.art("bot").locator("img").count(), 0)
        self.assertIn("Watercolour missing", self.art("bot").inner_text())
        self.assertIn("No illustrations yet", self.art("none").inner_text())
        self.assertEqual(self.requested("p-wc.webp"), [])

    def test_counts_and_filter(self):
        self.assertIn("3 with illustrations", self.page.inner_text("#stats"))
        self.page.select_option("#artFilter", "missing")
        self.page.wait_for_timeout(100)
        self.assertEqual(self.page.locator(".card").count(), 1)
        self.assertEqual(self.page.locator(".card").first.get_attribute("data-id"), IDS["none"])
        self.page.select_option("#artFilter", "with")
        self.page.wait_for_timeout(100)
        self.assertEqual({c.get_attribute("data-id") for c in self.page.locator(".card").all()}, {IDS["both"], IDS["bot"], IDS["wc"]})

    def test_compare_mode(self):
        self.page.check("#cmpToggle")
        self.page.wait_for_timeout(150)
        pane = lambda k, v: self.card(k).locator(f'.pane[data-pane="{v}"]')
        self.assertEqual(pane("both", "botanical").locator("img").count() + pane("both", "watercolour").locator("img").count(), 2)
        self.assertIn("Botanical missing", pane("wc", "botanical").inner_text())
        self.assertEqual(pane("wc", "watercolour").locator("img").count(), 1)
        self.assertIn("Watercolour missing", pane("bot", "watercolour").inner_text())
        self.assertEqual(pane("bot", "botanical").locator("img").count(), 1)
        self.assertEqual(self.card("none").locator(".pane").count(), 0)
        self.assertIn("No illustrations yet", self.art("none").inner_text())
        self.assertEqual(self.requested("p-wc.webp"), [])

    def test_enlarged_viewer(self):
        self.mode("watercolour")
        self.art("wc").locator("img").click()
        self.page.wait_for_selector("#imageDlg[open]")
        self.assertIn("p-wc-watercolour.webp", self.page.get_attribute("#fullImage", "src"))
        self.assertEqual(self.page.get_attribute("#imageDlg", "data-variant"), "watercolour")
        self.assertTrue(self.page.is_disabled("#ivBot"), "botanical toggle disabled for a watercolour-only plant")
        self.page.click("#imageClose")
        self.mode("botanical")
        self.page.check("#cmpToggle")
        self.page.wait_for_timeout(100)
        self.art("wc").locator('.pane[data-pane="watercolour"] img').click()
        self.page.wait_for_selector("#imageDlg[open]")
        self.assertIsNone(self.page.get_attribute("#fullImage", "src"), "no botanical src in compare viewer")
        self.assertIn("p-wc-watercolour.webp", self.page.get_attribute("#fullImage2", "src"))
        self.assertIn("unavailable", self.page.inner_text("#ivArea1"))
        self.assertEqual(self.requested("p-wc.webp"), [])
        self.assertEqual(self.errors, [])

    def test_detail_dialog_and_contact_sheet(self):
        self.card("wc").click()
        self.page.wait_for_selector("#dlg[open]")
        self.assertIn("Botanical missing", self.page.inner_text("#art"))
        self.page.click("#close")
        self.page.click("#contactBtn")
        self.page.wait_for_selector("#sheetDlg[open]")
        cells = self.page.locator(".sheetCard")
        self.assertEqual(cells.count(), 3, "plants with no illustration at all are not on the sheet")
        miss = self.page.locator(f'[data-sheet-missing="{IDS["wc"]}"]')
        self.assertEqual(miss.inner_text(), "Botanical missing")
        self.assertEqual(self.page.locator(f'[data-sheet-zoom="{IDS["bot"]}"]').count(), 1)
        self.page.click('[data-sheet-variant="watercolour"]')
        self.page.wait_for_timeout(150)
        self.assertEqual(self.page.locator(f'[data-sheet-missing="{IDS["bot"]}"]').inner_text(), "Watercolour missing")
        self.assertEqual(self.page.locator(f'[data-sheet-zoom="{IDS["wc"]}"]').count(), 1)
        self.assertEqual(self.requested("p-wc.webp"), [])
        self.assertEqual(self.errors, [])

    def test_both_state_unchanged(self):
        img = self.art("both").locator("img")
        self.assertIn("p-both.webp", img.get_attribute("src"))
        self.assertEqual(self.art("both").locator(".envBox").count(), 1)
        self.mode("watercolour")
        self.assertIn("p-both-watercolour.webp", self.art("both").locator("img").get_attribute("src"))
        self.assertEqual(self.art("both").locator(".envBox").count(), 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
