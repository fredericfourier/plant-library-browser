# Plant Library Browser

Public browser for the Border Designer plant library.

The browser loads `data/plants.json` live at runtime. The private Border Designer repository remains the canonical source; this public repository contains the published browser copy used for cross-device access.

## Watercolour convention
Production assets are expected at:

`assets/plant-watercolours/<plant-id>.webp`

Example: `assets/plant-watercolours/salvia-caradonna.webp`

## Illustration types
Each plant has at most two selectable illustrations: **Botanical** (`<plant-id>.webp`) and **Watercolour**
(`<plant-id>-watercolour.webp`, registered as `variants.watercolour` in `assets/plant-watercolours/manifest.json`).
Older watercolour A/B variants were consolidated into this single watercolour per plant; earlier versions remain in Git history.
`assets/side-view/backgrounds/` holds the watercolour-paper background used for watercolour side views.

## Asset rule
Real photography defines morphology. Database height/spread defines physical scale. Watercolour assets are scaled uniformly and should never be stretched or squashed to compensate for inaccurate source proportions.

## Download all illustrations
The **Download all illustrations (ZIP)** control beside **Contact sheet** downloads one complete,
prebuilt archive of the current published catalogue, regardless of search/filter settings.

The ZIP contains:
- `botanical/<plant-id>.webp` for botanical illustrations;
- `watercolour/<plant-id>-watercolour.webp` for watercolor illustrations;
- `plant-data.json` (plant IDs, names, height/spread and other library data);
- `source-asset-manifest.json` (original published asset registration);
- `illustrations-manifest.json` (per-asset SHA-256 hashes, sizes and missing variants).

Images are copied byte-for-byte: no resampling, image modification, PNG conversion or recompression.
Missing variants, if any, are explicitly listed in the ZIP manifest. The exported files are **WebP**, not the
original PNG masters. They can be opened directly or converted externally if required.

`tools/build_illustrations_zip.py` builds the bundle as part of the normal GitHub Pages workflow,
so the download always reflects the published image set after a successful deployment. The current
71-plant catalogue has 142 images and the archive is approximately 123 MiB; this will increase as
the library grows. The ZIP is deliberately built during deployment rather than assembled in browser
memory, making it more reliable on mobile devices.

## Contact sheet
The contact-sheet popup shows a dynamic title ("Botanical contact sheet" / "Watercolour contact sheet") and a `Botanical | Watercolour` switcher that re-renders in place (popup, browser filters, selection and scroll are kept). Images come from the manifest; a plant without the chosen type shows "Illustration unavailable" and is never substituted.

## Botanical illustration status
`data/botanical-status.json` tracks the botanical illustration state of every catalogue plant (missing / pending_review / approved /
rejected / uncertain_match) and defines the generation queue (`python3 tools/botanical_status.py queue 10`). See `docs/BOTANICAL_STATUS.md`.

## Botanical verification
Plants whose botanical image still needs a human check carry an orange "Needs verification" label (status in `data/botanical-verification.json`);
see `docs/BOTANICAL_VERIFICATION.md`. Cards show the same dotted mature-envelope box as the contact sheet ("Show bounding boxes" toggle, default on).
