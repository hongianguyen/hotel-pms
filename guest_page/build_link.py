# -*- coding: utf-8 -*-
"""Builds the page <-> till link and writes it as JSON for injection.

Runs the automatic join first (exact, then containment, then fuzzy on the
Vietnamese name), then lets menu_link.py override it. Every prod name the
curated table mentions is checked against english_names.py, so a typo here
fails the build instead of silently making a dish unorderable.
"""
import re, json, sys, unicodedata, difflib, csv
sys.path.insert(0, '/home/claude-worker/hotel-pms/tools/ylak_menu_import')
from english_names import ENGLISH
import menu_link as CUR

PROD = [vn for vn, _e, _d, _s in ENGLISH]
PSET = set(PROD)

def norm(s):
    s = unicodedata.normalize('NFC', (s or '')).casefold()
    s = s.replace('lăk', 'lắk').replace('lak', 'lắk')
    return re.sub(r'\s+', ' ', re.sub(r'[+/]', ' ', s)).strip()

PN = {vn: norm(vn) for vn in PROD}

# --- validate the curated table before trusting it -------------------------
bad = []
for k, v in CUR.OVERRIDE.items():
    if v not in PSET: bad.append(('OVERRIDE', k, v))
for k, vs in CUR.VARIANTS.items():
    for v in vs:
        if v not in PSET: bad.append(('VARIANTS', k, v))
for _p, vs in CUR.SETS:
    for v in vs:
        if v not in PSET: bad.append(('SETS', _p, v))
if bad:
    for w, k, v in bad: print('NOT A PROD PRODUCT: %s %r -> %r' % (w, k, v))
    raise SystemExit('curated table references products that do not exist')

html = open('original_24aug.html', encoding='utf-8').read()
MENU = json.loads(re.search(r'const MENU = (\[.*?\]);', html, re.S).group(1))
SETS = json.loads(re.search(r'const SETS = (\[.*?\]);', html, re.S).group(1))

link, audit = {}, []
for it in MENU:
    vi, k = it['vi'], norm(it['vi'])
    if vi in CUR.OVERRIDE:
        link[vi] = {'p': CUR.OVERRIDE[vi]}; audit.append((vi, CUR.OVERRIDE[vi], 'curated')); continue
    if vi in CUR.VARIANTS:
        link[vi] = {'v': CUR.VARIANTS[vi]}
        audit.append((vi, ' + '.join(CUR.VARIANTS[vi]), 'curated-variants')); continue
    if vi in CUR.ABSENT:
        link[vi] = {'absent': True}; audit.append((vi, '', 'absent')); continue
    m = [p for p in PROD if PN[p] == k]
    if m:
        link[vi] = {'p': m[0]}; audit.append((vi, m[0], 'exact')); continue
    c = [p for p in PROD if k and (k in PN[p] or PN[p] in k)]
    if c:
        best = min(c, key=lambda p: abs(len(PN[p]) - len(k)))
        link[vi] = {'p': best}; audit.append((vi, best, 'contains')); continue
    f = difflib.get_close_matches(k, [PN[p] for p in PROD], n=1, cutoff=0.82)
    if f:
        p = next(p for p in PROD if PN[p] == f[0])
        link[vi] = {'p': p}; audit.append((vi, p, 'fuzzy')); continue
    link[vi] = {'absent': True}; audit.append((vi, '', 'NO MATCH'))

setlink, seen = {}, {}
for s in SETS:
    price = s['p']
    tier = next((v for p, v in CUR.SETS if p == price), None)
    i = seen.get(price, 0); seen[price] = i + 1
    if tier and i < len(tier):
        setlink['%s|%s' % (s['n'], price)] = tier[i]

# Every prod product this link depends on, so a test can check that each one
# the till really offers did resolve. build_link.py and order/ui.js normalise
# names independently; if the two ever drift, dishes go quietly unorderable,
# and this is what turns that into a failing assertion instead.
needs = sorted({n for v in link.values() for n in ([v['p']] if v.get('p') else v.get('v', []))}
               | set(setlink.values()))
json.dump({'items': link, 'sets': setlink, 'needs': needs},
          open('menu_link.json', 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
with open('menu_link_audit.csv', 'w', newline='', encoding='utf-8') as fh:
    w = csv.writer(fh); w.writerow(['page_item', 'prod_product', 'how']); w.writerows(audit)

from collections import Counter
c = Counter(a[2] for a in audit)
print('page items       :', len(MENU))
for k in sorted(c): print('  %-18s %d' % (k, c[k]))
orderable = sum(1 for v in link.values() if not v.get('absent'))
print('orderable        : %d of %d' % (orderable, len(MENU)))
print('sets linked      : %d of %d' % (len(setlink), len(SETS)))
print('wrote menu_link.json + menu_link_audit.csv')
