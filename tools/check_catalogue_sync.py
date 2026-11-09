#!/usr/bin/env python3
"""Standalone drift check for the published plant data (stdlib only; no access to the private repository needed). Installed in the browser repository as tools/check_catalogue_sync.py.
  python3 tools/check_catalogue_sync.py [--root DIR]
Fails (exit 1) when data/plants.json is not a faithful, internally consistent export of a versioned catalogue:
  M1 the 'catalogue' manifest is present (name, version, recordCount, sharedDataSha256, workingSizeSchemaVersion, exportVersion, engineCatalogueRef)
  M2 recordCount equals the number of plants; ids and botanical names are unique
  M3 sharedDataSha256 recomputes from the plants (any hand edit of a shared value changes it: edit the canonical catalogue and re-export instead)
  M4 no private engine data is published (e3, engineNotes, evidence, provenance, enablement keys)
  M5 vocabulary: light (TOLERATES) is a non-empty subset of full_sun/part_shade/full_shade; preferredLight (PREFERS) is optional, a subset of light, labelled provisional and never active unless approved
  M6 sizes: positive integers; the illustration envelope follows the 10 px/cm convention (canonicalHeightPx = 10 x heightCm, expectedSpreadPx = 10 x spreadCm); workingSize, where present, equals heightCm/spreadCm
  M7 artwork links: every plant's registered botanical/watercolour file exists (missing art is reported, not failed, unless --strict-art)
  M8 archive: an archived record keeps its record and registered artwork, carries a well-formed 'archived' block (status archived, artwork approval unchanged), and the manifest's
     activeRecordCount / archivedRecordCount / archivedIds agree with the records (absent manifest keys = no archived records)"""
import sys, json, hashlib, argparse
from pathlib import Path
LIGHT = {'full_sun', 'part_shade', 'full_shade'}
PRIVATE = {'e3', 'engineNotes', 'designProvenance', 'evidenceFile', 'fieldStates', 'release', 'engineEnablement', 'conditionalSuitability'}
canon = lambda o: json.dumps(o, sort_keys=True, separators=(',', ':'), ensure_ascii=False)
def walk(o, path=''):
    if isinstance(o, dict):
        for k, v in o.items():
            yield path + '/' + k; yield from walk(v, path + '/' + k)
    elif isinstance(o, list):
        for i, v in enumerate(o): yield from walk(v, path)


def check(root, strict_art=False):
    root = Path(root); d = json.loads((root / 'data/plants.json').read_text(encoding='utf-8')); res = {}; plants = d.get('plants') or []
    def rec(name, problems, info=None): res[name] = dict(result='FAIL' if problems else 'PASS', problems=problems, info=info or {})
    cat = d.get('catalogue') or {}
    rec('M1_manifest', [f'catalogue.{k} missing' for k in ('name', 'version', 'recordCount', 'sharedDataSha256', 'workingSizeSchemaVersion', 'exportVersion', 'engineCatalogueRef') if k not in cat], {k: cat.get(k) for k in ('version', 'recordCount', 'sharedDataSha256', 'exportVersion')})
    ids = [p['id'] for p in plants]; names = [p['botanicalName'] for p in plants]
    rec('M2_count_identity', ([f'recordCount {cat.get("recordCount")} != {len(plants)} plants'] if cat.get('recordCount') != len(plants) else []) + [f'duplicate id {i}' for i in sorted(set(ids)) if ids.count(i) > 1] + [f'duplicate name {n}' for n in sorted(set(names)) if names.count(n) > 1], dict(records=len(plants)))
    got = hashlib.sha256(canon(plants).encode('utf-8')).hexdigest()
    rec('M3_shared_data_checksum', [] if got == cat.get('sharedDataSha256') else [f'checksum {got[:16]} != manifest {str(cat.get("sharedDataSha256"))[:16]}: shared data was edited outside the export'], dict(computed=got))
    leaks = sorted({k for p in plants for k in walk(p) if k.rsplit('/', 1)[-1] in PRIVATE}); rec('M4_no_private_engine_data', [f'private key published: {k}' for k in leaks[:10]])
    p5 = []
    for p in plants:
        lt = p.get('light') or []
        if not lt or not set(lt) <= LIGHT: p5.append(f'{p["id"]}: light {lt} not a non-empty subset of {sorted(LIGHT)}')
        if 'preferredLight' in p:
            pl = p['preferredLight']; v = pl.get('values') or []
            if not v or not set(v) <= set(lt): p5.append(f'{p["id"]}: preferredLight {v} is not a non-empty subset of tolerated light {lt}')
            if pl.get('state') not in ('PROVISIONAL', 'VERIFIED', 'DESIGN_JUDGEMENT', 'APPROVED'): p5.append(f'{p["id"]}: preferredLight state {pl.get("state")}')
            if pl.get('active') and pl.get('state') != 'APPROVED': p5.append(f'{p["id"]}: preferredLight active but not approved')
    rec('M5_light_vocabulary', p5, dict(withPreferredLight=sum('preferredLight' in p for p in plants)))
    p6 = []
    for p in plants:
        h, s, e = p.get('heightCm'), p.get('spreadCm'), p.get('watercolourEnvelope') or {}
        if not all(isinstance(x, int) and x > 0 for x in (h, s)): p6.append(f'{p["id"]}: size {h} x {s}'); continue
        if e.get('canonicalHeightPx') != h * 10 or e.get('expectedSpreadPx') != s * 10: p6.append(f'{p["id"]}: envelope {e.get("canonicalHeightPx")} x {e.get("expectedSpreadPx")} px != 10 px/cm of {h} x {s}')
        ws = p.get('workingSize')
        if ws and (ws.get('heightCm'), ws.get('spreadCm')) != (h, s): p6.append(f'{p["id"]}: workingSize {ws.get("heightCm")} x {ws.get("spreadCm")} != {h} x {s}')
        eds = p.get('engineDesignSize')
        if eds:
            if not all(isinstance(eds.get(k), int) and eds[k] > 0 for k in ('heightCm', 'spreadCm', 'referenceHeightCm', 'referenceSpreadCm')): p6.append(f'{p["id"]}: engineDesignSize needs positive integer design and reference sizes')
            elif (eds['referenceHeightCm'], eds['referenceSpreadCm']) != (h, s): p6.append(f'{p["id"]}: engineDesignSize reference {eds["referenceHeightCm"]} x {eds["referenceSpreadCm"]} != botanical reference {h} x {s}')
            elif (eds['heightCm'], eds['spreadCm']) == (h, s): p6.append(f'{p["id"]}: engineDesignSize equals the reference size (block is redundant)')
    rec('M6_sizes_and_envelope', p6)
    man = root / 'assets/plant-watercolours/manifest.json'; assets = (json.loads(man.read_text(encoding='utf-8')).get('assets') or {}) if man.is_file() else {}; p7 = []; missing = []
    for i in ids:
        a = assets.get(i)
        if not a: missing.append(i); continue
        files = [a.get('file')] + [v.get('file') for v in (a.get('variants') or {}).values() if isinstance(v, dict)]
        p7 += [f'{i}: registered file missing on disk: {f}' for f in files if f and not (root / f).is_file() and not (root / 'assets/plant-watercolours' / f).is_file()]
    if strict_art: p7 += [f'{i}: no registered artwork' for i in missing]
    rec('M7_artwork_links', p7, dict(plantsWithoutRegisteredArt=missing))
    arch = [p['id'] for p in plants if 'archived' in p]; p8 = []
    for p in plants:
        a = p.get('archived')
        if a is None: continue
        if not isinstance(a, dict) or a.get('status') != 'archived' or a.get('artworkApproval') != 'unchanged' or not a.get('decidedAt') or not a.get('reason'): p8.append(f'{p["id"]}: malformed archived block')
        if p['id'] not in assets: p8.append(f'{p["id"]}: archived record lost its registered artwork')
    if arch or 'archivedIds' in cat:
        if sorted(cat.get('archivedIds') or []) != sorted(arch): p8.append(f'catalogue.archivedIds {cat.get("archivedIds")} != archived records {arch}')
        if cat.get('archivedRecordCount') != len(arch) or cat.get('activeRecordCount') != len(plants) - len(arch): p8.append('active/archived counts do not match the records')
    rec('M8_archive', p8, dict(activeRecords=len(plants) - len(arch), archivedRecords=len(arch), archivedIds=arch))
    return res


def main():
    ap = argparse.ArgumentParser(); ap.add_argument('--root', default=str(Path(__file__).resolve().parent.parent)); ap.add_argument('--strict-art', action='store_true'); ap.add_argument('--json'); a = ap.parse_args()
    res = check(a.root, a.strict_art)
    for k, v in res.items(): print('%-30s %s%s' % (k, v['result'], '' if not v['problems'] else '  ' + '; '.join(v['problems'][:3])))
    if a.json: Path(a.json).write_text(json.dumps(res, indent=1, ensure_ascii=False) + '\n')
    sys.exit(1 if any(v['result'] == 'FAIL' for v in res.values()) else 0)

if __name__ == '__main__': main()
