#!/usr/bin/env python3
"""Build the static Plant Library Browser illustrations download from its published assets.

Run from the repository root: python3 tools/build_illustrations_zip.py
No image modification, format conversion or dependencies beyond Python stdlib.
"""
import argparse
import hashlib
import json
from pathlib import Path
from zipfile import ZIP_STORED, ZipFile, ZipInfo

ROOT = Path(__file__).resolve().parent.parent
STAMP = (2026, 1, 1, 0, 0, 0)  # fixed timestamp for reproducible archives


def add_bytes(zf, name, content):
    info = ZipInfo(name, STAMP)
    info.compress_type = ZIP_STORED
    info.external_attr = 0o644 << 16
    zf.writestr(info, content)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', default='downloads/border-designer-plant-illustrations.zip')
    args = parser.parse_args()
    catalog_bytes = (ROOT / 'data/plants.json').read_bytes()
    source_manifest_bytes = (ROOT / 'assets/plant-watercolours/manifest.json').read_bytes()
    catalog = json.loads(catalog_bytes)
    source_manifest = json.loads(source_manifest_bytes)
    plants = catalog['plants']
    asset_index = source_manifest['assets']
    entries, missing, inventories = [], [], []
    known_ids = set()
    for plant in sorted(plants, key=lambda p: p['id']):
        pid = plant['id']
        if pid in known_ids:
            raise ValueError(f'Duplicate plant ID in catalogue: {pid}')
        known_ids.add(pid)
        record = {'id': pid, 'botanicalName': plant.get('botanicalName'),
                  'heightCm': plant.get('heightCm'), 'spreadCm': plant.get('spreadCm'),
                  'files': {}}
        source = asset_index.get(pid, {})
        for variant in ('botanical', 'watercolour'):
            item = source if variant == 'botanical' else source.get('variants', {}).get('watercolour', {})
            rel = item.get('file')
            if not rel:
                missing.append({'id': pid, 'variant': variant, 'reason': 'not registered'})
                continue
            # Only the matching published WebP is allowed, never arbitrary filesystem paths.
            expected = f'assets/plant-watercolours/{pid}' + ('-watercolour' if variant == 'watercolour' else '') + '.webp'
            if rel != expected:
                raise ValueError(f'Unexpected asset path for {pid} {variant}: {rel!r}')
            src = ROOT / rel
            if not src.is_file():
                raise FileNotFoundError(f'Registered illustration missing: {rel}')
            sha = hashlib.sha256(src.read_bytes()).hexdigest()
            if item.get('sha256') and item['sha256'] != sha:
                raise ValueError(f'Checksum mismatch for {rel}')
            dest = f'{variant}/{src.name}'
            record['files'][variant] = {'path': dest, 'sha256': sha, 'bytes': src.stat().st_size}
            inventories.append((dest, src))
        entries.append(record)

    # Never silently leave published image files out of the download.
    referenced = {p.as_posix() for _, p in inventories}
    extra = sorted(p.as_posix() for p in (ROOT / 'assets/plant-watercolours').glob('*.webp') if p.as_posix() not in referenced)
    if extra:
        raise ValueError(f'Unindexed WebP illustrations would be omitted: {extra}')
    bundle_manifest = {'schemaVersion': 1, 'description': 'Published Botanical and Watercolour WebP illustrations with transparency; not PNG masters',
                       'catalogueUpdated': catalog.get('updated'), 'plants': entries, 'missing': missing,
                       'counts': {'plants': len(entries), 'illustrations': len(inventories),
                                  'botanical': sum('botanical' in p['files'] for p in entries),
                                  'watercolour': sum('watercolour' in p['files'] for p in entries)}}
    output = ROOT / args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    with ZipFile(output, 'w', allowZip64=True) as zf:
        for dest, src in sorted(inventories):
            info = ZipInfo(dest, STAMP)
            info.compress_type = ZIP_STORED  # WebP is already compressed
            info.external_attr = 0o644 << 16
            info.file_size = src.stat().st_size
            with src.open('rb') as f, zf.open(info, 'w') as z:
                while chunk := f.read(1024 * 1024):
                    z.write(chunk)
        add_bytes(zf, 'plant-data.json', catalog_bytes)
        add_bytes(zf, 'source-asset-manifest.json', source_manifest_bytes)
        add_bytes(zf, 'illustrations-manifest.json', (json.dumps(bundle_manifest, indent=2, ensure_ascii=False, sort_keys=True) + '\n').encode('utf-8'))
    with ZipFile(output) as zf:
        bad = zf.testzip()
        if bad:
            raise RuntimeError(f'ZIP integrity failure: {bad}')
    print(f"Wrote {output.relative_to(ROOT)}: {bundle_manifest['counts']}, {output.stat().st_size / 1048576:.1f} MiB, {len(missing)} unavailable variants")


if __name__ == '__main__':
    main()
