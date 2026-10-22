# Botanical illustration status and generation queue

`data/botanical-status.json` is the single source of truth for **botanical** illustration state, one record per catalogue plant in catalogue
order (`data/plants.json`). Watercolour files (`<id>-watercolour.*`) are recorded separately under each plant's `watercolour` key and never
count as botanical. `tools/botanical_status.py` (stdlib only) builds, validates and queries it.

## Statuses
| status | meaning | enters generation queue? |
| --- | --- | --- |
| `missing` | no botanical PNG master and no botanical WebP in either repository | **yes, the only one** |
| `pending_review` | an image exists but is not approved yet in `data/botanical-verification.json`, or only half published (PNG without WebP or WebP without PNG) | no |
| `approved` | PNG master and WebP exist, hashes agree, and `data/botanical-verification.json` status is `confirmed` | no |
| `rejected` | manual flag: regenerate only when explicitly requested | no |
| `uncertain_match` | manual flag, or an automatic hash mismatch between files and records; never counted as approved | no |

The existing review system is reused, not duplicated: approval stays in `data/botanical-verification.json` (`confirmed` maps to `approved`,
`pending_review` stays `pending_review`) and file facts stay in `assets/plant-watercolours/manifest.json`. The status manifest only adds the
missing piece: plants with no image at all, and a single catalogue-ordered view across both repositories. `approvalBasis` shows whether a
`confirmed` record has an explicit approval timestamp (`explicit_approval`) or was confirmed on filename match only
(`auto_confirmed_on_filename_match`).

## Commands
```bash
python3 tools/botanical_status.py check                    # validate (exit 1 on any problem, including a stale manifest)
python3 tools/botanical_status.py queue 10                 # first 10 missing plant IDs, catalogue order
python3 tools/botanical_status.py queue 20 --skip 10       # the next 20
python3 tools/botanical_status.py summary
python3 tools/botanical_status.py build                    # recompute from repository state (keeps recorded PNG master fields)
python3 tools/botanical_status.py build --bd <border-designer checkout> --bd-ref origin/main   # also re-read PNG masters there
python3 tools/botanical_status.py set rejected <id> --note "why"   # or uncertain_match; pinned to the current WebP hash
```

## Workflow
1. "Generate the next 10 missing botanical illustrations" means `queue 10`: the first 10 IDs with `status=missing` in catalogue order.
   Generate with `docs/briefs/BOTANICAL_ASSET_BRIEF.md` in border-designer (the manifest records its last commit as `brief.version`).
2. Import: PNG master to border-designer `assets/plant-watercolours/masters/<id>.png`, WebP to `assets/plant-watercolours/<id>.webp` here,
   with the matching `plants[id]` record in `data/botanical-verification.json` and `assets[id]` in `assets/plant-watercolours/manifest.json`.
3. Run `build --bd <border-designer checkout>`; the plant moves to `pending_review` and leaves the queue (also if only one of the two files exists).
4. After manual approval (`python3 tools/set_verification.py confirmed <id>`), run `build`; the plant becomes `approved`.
5. A rejected image: `set rejected <id>`; it is regenerated only when explicitly asked, and re-enters `missing` only if its files are removed.
   `rejected` and `uncertain_match` pins apply to the image hash they were set on; replaced bytes clear the pin.

Run `check` before committing. Statuses are always recomputed from files and records, so the manifest cannot drift silently: `check` fails
whenever a file, record or catalogue entry changes without a rebuild.

PNG masters live in the private border-designer repository (`pngMasters` in the manifest records repo, ref and commit read), so `check`
here cannot re-read them; they are verified by `build --bd`.
