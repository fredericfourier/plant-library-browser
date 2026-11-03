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

## Permanent approval lifecycle (visual approval vs source integrity)
An owner approval belongs to the **exact published WebP bytes** and to nothing else. It is recorded in the append-only
`data/approval-ledger.json` (`tools/approval_ledger.py`): `{variant, plantId, imageSha256, approvedAt}`. Historic `approvedAt` values are copied verbatim.

* **Approval is permanent for unchanged bytes.** A status rebuild, catalogue export, asset-manifest sync, importer run or CI run cannot end it.
  PNG-master presence, absence, staleness or provenance never changes it. Only an explicit `approval_ledger.py revoke ... --reason` (owner request) does.
* **Changed bytes are never approved.** A different WebP is `approval_for_other_bytes` (status `pending_review`/`uncertain_match`) until
  `approval_ledger.py approve <variant> <id>` records a new owner approval for the new hash. Old entries stay. Editing a verification record
  (e.g. re-pinning `imageSha256` to replacement bytes while keeping `approvedAt`) never transfers an approval; `approvedOriginalImageSha256` names the bytes actually approved.
* **Source integrity is a separate, NON-BLOCKING maintenance warning** (`sourceIntegrity` in the status manifests): `ok`, `master_not_registered`, `master_stale`
  (the registered master equals a superseded version), `master_hash_mismatch`, `record_unpinned`. It is reported, never used to approve or reject.
* An unchanged WebP re-imported with a different PNG master (importer, `plant_asset_publish.py`) is a provenance update: the record is kept and the
  new master hash is appended to `sourceMasters`.
* The browser pins labels to bytes too: ledger-approved bytes show no review label; a record pinned to different bytes than the published file does.
* CI (`validate-catalogue-sync.yml`) runs `approval_ledger.py check --base origin/main`, both manifest checks and `test_approval_lifecycle.py`.
Applies identically to botanical illustrations and to every future plant (new plant: published, `not_approved`, until `approve`).
* **Replacement bytes the owner has already accepted** (e.g. the CP9.1 resolution corrections) are recorded with
  `approval_ledger.py accept <variant> <id> --sha256 <new> --supersedes <approved> --basis ... --at <UTC time of the owner's confirmation>`:
  one ledger entry per image hash, carrying the superseded hash and its original timestamp. No new visual review is implied or required.
* Published artwork eligibility needs only the published WebP and its ledger entry. A missing, stale or unregistered PNG master is a maintenance
  item (`sourceIntegrity.blocking = false`) and never blocks rendering or customer eligibility.
