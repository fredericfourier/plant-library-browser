# Botanical image verification

`data/botanical-verification.json` holds one record per plant: `status` is `confirmed` or `pending_review`, plus the SHA-256 of the
public WebP (`imageSha256`). The browser shows a small orange, non-interactive **Needs verification** label on every
`pending_review` plant. There is no approval UI, service or login.

To approve a plant, ask for it to be approved (or run `python3 tools/set_verification.py confirmed <plant-id>`), commit and push;
the label disappears after the GitHub Pages deployment. When an image is re-imported with different bytes the importer resets the
record to its manifest status and keeps the old one under `previous`.

## Visible-content bounding boxes
`data/illustration-bounds.json` stores the bounding box of the non-transparent pixels (alpha > 8) of each illustration. The browser
draws it as a thin outline over each card image (toggle "Show bounding boxes"). Regenerate after changing any illustration:
`python3 tools/compute_visible_bounds.py`.
