# Botanical image verification

`data/botanical-verification.json` holds one record per plant: `status` is `confirmed` or `pending_review`, plus the SHA-256 of the
public WebP (`imageSha256`). The browser shows a small orange, non-interactive **Needs verification** label on every
`pending_review` plant. There is no approval UI, service or login.

To approve a plant, ask for it to be approved (or run `python3 tools/set_verification.py confirmed <plant-id>`), commit and push;
the label disappears after the GitHub Pages deployment. When an image is re-imported with different bytes the importer resets the
record to its manifest status and keeps the old one under `previous`.

## Bounding boxes
Each card draws the same dotted mature-envelope box as the contact sheet (database spread x height, scaled; the illustration is placed in it
by the shared `placeInEnvelope` silhouette logic). The "Show bounding boxes" toggle (default on) only shows or hides the dotted lines.

## Watercolour review status
Imported watercolours (`tools/import_watercolour_assets.py`) are recorded in the same file as `plants[id].watercolour.status = awaiting_review`
(pinned to the WebP's `imageSha256`). The Watercolour view shows the same orange label ("Awaiting review"). Approve by editing the status
to `confirmed` and pushing; nothing is approved automatically. The private PNG masters live in border-designer at
`assets/plant-watercolours/masters/<plant-id>-watercolour.png`.
