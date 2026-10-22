# Botanical illustration status and generation queue

`data/botanical-status.json` is the single source of truth for **botanical** illustration state, one record per catalogue plant in catalogue
order (`data/plants.json`). Watercolour files (`<id>-watercolour.*`) are recorded separately under each plant's `watercolour` key and never
count as botanical. `tools/botanical_status.py` (stdlib only) builds, validates and queries it.

## Statuses
| status | meaning | enters generation queue? |
| --- | --- | --- |
| `missing` | no botanical PNG master, no botanical WebP and no reservation | **yes, the only one** |
| `pending_review` | not approved by a person: a generated image delivered but not imported yet (a *reservation*, `assetForm` none), an imported image awaiting approval, an image confirmed by filename match only, or a half-published image | no |
| `approved` | PNG master and WebP exist, hashes agree, and `data/botanical-verification.json` carries an explicit manual approval (`approvedAt`) | no |
| `rejected` | manual flag: regenerate only when explicitly requested | no |
| `uncertain_match` | manual flag, or an automatic hash mismatch between files and records; never counted as approved | no |

The existing review system is reused, not duplicated: approval stays in `data/botanical-verification.json` and file facts stay in
`assets/plant-watercolours/manifest.json`; this tool never writes either. The status manifest adds only what they lack: plants with no image,
reservations, and a single catalogue-ordered view across both repositories.

### Approval basis (`approvalBasis`)
- `explicit_manual_approval`: `confirmed` with an `approvedAt` timestamp (set by `tools/set_verification.py confirmed <id>`). Only these are `approved`.
- `filename_match_only`: `confirmed` in the verification file without `approvedAt`, i.e. the image was matched by filename and no person approved it.
  These plants **keep their image and verification history**, are `pending_review` with `manualApprovalAt: null`, are never regenerated and never
  queued, and are not represented as verified botanical matches. Approving one with `set_verification.py` makes it `approved` after the next `build`.
- `null`: no verification record, or one that is still `pending_review`.

### Reservations (generated, ZIP received, not yet imported)
A generation package delivered as a ZIP is not in GitHub until it is imported, so its plants would otherwise stay `missing` and be generated twice.
Right after receiving a package, record it:
```bash
python3 tools/botanical_status.py reserve <id> [<id> ...] --batch ZIP-2026-10-22-A --source gen-A.zip   # default expiry 14 days
```
Each reserved plant becomes `pending_review` with `assetForm: none` and a `reservation` (`batchId`, `source`, `reservedAt`, `expiresAt`);
`queue` skips it. Only `missing` plants can be reserved (a plant with an active or expired reservation must first be renewed or released). Nothing is published or approved.
- **Import** the images and run `build --bd ...`: the reservation clears itself and the status follows the files and the verification record.
- **ZIP lost or rejected:** `release --batch <B>` (or `release <ids>`) returns the plants to `missing` at once.
- **Needs more time:** `renew --batch <B> [--days N]`.
- **Forgotten:** after `expiresAt`, `queue` refuses to run (exit 2, no IDs) and `check` fails until each expired reservation is imported,
  renewed or released. Expired reservations are never re-queued automatically: a generated package may still exist, so a person decides.
`reservations` lists them with active/expired state.

## Safety stops
`queue` and `reserve` first check that the manifest is fresh and exit 2 without returning any ID when it is not:
- the catalogue (`data/plants.json`) and the manifest list different plants (the message names the new or removed IDs), or
- files, verification records or the asset manifest changed since the last `build`, or
- (`queue` only) any reservation is expired.
The message says what to do: `build --bd <border-designer checkout>`, review and commit the manifest diff, then repeat; or renew/release/import.
PNG masters in the private repo cannot be re-read without `--bd`, so freshness against them is only checked when you rebuild with it.

## Commands
```bash
python3 tools/botanical_status.py check                    # validate (exit 1 on any problem, including a stale manifest or an expired reservation)
python3 tools/botanical_status.py queue 10                 # first 10 missing plant IDs, catalogue order (refuses if stale)
python3 tools/botanical_status.py queue 20 --skip 10       # the next 20
python3 tools/botanical_status.py summary
python3 tools/botanical_status.py build                    # recompute from repository state (keeps recorded PNG master fields)
python3 tools/botanical_status.py build --bd <border-designer checkout> --bd-ref origin/main   # also re-read PNG masters there
python3 tools/botanical_status.py set rejected <id> --note "why"   # or uncertain_match; pinned to the current WebP hash
python3 tools/botanical_status.py reserve|release|renew|reservations ...   # see Reservations; add --today YYYY-MM-DD to test expiry
```

## Workflow
1. "Generate the next 10 missing botanical illustrations" means `queue 10`: the first 10 plants still to generate, in catalogue order
   (status `missing` only; active reservations are excluded, and expired ones stop the queue until reconciled). Generate with `docs/briefs/BOTANICAL_ASSET_BRIEF.md` in border-designer (its last commit is `brief.version`).
2. When the ZIP arrives, `reserve` those IDs (commit the manifest). The next `queue` request then returns the following plants.
3. Import: PNG master to border-designer `assets/plant-watercolours/masters/<id>.png`, WebP to `assets/plant-watercolours/<id>.webp` here,
   with the plant's record in `data/botanical-verification.json` and `assets/plant-watercolours/manifest.json`.
4. Run `build --bd <border-designer checkout>`; the reservation clears and the plant stays `pending_review` (also if only one of the two files exists).
5. After manual approval (`python3 tools/set_verification.py confirmed <id>`), run `build`; the plant becomes `approved`.
6. A rejected image: `set rejected <id>`; it is regenerated only when explicitly asked, and re-enters `missing` only if its files are removed.
   `rejected` and `uncertain_match` pins apply to the image hash they were set on; replaced bytes clear the pin.

Run `check` before committing. Statuses are always recomputed from files and records, so the manifest cannot drift silently: `check` fails
whenever a file, record or catalogue entry changes without a rebuild.

PNG masters live in the private border-designer repository (`pngMasters` in the manifest records repo, ref and commit read), so `check`
here cannot re-read them; they are verified by `build --bd`.

## Watercolour variant (`--type watercolour`)
The same tool, statuses, reservations, safety stops and queue ordering run over the watercolour illustrations. Put `--type watercolour` **before** the subcommand;
the default (`botanical`) is unchanged. State is independent: `data/watercolour-status.json` is built only from `<id>-watercolour.webp`, the private
`<id>-watercolour.png` masters (border-designer, `assets/plant-watercolours/masters/`) and `plants[id].watercolour` in `data/botanical-verification.json`
(`confirmed` + `approvedAt` = approved; `awaiting_review` = pending_review). A botanical image never counts as a watercolour and vice versa; reservations are per type.
```bash
python3 tools/botanical_status.py --type watercolour check
python3 tools/botanical_status.py --type watercolour queue 10                # "Generate the next 10 missing watercolour illustrations"
python3 tools/botanical_status.py --type watercolour queue 10 --detail       # + height/spread, filenames, brief, reference image
python3 tools/botanical_status.py --type watercolour reserve <ids> --batch WC-ZIP-A --source gen.zip   # right after receiving a generated ZIP
python3 tools/botanical_status.py --type watercolour build --bd <border-designer checkout> --bd-ref origin/main   # after importing
python3 tools/test_illustration_status.py                                    # queue/idempotency/independence tests (sandbox copies only)
```
Brief: `docs/briefs/WATERCOLOUR_B_ASSET_BRIEF.md` with the approved style reference `docs/references/nepeta-watercolour-very-wet-approved.png` (both in border-designer;
the image must be attached to the generator, a path in a prompt sends no pixels). `pipelineQa` in a watercolour record is the recorded `variants.watercolour.status`
of `assets/plant-watercolours/manifest.json` (still `awaiting_review` there for imported images); approval comes only from the verification file.

### Batch handoff (both types): queue → generate → deliver → reserve → commit → next queue
A reservation exists only in `data/<type>-status.json`. If it is not committed (and pushed, when other sessions use the branch) it is invisible to them and the same IDs
can be handed out twice. Run the sequence in this order, with `T="python3 tools/botanical_status.py --type watercolour"` (omit `--type` for botanical):
```bash
git fetch origin && git pull --ff-only                         # 0. latest manifest from the shared branch
git -C <border-designer> fetch origin                          # 0. latest PNG masters
$T build --bd <border-designer> --bd-ref origin/main           # 0. refresh PNG-master info; commit the diff if any
$T queue 10 --bd <border-designer> --bd-ref origin/main --require-synced   # 1. queue: refuses (exit 2, no IDs) if masters/brief differ from the manifest,
                                                                           #    or the manifest is uncommitted, unpushed or behind upstream
# 2. generate (outside the repo)   3. deliver the ZIP
$T reserve <ids> --batch WC-ZIP-YYYY-MM-DD-A --source <zip>   # 4. reserve immediately
git add data/watercolour-status.json && git commit -m "Reserve WC-ZIP-…-A" && git push   # 5. commit + push
$T sync                                                        # exit 0 only when committed and in step with upstream (exit 3 otherwise)
$T queue 10 --bd <border-designer> --bd-ref origin/main --require-synced   # 6. next queue: excludes the reserved IDs
```
After importing the images (public WebP + private PNG master in border-designer): `build --bd … --bd-ref <ref containing the masters>`, `check`, commit, push. The reservation clears
itself and the status follows the files and approval records. Without `--bd` the private repository cannot be seen, so a master added only there is not detected: always pass `--bd` for a new
generation cycle. `--require-synced` is opt-in; without it `queue` keeps its previous behaviour.

Known limitation: `tools/import_watercolour_assets.py` indexes `manifest.json[id]` and `botanical-verification.json[id]` directly, so importing a watercolour for a plant that has no botanical
record yet fails with KeyError (by reading the code; not changed here). Import the botanical image first or create the records. The status tool itself accepts a watercolour-only
verification record (`plants[id]` with only `watercolour`), and the botanical build ignores it.
