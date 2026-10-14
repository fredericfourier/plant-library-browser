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
