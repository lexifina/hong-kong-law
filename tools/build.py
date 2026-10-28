"""Builds a git repository of Hong Kong law from the Department of Justice's open data (data.gov.hk), in which every
amending law is one commit, dated the day it took effect.

    python -X utf8 scripts/hong-kong-law/build.py [--repo ../hong-kong-law] [--today 2026-10-28] [--verify-rebuild]
                                                  [--sources <folder with the four bulk ZIPs>]

The Department of Justice publishes the Hong Kong e-Legislation (HKeL) as bulk files on DATA.GOV.HK: for every Cap.,
each dated version since 30 June 1997 as an XML file in the Hong Kong Legislation Model (HKLM). Each provision carries
a `sourceNote` naming the laws that added, amended or repealed it ("(Replaced 28 of 2012 s. 912. Amended 14 of 2016
s. 3)"), and a `startPeriod`, the day its present text began. We read every version of the acts below, compare
consecutive versions provision by provision, and credit a change to the law whose citation is new in that provision's
source notes. A change no new citation explains is never credited to a law: it gets a commit by the publisher,
labelled. Only the bulk files are read, from a local folder (--sources); the build makes no network requests.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
import zipfile
from collections import Counter
from pathlib import Path

from lxml import etree

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
# where the retrieved bulk files are; --sources sets another folder (through the environment, so the parse workers
# see it too)
CACHE = Path(os.environ['HK_SOURCES']) if os.environ.get('HK_SOURCES') else HERE / '.cache'
DATA_URL = 'https://resource.data.one.gov.hk/doj/data'
DATASET_URL = 'https://data.gov.hk/en-data/dataset/hk-doj-hkel-legislation-past'
TERMS_URL = 'https://data.gov.hk/en/terms-and-conditions'
COMMITTER = ('Lexifina', 'hong-kong-law@lexifina.com')
PUBLISHER = ('Department of Justice (HKeL)', 'hkel@hkel.invalid')
HISTORY_FROM = '1997-07-01'   # the establishment of the Hong Kong Special Administrative Region
NS = '{http://www.xml.gov.hk/schemas/hklm/1.0}'

# The bulk files of past versions (English). Every Cap. in them is in the record: ordinances (Cap. 486) and subsidiary
# legislation (Cap. 486A). Each Cap. is one act: its number, a folder name, and the bulk file that holds it.
ZIPS = ['hkel_p_leg_cap_1_cap_200_en.zip', 'hkel_p_leg_cap_201_cap_400_en.zip', 'hkel_p_leg_cap_401_cap_600_en.zip',
        'hkel_p_leg_cap_601_cap_end_en.zip']
MEMBER = re.compile(r'^cap_([0-9]+[A-Z]*)_en_p/cap_\1_(\d{4})(\d{2})(\d{2})(\d{6})_en_p\.xml$')
UNDATED = re.compile(r'^cap_([0-9]+[A-Z]*)_en_p/cap_\1_-+_en_p\.xml$')


def cap_order(cap: str) -> tuple:
    m = re.fullmatch(r'(\d+)([A-Z]*)', cap)
    return (int(m.group(1)), len(m.group(2)), m.group(2))


def discover(offline: bool) -> tuple[list[dict], list[dict]]:
    """Every Cap. with at least one dated version in the bulk files, in Cap. order; and the undated placeholder files
    ("will be incorporated ... as soon as possible"), which are not versions and are left out."""
    acts, undated = {}, []
    for name in ZIPS:
        z = open_zip(name)
        for n in z.namelist():
            m = MEMBER.match(n)
            if m:
                acts.setdefault(m.group(1), {'cap': m.group(1), 'slug': f'cap-{m.group(1).lower()}', 'zip': name})
            elif UNDATED.match(n):
                undated.append({'cap': UNDATED.match(n).group(1), 'member': n, 'zip': name})
    for u in undated:
        u['has_versions'] = u['cap'] in acts
    return sorted(acts.values(), key=lambda a: cap_order(a['cap'])), undated


ACTS: list[dict] = []


# ---------------------------------------------------------------- the bulk files

REQUESTS: list[dict] = []   # every file the build read, for REPRODUCE.md
_zips: dict[str, zipfile.ZipFile] = {}


def zip_path(name: str) -> Path:
    return CACHE / name


def open_zip(name: str, offline: bool = True) -> zipfile.ZipFile:
    """A retrieved bulk ZIP, read from the sources folder (the build never downloads; `offline` is kept for old
    callers). A `<name minus .zip>.headers` file next to it, if present, gives its Last-Modified."""
    if name in _zips:
        return _zips[name]
    path = zip_path(name)
    url = f'{DATA_URL}/{name}'
    if not path.exists():
        raise SystemExit(f'not in the sources folder ({path.parent}): {name}, from {url}')
    REQUESTS.append({'url': url, 'file': path})
    _zips[name] = zipfile.ZipFile(path)
    return _zips[name]


def zip_info(name: str) -> dict:
    """Size, sha256 (computed once, kept next to it) and the Last-Modified header of a bulk file."""
    meta = CACHE / (name + '.sha256.json')
    if meta.exists():
        return json.loads(meta.read_text(encoding='utf-8'))
    path = zip_path(name)
    h = hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
    heads = path.with_suffix('.headers')
    lm = ''
    if heads.exists():
        m = re.search(r'^last-modified:\s*(.+)$', heads.read_text(encoding='utf-8'), re.I | re.M)
        lm = m.group(1).strip() if m else ''
    info = {'name': name, 'url': f'{DATA_URL}/{name}', 'bytes': path.stat().st_size, 'sha256': h.hexdigest(),
            'last_modified': lm}
    meta.write_text(json.dumps(info, indent=1) + '\n', encoding='utf-8')
    return info


def clean(s: str) -> str:
    """Runs of white space (spaces, line breaks, tabs, no-break spaces) become one space. Nothing else changes."""
    return re.sub(r'[\s ]+', ' ', s).strip()


# ---------------------------------------------------------------- the act's versions

def versions(act: dict, offline: bool) -> list[dict]:
    """The act's dated versions in the bulk file, oldest first, then cut to the record: the newest version dated on or
    before 1 July 1997 stands for that day (the version of 30 June 1997 is the text before the handover and is not in
    the record when a version of 1 July 1997 exists), and every later version is a change."""
    z = open_zip(act['zip'])
    found = []
    for n in z.namelist():
        m = MEMBER.match(n)
        if m and m.group(1) == act['cap']:
            found.append({'member': n, 'date': f'{m.group(2)}-{m.group(3)}-{m.group(4)}', 'time': m.group(5)})
    found.sort(key=lambda v: (v['date'], v['time']))
    if not found:
        raise SystemExit(f'Cap. {act["cap"]} is not in {act["zip"]}')
    # Two files of one day (4 Caps have them: 000000 and 110000): the later one is the day's text, the earlier one is
    # left out of the record and listed.
    same_day = []
    kept = []
    for v in found:
        if kept and kept[-1]['date'] == v['date']:
            same_day.append(kept.pop()['member'])
        kept.append(v)
    found = kept
    for v in found:
        v['superseded_same_day'] = [s for s in same_day if f'_{v["date"].replace("-", "")}' in s]
    before = [v for v in found if v['date'] <= HISTORY_FROM]
    start = before[-1] if before else found[0]
    out = [v for v in found if v['date'] > start['date']]
    skipped = [v['date'] for v in before[:-1]]
    start = dict(start)
    start['in_force'] = max(start['date'], HISTORY_FROM)
    start['skipped_before'] = skipped
    for v in [start] + out:
        v.setdefault('in_force', v['date'])
    return [start] + out


# ---------------------------------------------------------------- reading one version

CONTAINERS = {'part', 'division', 'subdivision', 'chapter', 'crossHeading'}
UNITS = {'section', 'schedule'}
LEVELS = {'subsection', 'paragraph', 'subparagraph', 'subsubparagraph', 'def', 'section', 'part', 'division',
          'subdivision', 'item', 'proviso'}
BLOCKS = {'continued', 'p', 'editorialNote', 'statutoryNote', 'note', 'text', 'referenceNote'}
NOTE_PARENTS = {'editorialNote', 'statutoryNote', 'referenceNote'}
# Elements inside a line of text that join the words around them as printed ("m<sup>2</sup>", "<term>court</term>").
# Every other element (a paragraph, a table cell, a line break, a recital after its heading) separates words.
INLINE = {'ref', 'term', 'i', 'b', 'u', 'bold', 'inline', 'span', 'shortTitle', 'a', 'fillIn', 'sup', 'sub', 'ins', 'del'}


def ln(e) -> str:
    """An element's local name, in any namespace: HKLM elements, and the XHTML tables, paragraphs and line breaks the
    source mixes into them (<html:br/>, <html:table>)."""
    if not isinstance(e.tag, str):
        return ''
    return e.tag.rsplit('}', 1)[-1]


def itext(e) -> str:
    """All the text of an element as the page shows it: inline elements join the words around them, others separate
    them."""
    return ''.join(x if isinstance(x, str) else '' for x in _walk(e))


def _walk(e):
    yield e.text or ''
    for c in e:
        if isinstance(c.tag, str):
            if ln(c) in INLINE:
                yield from _walk(c)
            else:
                yield ' '   # a marker, a line break, a paragraph or cell inside a cell: words do not run together
                yield from _walk(c)
                yield ' '
        yield c.tail or ''


def ref_id(href: str | None):
    """A citation's identity from its link: 2012/18 -> ('ord', 2012, '18'); ln343 -> ('ln', 1996, '343'); er1 ->
    ('er', 2013, '1'). Links to Caps (cap486/s3) are not amending laws."""
    # Also G.N. and G.N.A. (government notices), and two misspelt links the source has (/hk/2012/s28 for 28 of 2012,
    # /hk/2017/3er for E.R. 3 of 2017).
    m = re.fullmatch(r'/?hk/(\d{4})/(ln|er|gna|gn|s)?(\d+)(er)?', (href or '').strip())
    if not m:
        return None
    kind = 'er' if m.group(4) else {None: 'ord', 's': 'ord'}.get(m.group(2), m.group(2))
    return (kind, int(m.group(1)), m.group(3))


def law_label(i: tuple) -> str:
    kind, y, n = i
    return {'ord': f'{n} of {y}', 'ln': f'L.N. {n} of {y}', 'er': f'E.R. {n} of {y}', 'gn': f'G.N. {n} of {y}',
            'gna': f'G.N.A. {n} of {y}', 'gne': f'G.N. (E.) {n} of {y}'}[kind]


def law_slug(i: tuple) -> str:
    return f'{i[0]}-{i[1]}-{i[2].lower()}'


def law_kind(i: tuple) -> str:
    return {'ord': 'Ordinance', 'ln': 'Legal notice', 'er': 'Editorial revision (E.R.), not an amending law',
            'gn': 'Government notice', 'gna': 'Government notice (G.N.A.)', 'gne': 'Government notice in the Gazette Extraordinary (G.N. (E.))'}[i[0]]


def law_order(i: tuple) -> tuple:
    return ({'ord': 0, 'ln': 1, 'gn': 2, 'gne': 3, 'gna': 4, 'er': 5}[i[0]], i[1], int(re.match(r'\d+', i[2]).group(0)), i[2])


def table_lines(x) -> list[str]:
    """One line per row of the table (HKLM or XHTML), cells separated by ' | '. A table inside a cell is part of that
    cell's text, not rows of its own. A table's caption is a line before its rows. A "|" printed in a cell is escaped
    ("\\|"), so it is not read as the separator."""
    rows = [clean(itext(c)) for c in x if isinstance(c.tag, str) and ln(c) == 'caption']
    rows = [r for r in rows if r]
    for tr in x.iter():
        if ln(tr) != 'tr' or next((a for a in tr.iterancestors() if ln(a) == 'table'), None) is not x:
            continue
        cells = [clean(itext(td)).replace('|', '\\|') for td in tr if isinstance(td.tag, str) and ln(td) in ('td', 'th')]
        row = ' | '.join(c for c in cells if c)
        if row:
            rows.append(row)
    return rows


def lines_of(e, depth: int, skip=(), skip_el=frozenset()) -> list[tuple[int, str]]:
    """The lines of an element, as (depth, text). A numbered level (subsection, paragraph, definition, ...) starts a
    line with its number and puts each level nested in it one deeper; a continuation, a note, a table row or a line
    break starts a line at the element's own depth. Inline elements (terms, citations, source notes, italics) join
    the words around them as the page shows them."""
    out: list[tuple[int, str]] = []
    buf: list[str] = []

    def flush():
        t = clean(''.join(buf)).replace('|', '\\|')   # a printed "|" is escaped: " | " separates table cells
        buf.clear()
        if t:
            out.append((depth, t))

    def inline(x):
        buf.append(x.text or '')
        for c in x:
            add(c)
            buf.append(c.tail or '')

    def add(c):
        if not isinstance(c.tag, str):
            return
        k = ln(c)
        if k in skip or c in skip_el:
            return
        if k == 'num':
            buf.append(itext(c) + ' ')
        elif k in LEVELS:
            flush()
            out.extend(lines_of(c, depth + 1))
        elif k in BLOCKS:
            flush()
            out.extend(lines_of(c, depth))
        elif k == 'table':
            flush()
            out.extend((depth, r) for r in table_lines(c))
        elif k == 'br':
            flush()
        elif k == 'marker':
            buf.append(' ')   # a blank-line marker separates the words around it
        elif k == 'content' and ln(c.getparent()) in NOTE_PARENTS:
            flush()   # the paragraphs of a note are lines of their own
            out.extend(lines_of(c, depth))
        elif k in INLINE:
            inline(c)
        else:   # leadIn, content, heading, a recital, a source note, a formula: its words do not run into the next
            buf.append(' ')
            inline(c)
            buf.append(' ')

    buf.append(e.text or '')
    for c in e:
        add(c)
        buf.append(c.tail or '')
    flush()
    return out


def render(lines: list[tuple[int, str]]) -> str:
    out = []
    for d, t in lines:
        if d == -2:
            out.append(f'# {t}')
        elif d == -1:
            out.append(f'## {t}')
        elif d <= 0:
            # A line of text that itself begins like a heading or a list item ("# Commencement date: ..." in an
            # editorial note) is escaped, so markdown shows the character and no reader takes it for a marker.
            out.append('\\' + t if re.match(r'#|- ', t) else t)
        else:
            out.append('  ' * (d - 1) + '- ' + t)
    return '\n\n'.join(out) + '\n'


def notes_of(e) -> Counter:
    """The citations in an element's source notes, as a multiset of (law, citation as printed)."""
    c: Counter = Counter()
    for sn in e.iter(NS + 'sourceNote'):
        if any(ln(a) == 'commencementNote' for a in sn.iterancestors()):
            continue   # a commencement notice (L.N. 343 of 1996) is not an amending law
        for r in sn.iter(NS + 'ref'):
            i = ref_id(r.get('href'))
            if i:
                c[(i, clean(itext(r)))] += 1
    return c


def unit_key(e) -> tuple[str, str, tuple]:
    """A provision's file key, label and sort key from its official identifier: s33 -> s-033 ('s. 33'), s2A -> s-002A,
    sch1 -> sch-1 ('Sch. 1')."""
    name = e.get('name') or ''
    m = re.fullmatch(r's(\d+)([A-Za-z]*)', name)
    if m and ln(e) == 'section':
        return f's-{int(m.group(1)):03d}{m.group(2)}', f's. {int(m.group(1))}{m.group(2)}', (1, int(m.group(1)), m.group(2))
    m = re.fullmatch(r'sch(\d*)([A-Za-z]*)', name)
    if m and ln(e) == 'schedule' and name == 'sch0' and not re.search(r'\d', itext(e.find(NS + 'num')) if e.find(NS + 'num') is not None else ''):
        return 'sch', 'Sch.', (2, 0, '')   # the only, unnumbered schedule
    if m and ln(e) == 'schedule':
        n = m.group(1)
        label = f'Sch. {n}{m.group(2)}' if n or m.group(2) else 'Sch.'
        return f'sch-{n}{m.group(2)}' if n or m.group(2) else 'sch', label, (2, int(n or 0), m.group(2))
    slug = re.sub(r'[^A-Za-z0-9]+', '-', name).strip('-') or 'x'
    return f'{ln(e)}-{slug}', f'{ln(e)} {name}', (3 if ln(e) == 'section' else 4, 0, slug)


def read_version(raw: bytes) -> dict:
    """One version as units in document order: the opening (long title, commencement, enacting words), each section and
    each schedule (with the headings of the parts and divisions that begin with it), and the closing matter. Each unit
    carries the citations of its source notes and the day its present text began (startPeriod)."""
    root = etree.fromstring(raw)
    main = root if ln(root) == 'main' else root.find(NS + 'main')   # one file (Cap. 139N, 2001-11-02) is a bare <main>
    units: dict[str, dict] = {}
    order: list[str] = []
    pending: list[tuple[int, str]] = []
    pending_notes: Counter = Counter()
    state = {'after': False}
    pending_start = [None]

    def unit(key, label, sort, start=None, status=None):
        base = key
        n = 2
        while key in units:
            key = f'{base}-dup{n}'
            n += 1
        u = {'key': key, 'label': label, 'sort': sort, 'lines': [], 'notes': Counter(), 'start': start, 'status': status, 'head_start': None}
        units[key] = u
        order.append(key)
        return u

    def loose(c):
        """Opening or closing matter: long title, commencement note, enacting formula, a note on the whole act. Matter
        between two provisions (a source note after a cross-heading) goes with the next provision, in its place, as
        headings do; only matter after the last provision is the closing matter."""
        if state['after']:
            pending.extend(lines_of(c, 0))
            pending_notes.update(notes_of(c))
            return
        else:
            u = units.get('intro') or unit('intro', 'Long title and commencement', (0, 0, ''), c.get('startPeriod'))
        u['lines'].extend(pending)
        u['notes'] += pending_notes
        pending.clear()
        pending_notes.clear()
        u['lines'].extend(lines_of(c, 0) if ln(c) in LEVELS else lines_of(c, 0))
        u['notes'] += notes_of(c)

    def provision(e):
        key, label, sort = unit_key(e)
        u = unit(key, label, sort, e.get('startPeriod'), e.get('status'))
        # The unit's head: its number and heading on one line when they are next to each other; when the source puts a
        # note between them (a schedule's "[ss. 2(1) & 5]"), the number, the note and the heading are three lines, in
        # the source's order.
        kids = [c for c in e if isinstance(c.tag, str)]
        hi = next((i for i, c in enumerate(kids) if ln(c) == 'heading'), None)
        lead = kids[:hi + 1] if hi is not None else [c for c in kids[:1] if ln(c) == 'num']
        mids = [c for c in lead if ln(c) not in ('num', 'heading', 'marker')]
        nums = [clean(itext(c)) for c in lead if ln(c) == 'num']
        heads = [clean(itext(c)) for c in lead if ln(c) == 'heading']
        if not mids:
            headlines = [(-2, ' '.join(h for h in nums + heads if h))]
        else:
            headlines = [(-2, ' '.join(nums))] + [l for m in mids for l in lines_of(m, 0)] + [(0, h) for h in heads if h]
        flat = any(ln(c) == 'subsection' for c in e)
        u['lines'] = pending[:] + headlines
        u['notes'] += pending_notes
        pending.clear()
        pending_notes.clear()
        body = lines_of(e, 0, skip_el=frozenset(lead))
        # Subsections are the provision's own paragraphs: they stay at the provision's level, as in the other corpora.
        u['lines'].extend((d - 1 if flat and d > 0 else d, t) for d, t in body)
        u['notes'] += notes_of(e)
        u['head_start'] = pending_start[0]
        pending_start[0] = None
        state['after'] = True

    def container(e):
        head = []
        for c in e:
            if isinstance(c.tag, str) and ln(c) in ('num', 'heading'):
                head.append(clean(itext(c)))
        # When the source puts a note between the number and the heading ("PART I (Added 51 of 1911) PRELIMINARY
        # PROVISIONS"), the number, the note and the heading are lines of their own, in the source's order.
        kids = [c for c in e if isinstance(c.tag, str)]
        ni = next((i for i, c in enumerate(kids) if ln(c) == 'num'), None)
        hi = next((i for i, c in enumerate(kids) if ln(c) == 'heading'), None)
        mids = [c for c in kids[ni + 1:hi] if ln(c) not in ('marker', 'br')] if ni is not None and hi is not None else []
        if mids:
            pending.append((-1, clean(itext(kids[ni]))))
            for m in mids:
                pending.extend(lines_of(m, 0))
                pending_notes.update(notes_of(m))
            pending.append((-1, clean(itext(kids[hi]))))
            pending_start[0] = max(filter(None, [pending_start[0], e.get('startPeriod')]), default=None)
        elif any(head):
            pending.append((-1, ' '.join(h for h in head if h)))
            pending_start[0] = max(filter(None, [pending_start[0], e.get('startPeriod')]), default=None)
        done = set(mids)
        # A container's own words, outside any child (a cross-heading printed as plain text, "PART V<marker/>SPECIAL
        # PROVISIONS ..."), are a heading line of their own, with the inline elements and markers among them.
        words = [e.text or '']

        def own():
            t = clean(''.join(words))
            words.clear()
            if t:
                pending.append((-1, t))
        for c in e:
            if not isinstance(c.tag, str):
                words.append(c.tail or '')
                continue
            k = ln(c)
            if k in ('num', 'heading') or c in done:
                pass
            elif k in INLINE:
                words.append(itext(c))
            elif k in ('marker', 'br'):
                words.append(' ')
            else:
                own()
                if k in UNITS:
                    provision(c)
                elif k in CONTAINERS:
                    container(c)
                else:   # a note on the part, a table, ...: it goes with the next provision, as its headings do
                    pending.extend(lines_of(c, 0))
                    pending_notes.update(notes_of(c))
            words.append(c.tail or '')
        own()

    for c in main:
        if not isinstance(c.tag, str):
            continue
        k = ln(c)
        if k in UNITS:
            provision(c)
        elif k in CONTAINERS:
            container(c)
        else:
            loose(c)
    if pending:
        u = units.get('outro') or unit('outro', 'Closing matter', (9, 0, ''))
        u['lines'].extend(pending)
        u['notes'] += pending_notes
    for k in order:
        units[k]['text'] = render(units[k]['lines'])
    short = main.find('.//' + NS + 'shortTitle')
    title = clean(itext(short)) if short is not None else ''
    meta = root.find(NS + 'meta')
    docname = clean(itext(meta.find(NS + 'docName'))) if meta is not None else ''
    return {'units': units, 'order': order, 'title': title, 'docname': docname}


def file_name(key: str) -> str:
    return f'{key}.md'


ORDER_FILE = 'order.txt'


def order_text(order: list[str]) -> bytes:
    """order.txt: the Cap.'s files in the order of the official text, one per line. The order cannot be read from the
    file names: newer Caps put s. 3AA before s. 3A, older ones after it."""
    return ''.join(file_name(k) + '\n' for k in order).encode('utf-8')


def unit_sort(u: dict) -> tuple:
    return u['sort']


def sort_keys(units: dict, keys) -> list[str]:
    return sorted(keys, key=lambda k: (units[k]['sort'], k))


# ---------------------------------------------------------------- one act: versions, changes, causes

def removal_only(a: str | None, b: str | None) -> bool:
    if a and b is None:
        return True
    return False


PARA = '\n\n'
MONTHS = ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October',
          'November', 'December']


def plain_citations(p: dict | None, c: dict | None, day: str, named: bool = True) -> set:
    """Laws cited as plain text (not as a linked source note) in the lines a version adds and nowhere in the provision's
    text before, when those lines also name the version's day in words ("On and from 18 July 1997, ... see ... (126 of
    1997 s.2)"; "G.N. (E.) 212 of 2020 (published on 23 November 2020)")."""
    if not c:
        return set()
    before = p['text'] if p else ''
    old = set(before.split(PARA))
    blob = ' '.join(l for l in c['text'].split(PARA) if l not in old)
    d = dt.date.fromisoformat(day)
    if named and f'{d.day} {MONTHS[d.month - 1]} {d.year}' not in blob:
        return set()
    # Without the day named (named=False, tried last): only a citation of the version's own year counts.
    return {i for i in cites_in(blob, d.year) - cites_in(before, d.year) if named or i[1] == d.year}


def cites_in(text: str, year: int) -> set:
    out = set()
    for m in re.finditer(r'\b(\d{1,4}) of (\d{4})\b', text):
        if int(m.group(2)) > year:
            continue
        kind = plain_kind(text[max(0, m.start() - 12):m.start()])
        if kind:
            out.add((kind, int(m.group(2)), m.group(1)))
    return out


def plain_kind(before: str) -> str | None:
    """The series of a citation printed in words, from what comes before its number: L.N., G.N., G.N. (E.), G.N.A.,
    E.R., or nothing (an Ordinance). Any other abbreviation (No., Cap.) is not a law citation."""
    for pat, kind in ((r'G\.N\.\s?\(E\.\)\s?$', 'gne'), (r'G\.N\.A\.\s?$', 'gna'), (r'G\.N\.\s?$', 'gn'),
                      (r'L\.N\.\s?$', 'ln'), (r'E\.R\.\s?$', 'er')):
        if re.search(pat, before):
            return kind
    if re.search(r'[.)]\s?$', before):
        return None
    return 'ord'


# An editorial note of a whole Cap. naming an editorial revision: "(Format changes—E.R. 3 of 2015)".
ER_NOTE = re.compile(r'—\s?E\.R\. (?:of )?(\d+) of (\d{4})')


def blob_id(data: bytes) -> str:
    return hashlib.sha1(b'blob %d\x00' % len(data) + data).hexdigest()


def build_act(act: dict, offline: bool) -> tuple[dict, dict]:
    """One Cap.: its versions read one after another (only two in memory at a time), the changes between them and their
    causes. Returns the Cap. with the provisions' texts replaced by git blob ids, and the blobs (id -> bytes)."""
    vs = versions(act, offline)
    z = open_zip(act['zip'])
    blobs: dict[str, bytes] = {}

    def load(v):
        raw = z.read(v['member'])
        parsed = read_version(raw)
        v['sha256'] = hashlib.sha256(raw).hexdigest()
        if parsed['title'] and not v.get('title'):
            v['title'] = parsed['title']
        data = order_text(parsed['order'])
        v['order_blob'] = blob_id(data)
        blobs[v['order_blob']] = data
        return parsed['units']

    def stub(u, text=False):
        s = {'label': u['label'], 'status': u['status'], 'notes': u['notes'], 'sort': u['sort']}
        if text:
            data = u['text'].encode('utf-8')
            s['blob'] = blob_id(data)
            blobs[s['blob']] = data
        return s

    first_units = load(vs[0])
    vs[0]['units'] = {k: stub(u, True) for k, u in first_units.items()}
    title = vs[0].get('title', '')
    changes = []
    problems = []
    seen: dict[str, set] = {}
    for k, u in first_units.items():
        seen[k] = {u['text']}
    prev = dict(vs[0], units=first_units)
    for vi in range(1, len(vs)):
        cur = dict(vs[vi], units=load(vs[vi]))
        title = title or vs[vi].get('title', '')
        day = cur['in_force']
        keys = set(prev['units']) | set(cur['units'])
        changed = sort_keys({**prev['units'], **cur['units']},
                            [k for k in keys if (prev['units'].get(k) or {}).get('text') != (cur['units'].get(k) or {}).get('text')])
        # Citations new anywhere in the act in this version. A citation of a law of a later year cannot be the cause of
        # a version of this year (HKeL prints later editorial revisions into earlier versions): it is ignored, labelled.
        year = int(day[:4])
        union: set = set()
        newids: dict[str, set] = {}
        later: dict[str, set] = {}
        # A citation that leaves one provision of the Cap. and appears, printed the same, in another (the revision of
        # 2015 moved "(2 of 2015 s. 73)" from the end of Cap. 138A into ss. 12, 19, ...) is moved, not new: only the
        # citations the whole Cap. prints more often than before can be new.
        cap_added = (sum((u['notes'] for u in cur['units'].values()), Counter())
                     - sum((u['notes'] for u in prev['units'].values()), Counter()))
        for k in keys:
            p, c = prev['units'].get(k), cur['units'].get(k)
            added = (c['notes'] if c else Counter()) - (p['notes'] if p else Counter())
            ids = {i for (i, t) in added if cap_added[(i, t)]}
            if ids and p:
                # A law the provision already printed (as plain text, "(L.N. 108 of 2015)") is not new when a later
                # version turns that text into a linked source note.
                ids -= cites_in(p['text'], 9999)
            newids[k] = {i for i in ids if i[1] <= year}
            later[k] = ids - newids[k]
            union |= newids[k]
        # An editorial revision day: exactly one E.R. is new in the version, and the text the version adds prints it in
        # an editorial note of the Cap. ("(Format changes—E.R. 3 of 2015)", "(Enacting provision omitted—E.R. 3 of
        # 2015)"). The other laws new in the version that the Cap. already cited in its previous version (in a source
        # note or in words) are citations the revision reprinted, not laws acting on the Cap. that day: they are left
        # out of the laws of the version, so a provision with no new source note that starts that day is credited to
        # the revision by date only. A provision whose own source notes newly cite a law is not affected.
        er_day = None
        ers = {i for i in union if i[0] == 'er'}
        if len(ers) == 1 and len(union) > 1:
            er = next(iter(ers))
            old_lines = {t for u in prev['units'].values() for t in u['text'].split(PARA)}
            printed = any(m and ('er', int(m.group(2)), m.group(1)) == er
                          for u in cur['units'].values() for t in u['text'].split(PARA) if t not in old_lines
                          for m in ER_NOTE.finditer(t))
            if printed:
                before = set()
                for u in prev['units'].values():
                    before |= {i for (i, _t) in u['notes']} | cites_in(u['text'], 9999)
                reprinted = (union - ers) & before
                if reprinted == union - ers:
                    er_day = {'er': er, 'reprinted': sorted(reprinted, key=law_order)}
                    union = {er}
        union_all = union | set(er_day['reprinted']) if er_day else union
        cause: dict[str, object] = {}
        why: dict[str, str] = {}
        flags: dict[str, list[str]] = {}
        for k in changed:
            p, c = prev['units'].get(k), cur['units'].get(k)
            ids = newids.get(k, set())
            dated = c is None or c['start'] == day or (c['head_start'] == day)
            plain = plain_citations(p, c, day) if not ids else set()
            if len(ids) == 1:
                cause[k], why[k] = next(iter(ids)), 'new source note'
            elif len(ids) > 1:
                cause[k], why[k] = ('candidates', tuple(sorted(ids, key=law_order))), 'two laws cited'
            elif len(plain) == 1:
                cause[k], why[k] = next(iter(plain)), 'plain citation'
            elif dated and len(union) == 1 and er_day:
                cause[k], why[k] = next(iter(union)), 'date only, editorial revision'
            elif dated and len(union) == 1:
                cause[k], why[k] = next(iter(union)), 'date only'
            elif dated and len(union) > 1:
                cause[k], why[k] = ('candidates', tuple(sorted(union, key=law_order))), 'two laws in this version'
            elif not ids and len(plain_citations(p, c, day, named=False)) == 1:
                cause[k], why[k] = next(iter(plain_citations(p, c, day, named=False))), 'plain citation, day not named'
            else:
                cause[k], why[k] = 'unexplained', 'no new source note, and the provision does not start on this day'
            fl = []
            if c and c['start'] and c['start'] > day:
                fl.append('startPeriod later than the version day')
            if c and c['text'] in seen.get(k, set()) and p and c['text'] != p['text']:
                fl.append('restores an earlier text')
            if later.get(k):
                fl.append('source note cites ' + ', '.join(law_label(i) for i in sorted(later[k], key=law_order))
                          + ', a later law, printed into this earlier version and ignored')
            if fl:
                flags[k] = fl
        for k, u in cur['units'].items():
            seen.setdefault(k, set()).add(u['text'])
        groups: dict[object, list[str]] = {}
        for k in changed:
            groups.setdefault(cause[k], []).append(k)
        for k in changed:
            if cause[k] == 'unexplained' or (isinstance(cause[k], tuple) and cause[k][0] == 'candidates'):
                problems.append(f'{day} {(cur["units"].get(k) or prev["units"][k])["label"]} ({why[k]})')
        pstub = {'units': {k: stub(prev['units'][k]) for k in changed if k in prev['units']}}
        cstub = {'member': cur['member'], 'sha256': cur['sha256'], 'date': cur['date'],
                 'units': {k: stub(cur['units'][k], True) for k in changed if k in cur['units']}}
        changes.append({'from': day, 'date': cur['date'], 'groups': groups, 'why': why, 'flags': flags, 'prev': pstub,
                        'cur': cstub, 'union': sorted(union_all, key=law_order),
                        'er_day': er_day,
                        'order_blob': cur['order_blob'] if cur['order_blob'] != prev['order_blob'] else None})
        prev = cur
    if len(vs) > 1:
        vs[-1]['units'] = {k: {'label': u['label'], 'sort': u['sort']} for k, u in prev['units'].items()}
    for v in vs[1:-1]:
        v.pop('units', None)
    return {'act': act, 'versions': vs, 'changes': changes, 'problems': problems, 'title': title,
            'label': f'Cap. {act["cap"]}', 'zipinfo': zip_info(act['zip'])}, blobs


def build_cap(args) -> tuple[dict, dict]:
    """A pool worker: one Cap."""
    act, offline = args
    return build_act(act, offline)


# ---------------------------------------------------------------- the git repository

def git(repo: Path, *args: str, env: dict | None = None, input: str | None = None) -> str:
    out = subprocess.run(['git', *args], cwd=repo, capture_output=True, text=True, encoding='utf-8', env=env, input=input)
    if out.returncode:
        raise SystemExit(f'git {" ".join(args)} failed: {out.stderr}')
    return out.stdout


def commit_date(day: str) -> str:
    """Noon in Hong Kong (UTC+8, no summer time since 1979) on the day. The record starts in 1997, so no date is
    before 1970."""
    d = dt.date.fromisoformat(day)
    stamp = int(dt.datetime(d.year, d.month, d.day, 12, tzinfo=dt.timezone(dt.timedelta(hours=8))).timestamp())
    return f'@{stamp} +0800'


def author_of(i: tuple) -> tuple[str, str]:
    return law_label(i), f'{law_slug(i)}@hkel.invalid'


def tag_of(i: tuple) -> str:
    return f'{i[0]}/{i[1]}-{i[2].lower()}'


def plan_commits(built: list[dict]) -> list[tuple]:
    """Every commit, sorted by day: the first version of each act first on its day, then one commit per amending law
    (ordinances, then legal notices, then editorial revisions), across all the acts it changed, then the changes
    credited to several candidate laws, then the changes nothing explains."""
    commits = []
    for ai, b in enumerate(built):
        commits.append((b['versions'][0]['in_force'], 0, (0,), ai, {'kind': 'start', 'b': b}))
        for ch in b['changes']:
            if not ch['groups']:
                commits.append((ch['from'], 3, (1,), ai, {'kind': 'unchanged', 'b': b, 'ch': ch, 'keys': []}))
    laws: dict[tuple, dict] = {}
    for ai, b in enumerate(built):
        for ch in b['changes']:
            for g, keys in ch['groups'].items():
                if isinstance(g, tuple) and g and g[0] == 'candidates':
                    commits.append((ch['from'], 2, tuple(law_order(i) for i in g[1]), ai,
                                    {'kind': 'candidates', 'b': b, 'ch': ch, 'laws': g[1], 'keys': keys}))
                elif g == 'unexplained':
                    commits.append((ch['from'], 3, (0,), ai, {'kind': 'unexplained', 'b': b, 'ch': ch, 'keys': keys}))
                else:
                    d = laws.setdefault((ch['from'], g), {'kind': 'law', 'law': g, 'parts': []})
                    d['parts'].append((b, ch, keys))
    for (day, law), d in laws.items():
        commits.append((day, 1, law_order(law), 0, d))
    commits.sort(key=lambda c: c[:4])
    return commits


def status_note(u: dict | None) -> str:
    return (u or {}).get('status') or ''


def change_kind(p: dict | None, c: dict | None) -> str:
    if p is None:
        return 'Added'
    if c is None:
        return 'Removed'
    if c['status'] == 'repealed' and p['status'] != 'repealed':
        return 'Repealed'
    if c['status'] == 'omitted' and p['status'] != 'omitted':
        return 'Omitted as spent'
    if c['status'] == 'operational' and p['status'] == 'pending':
        return 'Brought into operation'
    return 'Changed'


KIND_ORDER = ['Added', 'Changed', 'Brought into operation', 'Repealed', 'Omitted as spent', 'Removed']


def provisions_text(b: dict, ch: dict, keys: list[str]) -> tuple[list[str], list[str]]:
    """Listing lines (Added: s. 3, ...) and the labels, for the provisions of one act."""
    by_kind: dict[str, list[str]] = {}
    labels = []
    for k in keys:
        p, c = ch['prev']['units'].get(k), ch['cur']['units'].get(k)
        lab = (c or p)['label']
        labels.append(lab)
        by_kind.setdefault(change_kind(p, c), []).append(lab)
    listing = [f'{n}: {", ".join(by_kind[n])}' for n in KIND_ORDER if n in by_kind]
    return listing, labels


def new_citations(ch: dict, keys: list[str], law=None) -> list[str]:
    """The citations of the law as printed in the new source notes of these provisions (18 of 2012 s. 3)."""
    out = []
    for k in keys:
        p, c = ch['prev']['units'].get(k), ch['cur']['units'].get(k)
        added = (c['notes'] if c else Counter()) - (p['notes'] if p else Counter())
        for (i, t), n in sorted(added.items(), key=lambda x: (law_order(x[0][0]), x[0][1])):
            if law is None or i == law:
                if t not in out:
                    out.append(t)
    return out


def subject_for(parts: list[tuple[str, list[str]]], tail: str) -> str:
    """'Cap. 486 s. 2, s. 12 (18 of 2012)', shortened to 72 characters when needed (GitHub cuts longer subjects)."""
    def one(style):
        out = []
        for cap, labs in parts:
            if not labs:
                out.append(f'{cap} no words')
            elif style == 0:
                out.append(f'{cap} {", ".join(labs)}')
            elif style == 1 and all(l.startswith('s. ') for l in labs):
                out.append(f'{cap} ss. {", ".join(l[3:] for l in labs)}')
            else:
                out.append(f'{cap}: {len(labs)} provisions')
        return ' / '.join(out) + f' ({tail})'
    for style in (0, 1, 2):
        if len(one(style)) <= 72:
            return one(style)
    n = sum(len(labs) for _cap, labs in parts)
    if len(parts) == 1:
        return f'{parts[0][0]}: {n} provisions ({tail})'
    return f'{len(parts)} Caps., {n} provisions ({tail})'


def source_trailers(b: dict, ch_cur: dict) -> list[str]:
    return [f'Consolidated: {b["act"]["zip"]}:{ch_cur["member"]} (sha256 {ch_cur["sha256"][:16]})']


def wrap(text: str) -> list[str]:
    import textwrap
    return textwrap.wrap(text, 110)


def law_message(d: dict, day: str):
    law = d['law']
    parts = []
    msg_body = []
    trailers = []
    affecting = []
    cites: list[str] = []
    evidence = []
    flags = []
    for b, ch, keys in d['parts']:
        listing, labels = provisions_text(b, ch, keys)
        parts.append((b['label'], labels))
        msg_body += [f'{b["label"]} {b["title"]}', ''] + listing + ['']
        affecting += [f'{b["label"]} {l}' for l in labels]
        for c in new_citations(ch, keys, law):
            if c not in cites:
                cites.append(c)
        if [k for k in keys if ch['why'][k] == 'new source note']:
            evidence.append(f'{b["label"]}: the citation is new in the source notes of '
                            + ', '.join((ch['cur']['units'].get(k) or ch['prev']['units'][k])['label'] for k in keys if ch['why'][k] == 'new source note'))
        plain = [k for k in keys if ch['why'][k] == 'plain citation']
        if plain:
            names = ', '.join((ch['cur']['units'].get(k) or ch['prev']['units'][k])['label'] for k in plain)
            evidence.append(f'the added text of {b["label"]} {names} cites this law in words and names this day (not a linked source note)')
        plain2 = [k for k in keys if ch['why'][k] == 'plain citation, day not named']
        if plain2:
            names = ', '.join((ch['cur']['units'].get(k) or ch['prev']['units'][k])['label'] for k in plain2)
            evidence.append(f'plain citation only: the added text of {b["label"]} {names} cites this law in words, the only '
                            'law of this year it newly cites (not a linked source note; the text does not name this day)')
        dated = [k for k in keys if ch['why'][k] == 'date only']
        if dated:
            names = ', '.join((ch['cur']['units'].get(k) or ch['prev']['units'][k])['label'] for k in dated)
            evidence.append(f'date only for {b["label"]} {names} (no new source note; the provision starts on this day and this is the only law cited anywhere in the version)')
            msg_body += wrap(f'No new source note explains {b["label"]} {names}. The source gives the provision a start date of '
                             'this day, and this law is the only one cited as new anywhere in the version of this day, so the '
                             'change is credited to it by date only.') + ['']
        erd = [k for k in keys if ch['why'][k] == 'date only, editorial revision']
        if erd:
            names = ', '.join((ch['cur']['units'].get(k) or ch['prev']['units'][k])['label'] for k in erd)
            rep = ', '.join(law_label(i) for i in ch['er_day']['reprinted'])
            evidence.append(f'date only, editorial revision, for {b["label"]} {names} (no new source note; the provision '
                            f'starts on this day; the version prints a note of this revision on the Cap., and the other laws '
                            f'newly cited in it, {rep}, were already cited in the Cap. before)')
            msg_body += wrap(f'No new source note explains {b["label"]} {names}. The source gives the provision a start date of '
                             f'this day, the version of this day prints a note of this editorial revision on the Cap., and '
                             f'the only other laws it newly cites ({rep}) were already cited in the Cap. before this day, '
                             'so they are reprinted citations, not laws acting on it. The change is credited to the revision '
                             'by date only.') + ['']
        for k in keys:
            for f in ch['flags'].get(k, []):
                flags.append(f'{b["label"]} {(ch["cur"]["units"].get(k) or ch["prev"]["units"][k])["label"]}: {f}')
    subject = subject_for(parts, law_label(law))
    first = (f'Editorial revision {law_label(law)} (not an amending law).' if law[0] == 'er'
             else f'{law_kind(law)} {law_label(law)}.')
    msg = [subject, '', first, ''] + msg_body
    if law[0] == 'er':
        msg += wrap('An editorial revision is a revised printing of the text made by the Department of Justice, not an act of the '
                    'legislature: it changes how the text is printed (format, numbering, omission of spent provisions). It is '
                    'credited as its own author because it is what changed these files, not as an amending law.') + ['']
    for f in flags:
        msg += [f'Note: {f}.']
    if flags:
        msg += ['']
    trailers += [f'Kind: {law_kind(law)}']
    trailers += [f'Cited: {c}' for c in cites]
    trailers += [f'Evidence: {e}' for e in evidence]
    trailers += [f'In-force: {day}']
    trailers += [f'Affecting: {a}' for a in affecting]
    trailers += [f'Date-note: {f}' for f in flags]
    for b, ch, keys in d['parts']:
        trailers += source_trailers(b, ch['cur'])
    trailers += [f'Source: {DATASET_URL}']
    return author_of(law), msg, trailers, parts


def start_message(b: dict, day: str):
    v = b['versions'][0]
    author = (f'{b["label"]} (text on 1 July 1997)' if v['in_force'] == HISTORY_FROM else f'{b["label"]} (first version)',
              f'cap-{b["act"]["cap"]}@hkel.invalid')
    subject = f'{b["label"]}: {b["title"]}'
    if len(subject.encode('utf-8')) > 72:   # GitHub cuts longer subjects: the full title opens the body
        import textwrap
        width = 72
        while len(subject.encode('utf-8')) > 72:
            subject = textwrap.shorten(f'{b["label"]}: {b["title"]}', width, placeholder='...')
            width -= 1
        msg = [subject, '', f'{b["label"]} {b["title"]}.', '']
    else:
        msg = [subject, '']
    if v['in_force'] == HISTORY_FROM:
        msg += [f'The text in force on {day}, the first day of the Hong Kong Special Administrative Region: the first',
                'version of this record. The history before that day is not recorded here, and the source names no',
                'amending law for it.', '']
    else:
        msg += [f'The first version of this Cap. in the bulk file, in force from {day}.', '']
    if v['skipped_before']:
        msg += [f'Not in the record: the version of {", ".join(v["skipped_before"])} (text before the handover).', '']
    trailers = ['Kind: Baseline', f'In-force: {day}', f'Source: {DATASET_URL}'] + source_trailers(b, v)
    return author, msg, trailers


def candidate_message(c: dict, day: str):
    b, ch, laws, keys = c['b'], c['ch'], c['laws'], c['keys']
    listing, labels = provisions_text(b, ch, keys)
    names = ', '.join(law_label(i) for i in laws)
    subject = subject_for([(b['label'], labels)], f'candidates: {names}')
    if len(subject) > 72:
        subject = f'{b["label"]}: {len(labels)} provisions (candidates)'
    msg = [subject, '',
           f'These laws are candidates for the change: {names}. The source gives the provisions a new text from this day',
           'and cites more than one law for it (in the provisions themselves, or, where they cite none, among the laws',
           'new in this version), and does not say which law changed which provision. The change is credited to none of',
           'them.', ''] + listing + ['']
    for i in laws:
        msg.append(f'- {law_label(i)} ({law_kind(i)})')
    msg.append('')
    trailers = ['Kind: Change with several candidate laws', f'In-force: {day}'] + [f'Affecting: {b["label"]} {l}' for l in labels]
    trailers += [f'Candidate: {law_label(i)}' for i in laws]
    trailers += [f'Date-note: {b["label"]} {(ch["cur"]["units"].get(k) or ch["prev"]["units"][k])["label"]}: {f}'
                 for k in keys for f in ch['flags'].get(k, [])]
    trailers += source_trailers(b, ch['cur']) + [f'Source: {DATASET_URL}']
    return PUBLISHER, msg, trailers


def unexplained_message(c: dict, day: str):
    b, ch, keys = c['b'], c['ch'], c['keys']
    listing, labels = provisions_text(b, ch, keys)
    subject = subject_for([(b['label'], labels)], 'no law cited')
    if len(subject) > 72:
        subject = f'{b["label"]}: {len(labels)} provisions (no law cited)'
    msg = [subject, '',
           'The text in the source changed on this day, but no source note of these provisions gives a new citation and',
           'the source does not date them to this day, so the change is credited to no law.', ''] + listing + ['']
    trailers = ['Kind: Change no law explains', f'In-force: {day}'] + [f'Affecting: {b["label"]} {l}' for l in labels]
    trailers += [f'Date-note: {b["label"]} {(ch["cur"]["units"].get(k) or ch["prev"]["units"][k])["label"]}: {f}'
                 for k in keys for f in ch['flags'].get(k, [])]
    trailers += [f'Version-laws: {", ".join(law_label(i) for i in ch["union"]) or "none"}']
    trailers += source_trailers(b, ch['cur']) + [f'Source: {DATASET_URL}']
    return PUBLISHER, msg, trailers


def unchanged_message(c: dict, day: str):
    b, ch = c['b'], c['ch']
    msg = [f'{b["label"]}: version of {day}, same English text (no change)', '',
           f'The bulk file has a version of {b["label"]} dated {day} whose English text is word for word the text of the',
           f'version before it (it differs only in the date in its metadata). The source does not say why a new version',
           'was made (for example, a change in the Chinese text); nothing in the English text is credited to any law.', '']
    trailers = ['Kind: Version with no change to the English text', f'In-force: {day}'] + source_trailers(b, ch['cur'])
    trailers += [f'Source: {DATASET_URL}']
    return PUBLISHER, msg, trailers


class FastImport:
    """git fast-import, fed bytes only (no newline translation, so no CR ever reaches a message)."""

    def __init__(self, repo: Path):
        self.p = subprocess.Popen(['git', 'fast-import', '--quiet', '--done'], cwd=repo, stdin=subprocess.PIPE)
        self.marks = 0
        self.blobs: dict[str, int] = {}

    def w(self, b: bytes):
        self.p.stdin.write(b)

    def blob(self, sha: str, data: bytes):
        if sha in self.blobs:
            return
        self.marks += 1
        self.blobs[sha] = self.marks
        self.w(b'blob\nmark :%d\ndata %d\n' % (self.marks, len(data)) + data + b'\n')

    def commit(self, author: tuple[str, str], when: str, message: str, ops: list[tuple[str, str | None]],
               parent: int | None) -> int:
        self.marks += 1
        msg = message.encode('utf-8')
        stamp = when.lstrip('@')
        out = [b'commit refs/heads/main\nmark :%d\n' % self.marks,
               f'author {author[0]} <{author[1]}> {stamp}\n'.encode('utf-8'),
               f'committer {COMMITTER[0]} <{COMMITTER[1]}> {stamp}\n'.encode('utf-8'),
               b'data %d\n' % len(msg), msg, b'\n']
        if parent:
            out.append(b'from :%d\n' % parent)
        for path, sha in ops:
            if sha is None:
                out.append(f'D {path}\n'.encode('utf-8'))
            else:
                out.append(f'M 100644 :{self.blobs[sha]} {path}\n'.encode('utf-8'))
        out.append(b'\n')
        self.w(b''.join(out))
        return self.marks

    def tag(self, name: str, mark: int):
        self.w(f'reset refs/tags/{name}\nfrom :{mark}\n\n'.encode('utf-8'))

    def close(self):
        self.w(b'done\n')
        self.p.stdin.close()
        if self.p.wait():
            raise SystemExit('git fast-import failed')


def fresh_repo(repo: Path):
    """The history is rebuilt from scratch each time (it is deterministic), keeping the remote it is pushed to. Git
    marks its object files read-only, which Windows will not delete without clearing the flag first."""
    remote = None
    if (repo / '.git').exists():
        out = subprocess.run(['git', 'remote', 'get-url', 'origin'], cwd=repo, capture_output=True, text=True)
        remote = out.stdout.strip() or None

    def force(fn, path, _exc):
        os.chmod(path, 0o700)
        fn(path)
    if repo.exists():
        if (repo / '.git').exists() or not any(repo.iterdir()):
            for p in repo.iterdir():
                shutil.rmtree(p, onexc=force) if p.is_dir() else p.unlink()
        else:
            raise SystemExit(f'{repo} exists and is not an earlier build of this repository; refusing to use it')
    repo.mkdir(parents=True, exist_ok=True)
    git(repo, 'init', '-q', '-b', 'main')
    git(repo, 'config', 'core.autocrlf', 'false')
    if remote:
        git(repo, 'remote', 'add', 'origin', remote)


def read_all(acts: list[dict], offline: bool, fi: FastImport, workers: int) -> list[dict]:
    """Every Cap., read by a pool of parse workers in Cap. order; each Cap.'s texts go to fast-import as blobs as soon
    as it is read, so only the Caps' metadata stays in memory."""
    import multiprocessing as mp
    built = []
    t0 = dt.datetime.now()
    with mp.Pool(workers) as pool:
        for i, (b, blobs) in enumerate(pool.imap(build_cap, [(a, offline) for a in acts], chunksize=1)):
            for sha in sorted(blobs):
                fi.blob(sha, blobs[sha])
            built.append(b)
            if (i + 1) % 100 == 0 or i + 1 == len(acts):
                print(f'  read {i + 1}/{len(acts)} Caps ({(dt.datetime.now() - t0).seconds}s)', flush=True)
    return built


def write_history(fi: FastImport, built: list[dict]) -> tuple[list[dict], dict]:
    tags: dict[str, int] = {}
    law_days: dict[tuple, list[tuple[str, int]]] = {}
    log = []
    parent = None
    plan = plan_commits(built)
    # order.txt of a Cap. changes with the last of its commits of the day, when the version's order is new.
    last: dict[tuple[str, str], int] = {}
    order_of: dict[tuple[str, str], str | None] = {}
    for idx, (day, _r, _o, _ai, c) in enumerate(plan):
        if c['kind'] == 'start':
            pairs = [(c['b'], None)]
        elif c['kind'] == 'law':
            pairs = [(b, ch) for b, ch, _k in c['parts']]
        else:
            pairs = [(c['b'], c['ch'])]
        for b, ch in pairs:
            key = (b['act']['slug'], day)
            last[key] = idx
            order_of[key] = b['versions'][0]['order_blob'] if ch is None else ch['order_blob']
    for idx, (day, rank, _o, _ai, c) in enumerate(plan):
        touched: list[tuple[dict, list[str], bool]] = []
        ops: list[tuple[str, str | None]] = []
        if c['kind'] == 'start':
            b = c['b']
            for key, u in sorted(b['versions'][0]['units'].items()):
                ops.append((f'{b["act"]["slug"]}/{file_name(key)}', u['blob']))
            author, msg, trailers = start_message(b, day)
            touched.append((b, list(b['versions'][0]['units']), True))
            law = None
        elif c['kind'] == 'law':
            law = c['law']
            author, msg, trailers, _p = law_message(c, day)
            for b, ch, keys in c['parts']:
                for k in keys:
                    u = ch['cur']['units'].get(k)
                    ops.append((f'{b["act"]["slug"]}/{file_name(k)}', u['blob'] if u else None))
                touched.append((b, keys, False))
        else:
            law = None
            b, ch, keys = c['b'], c['ch'], c['keys']
            author, msg, trailers = {'candidates': candidate_message, 'unexplained': unexplained_message,
                                     'unchanged': unchanged_message}[c['kind']](c, day)
            for k in keys:
                u = ch['cur']['units'].get(k)
                ops.append((f'{b["act"]["slug"]}/{file_name(k)}', u['blob'] if u else None))
            touched.append((b, keys, False))
        for b, _k, _s in touched:
            key = (b['act']['slug'], day)
            if last[key] == idx and order_of[key]:
                ops.append((f'{b["act"]["slug"]}/{ORDER_FILE}', order_of[key]))
        message = '\n'.join(msg).rstrip('\n') + '\n\n' + '\n'.join(trailers) + '\n'
        parent = fi.commit(author, commit_date(day), message, ops, parent)
        for b, _k, _s in touched:
            tags[f'{b["act"]["slug"]}/{day}'] = parent
        if law is not None:
            law_days.setdefault(law, []).append((day, parent))
        log.append({'day': day, 'kind': c['kind'], 'law': law_label(law) if law else None, 'author': author[0],
                    'caps': [b['label'] for b, _k, _s in touched], 'units': sum(len(k) for _b, k, _s in touched)})
    for law, days in law_days.items():
        if len(days) == 1:
            tags[tag_of(law)] = days[0][1]
        else:
            for day, mark in days:
                tags[f'{tag_of(law)}/{day}'] = mark
    for name in sorted(tags):
        fi.tag(name, tags[name])
    return log, tags


def write_repo(repo: Path, acts: list[dict], offline: bool, docs: Path, today: str, workers: int,
               undated: list[dict]) -> tuple[list[dict], list[dict], dict]:
    fresh_repo(repo)
    fi = FastImport(repo)
    built = read_all(acts, offline, fi, workers)
    report(built)
    log, tags = write_history(fi, built)
    fi.close()
    git(repo, 'checkout', '-q', '-f', 'main')
    # Documentation, tables, the build scripts and the record of how it was made come last, by Lexifina, dated the
    # day the data was retrieved, so the same data gives the same hashes on any later day.
    for p in sorted(docs.rglob('*')):
        if p.is_file() and '__pycache__' not in p.parts:
            dest = repo / p.relative_to(docs)
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(p.read_bytes())
    (repo / 'tools').mkdir(exist_ok=True)
    for name in ('build.py', 'reproduce.py', 'check_repo.py', 'test_repo.py'):
        (repo / 'tools' / name).write_bytes((HERE / name).read_bytes())
    write_tables(repo, built)
    from reproduce import write_corpus, write_manifest, write_reproduce
    write_manifest(repo, built, today, undated)
    write_corpus(repo, built, today)
    write_reproduce(repo, built, log, tags, REQUESTS, today, undated)
    gate(repo)
    git(repo, 'add', '-A')
    when = commit_date(today)
    env = {**os.environ, 'GIT_AUTHOR_NAME': COMMITTER[0], 'GIT_AUTHOR_EMAIL': COMMITTER[1], 'GIT_AUTHOR_DATE': when,
           'GIT_COMMITTER_NAME': COMMITTER[0], 'GIT_COMMITTER_EMAIL': COMMITTER[1], 'GIT_COMMITTER_DATE': when}
    msg = (b'Documentation, tables, tools, corpus.json and REPRODUCE.md\n\nNo law text changes.\n\n'
           + f'In-force: {today}\nKind: documentation\n'.encode('utf-8'))
    out = subprocess.run(['git', 'commit', '-q', '--cleanup=verbatim', '-F', '-'], cwd=repo, env=env, input=msg,
                         capture_output=True)
    if out.returncode:
        raise SystemExit(f'git commit failed: {out.stderr.decode(errors="replace")}')
    return built, log, tags


def gate(repo: Path):
    """Every non-law file of the documentation commit (top-level files, tools/, data/) goes through publish_gate
    (Lexifina's private rule of 2026-10-29: no retrieval detail, no fetch code, no home paths) before it is committed.
    The Caps' own folders are law and are never passed to it."""
    sys.path.insert(0, str(HERE.parent / 'gitlaw_common'))
    try:
        from publish_gate import publish_gate
    except ImportError:          # an outside reader rebuilding from the published tools: no private rule to apply
        if os.environ.get('GITLAW_PUBLIC_REBUILD') != '1':
            raise SystemExit('publish gate missing: run from lexifina/scripts, or set GITLAW_PUBLIC_REBUILD=1')

        def publish_gate(files): return files
    paths = [p for p in repo.iterdir() if p.is_file()]
    paths += [p for d in ('tools', 'data') if (repo / d).is_dir() for p in (repo / d).rglob('*') if p.is_file()]
    files = {p.relative_to(repo).as_posix(): p.read_bytes() for p in sorted(paths)}
    out = publish_gate(files)
    for name, data in out.items():
        if data != files[name]:
            (repo / name).write_bytes(data)


def report(built: list[dict]):
    total = sum(len(b['versions']) for b in built)
    n = sum(len(ks) for b in built for ch in b['changes'] for ks in ch['groups'].values())
    probs = sum(len(b['problems']) for b in built)
    print(f'{len(built)} Caps, {total} versions, {n} file changes, {probs} not credited to one law', flush=True)


def write_tables(repo: Path, built: list[dict]):
    """laws.csv: every law the record credits, with the days it took effect and what it changed."""
    import csv
    rows: dict[tuple, dict] = {}
    for b in built:
        for ch in b['changes']:
            for g, keys in ch['groups'].items():
                if isinstance(g, tuple) or g == 'unexplained':
                    continue
                r = rows.setdefault((ch['from'], law_order(g), g), {'law': law_label(g), 'kind': law_kind(g), 'in_force': ch['from'],
                                                                   'caps': {}, 'cited': []})
                r['caps'][b['label']] = r['caps'].get(b['label'], 0) + len(keys)
                for t in new_citations(ch, keys, g):
                    if t not in r['cited']:
                        r['cited'].append(t)
    out = []
    for (_d, _o, _g), r in sorted(rows.items(), key=lambda x: (x[0][0], x[0][1])):
        out.append({'law': r['law'], 'kind': r['kind'], 'in_force': r['in_force'],
                    'provisions': '; '.join(f'{c}: {n}' for c, n in r['caps'].items()), 'cited_as': '; '.join(r['cited'])})
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=['law', 'kind', 'in_force', 'provisions', 'cited_as'], lineterminator='\n')
    w.writeheader()
    w.writerows(out)
    (repo / 'laws.csv').write_text(buf.getvalue(), encoding='utf-8', newline='\n')
    for b in built:
        last = b['versions'][-1]
        counts: dict[str, int] = {}
        lastday: dict[str, str] = {}
        for ch in b['changes']:
            for keys in ch['groups'].values():
                for k in keys:
                    counts[k] = counts.get(k, 0) + 1
                    lastday[k] = ch['from']
        lines = [f'# {b["label"]}: {b["title"]}', '',
                 f'{len(b["versions"])} versions in the record, in force from {b["versions"][0]["in_force"]} '
                 f'(the last from {last["in_force"]}).', '',
                 '| Provision | File | Changes | Last changed |', '| --- | --- | ---: | --- |']
        for k in last['units']:   # the order of the official text, as in order.txt
            u = last['units'][k]
            lines.append(f'| {u["label"]} | [{file_name(k)}]({file_name(k)}) | {counts.get(k, 0)} | {lastday.get(k, "")} |')
        (repo / b['act']['slug'] / 'README.md').write_text('\n'.join(lines) + '\n', encoding='utf-8', newline='\n')


# ---------------------------------------------------------------- main

def data_day() -> str:
    """The day the source data was retrieved (the newest bulk file), so the documentation commit made by a
    rebuild on any later day carries the same date."""
    files = [zip_path(z) for z in ZIPS if zip_path(z).exists()]
    if not files:
        return dt.date.today().isoformat()
    return dt.date.fromtimestamp(max(p.stat().st_mtime for p in files)).isoformat()


def select(acts: list[dict], caps: str | None) -> list[dict]:
    """--caps 383,486,1A: only these Caps (a sample build for testing); default every Cap."""
    if not caps:
        return acts
    want = {c.strip().upper() for c in caps.split(',') if c.strip()}
    out = [a for a in acts if a['cap'] in want]
    missing = want - {a['cap'] for a in out}
    if missing:
        raise SystemExit(f'not in the bulk files: {sorted(missing)}')
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--repo', default=str(ROOT.parent / 'hong-kong-law'))
    ap.add_argument('--offline', action='store_true', help=argparse.SUPPRESS)   # kept for old commands: a no-op
    ap.add_argument('--sources', default=None, help='the folder holding the four bulk ZIPs (default: next to this script)')
    ap.add_argument('--today', default=None, help='the build day (default: the day the data was retrieved)')
    ap.add_argument('--caps', default=None, help='only these Caps, comma-separated (a sample build); default all')
    ap.add_argument('--workers', type=int, default=4, help='parse workers (at most 8)')
    ap.add_argument('--verify-rebuild', action='store_true',
                    help='build again into a temporary folder from the same bulk files, compare every hash with --repo, and record the result')
    args = ap.parse_args()
    workers = max(1, min(8, args.workers))
    if args.sources:
        global CACHE
        CACHE = Path(args.sources).resolve()
        os.environ['HK_SOURCES'] = str(CACHE)
    if args.verify_rebuild:
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            out = subprocess.run([sys.executable, '-X', 'utf8', str(HERE / 'build.py'), '--repo', tmp,
                                  '--workers', str(workers)]
                                 + (['--sources', args.sources] if args.sources else [])
                                 + (['--today', args.today] if args.today else [])
                                 + (['--caps', args.caps] if args.caps else []), capture_output=True, text=True)
            if out.returncode:
                raise SystemExit(out.stderr)

            def hashes(r):
                log = git(Path(r), 'log', '--format=%H', 'main').split()
                tags = dict(l.split(' ', 1)[::-1] for l in git(Path(r), 'show-ref', '--tags').split('\n') if l)
                return log, tags
            a, b = hashes(args.repo), hashes(tmp)
            same_history = a[0][1:] == b[0][1:]
            rec = {'identical': same_history and a[1] == b[1], 'history_tip': a[0][1], 'commits': len(a[0]) - 1,
                   'tags': len(a[1]), 'main_identical': a[0][0] == b[0][0], 'main': a[0][0], 'rebuilt_main': b[0][0]}
            print(json.dumps(rec, indent=1))
            if not args.caps:
                p = HERE / 'verification.json'
                ver = json.loads(p.read_text(encoding='utf-8')) if p.exists() else {}
                ver['rebuild'] = {k: rec[k] for k in ('identical', 'history_tip', 'commits', 'tags')}
                p.write_text(json.dumps(ver, indent=1, sort_keys=True) + '\n', encoding='utf-8', newline='\n')
            for f in Path(tmp).rglob('*'):
                os.chmod(f, 0o700)
            raise SystemExit(0 if rec['identical'] else 1)
    acts, undated = discover(args.offline)
    acts = select(acts, args.caps)
    for z in ZIPS:
        zip_info(z)   # once, before the workers read the record
    today = args.today or data_day()
    built, log, tags = write_repo(Path(args.repo), acts, args.offline, HERE / 'repo', today, workers, undated)
    probs = [f'{b["label"]} {p}' for b in built for p in b['problems']]
    (HERE / 'scratch').mkdir(exist_ok=True)
    (HERE / 'scratch' / 'problems.txt').write_text('\n'.join(probs) + '\n', encoding='utf-8', newline='\n')
    print(f'repo: {len(log)} commits + 1 documentation commit, {len(tags)} tags -> {args.repo}')


if __name__ == '__main__':
    main()
