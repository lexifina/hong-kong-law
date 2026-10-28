"""Checks the git repository against the official text: every version of every Cap. in the Department of Justice's bulk
files, read back from git on the day it took effect, must equal that version's official text.

    python -X utf8 scripts/hong-kong-law/check_repo.py [--repo ../hong-kong-law] [--caps 383,486] [--no-record]

Three checks per version, from the bulk ZIPs in the cache (no network), run by a pool of 4 workers:
1. File by file: the Cap.'s files in git on that day (the last commit touching the Cap. whose In-force day is on or
   before it, as tools/hkhistory.py reads it) are exactly the files the build's parser makes from that version's XML
   (same set of files, same bytes).
2. Word for word: the whole Cap. as tools/hkhistory.py prints it (files in its order), with its markdown marks removed,
   has the same words and punctuation in the same order as the whole official text, read independently of the parser
   (every text node under <main>).
3. Letters and digits: the same two texts, casefolded, with everything but letters and digits removed, are equal.
The tool itself is then run on a few provisions at several dates. The result is written to verification.json next to
this script (unless --no-record or --caps), for REPRODUCE.md.
"""
import argparse
import json
import multiprocessing as mp
import re
import subprocess
import sys
from pathlib import Path

from lxml import etree

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import build  # noqa: E402

TOKEN = re.compile(r'\w+|[^\w\s]')
INLINE = {'ref', 'term', 'i', 'b', 'u', 'bold', 'inline', 'span', 'shortTitle', 'a', 'fillIn', 'sup', 'sub', 'ins', 'del'}


def official_text(raw: bytes) -> str:
    """All the text of the Cap. as the XML has it: every text node under <main>. Inline elements join the words around
    them; every other element separates words."""
    root = etree.fromstring(raw)
    main = root if etree.QName(root).localname == 'main' else root.find(build.NS + 'main')

    def text(e) -> str:
        if not isinstance(e.tag, str):
            return e.tail or ''
        k = etree.QName(e).localname
        gap = '' if k in INLINE else ' '
        return gap + (e.text or '') + ''.join(text(c) for c in e) + gap + (e.tail or '')
    main.tail = None
    return text(main).replace(' ', ' ')


def repo_text(text: str) -> str:
    lines = []
    for l in text.split('\n'):
        l = re.sub(r'^\s*(#+ |- )', '', l)
        l = re.sub(r'^\\(?=#|- )', '', l)   # a line of text that begins like a marker is escaped in the file
        # the separator between the cells of a table row; a "|" printed in a cell is escaped in the file
        lines.append(l.replace(' | ', ' ').replace('\\|', '|'))
    return ' '.join(lines)


def letters(s: str) -> str:
    return ''.join(c for c in s.casefold() if c.isalnum())


def order(path: str) -> tuple:
    """The order in which tools/hkhistory.py prints a Cap.'s files (the same function)."""
    name = path.split('/', 1)[1][:-3]
    if name == 'intro':
        return (0, 0, '')
    m = re.fullmatch(r's-(\d+)([A-Za-z]*)', name)
    if m:
        return (1, int(m.group(1)), m.group(2))
    m = re.fullmatch(r'sch-?(\d*)([A-Za-z]*)', name)
    if m:
        return (2, int(m.group(1) or 0), m.group(2))
    return (3, 0, name)


def files_at(repo: str, commit: str, slug: str) -> dict[str, str]:
    """The Cap.'s files at a commit, read with one ls-tree and one cat-file --batch (not one git show per file)."""
    out = subprocess.run(['git', 'ls-tree', '-r', commit, f'{slug}/'], cwd=repo, capture_output=True,
                         text=True, encoding='utf-8').stdout.split('\n')
    blobs = []
    for line in out:
        if not line:
            continue
        info, f = line.split('\t', 1)
        if (f.endswith('.md') and not f.endswith('/README.md')) or f.endswith('/' + build.ORDER_FILE):
            blobs.append((f[len(slug) + 1:], info.split()[2]))
    if not blobs:
        return {}
    data = subprocess.run(['git', 'cat-file', '--batch'], cwd=repo, input=''.join(f'{sha}\n' for _, sha in blobs).encode(),
                          capture_output=True).stdout
    res, pos = {}, 0
    for name, _ in blobs:
        nl = data.index(b'\n', pos)
        size = int(data[pos:nl].split()[2])
        res[name] = data[nl + 1:nl + 1 + size].decode('utf-8')
        pos = nl + 1 + size + 1
    return res


def commits_by_cap(repo: str) -> dict[str, list[tuple[str, str]]]:
    """For each Cap. folder, the commits that touch it, newest first, with their In-force days: one git log."""
    out = subprocess.run(['git', 'log', '--format=\x1e%H\t%(trailers:key=In-force,valueonly,separator=)', '--name-only',
                          'main'], cwd=repo, capture_output=True, text=True, encoding='utf-8').stdout
    res: dict[str, list[tuple[str, str]]] = {}
    for rec in out.split('\x1e')[1:]:
        head, _, names = rec.partition('\n')
        h, _, day = head.partition('\t')
        for slug in sorted({n.split('/', 1)[0] for n in names.split('\n') if n.startswith('cap-')}):
            res.setdefault(slug, []).append((h, day.strip()))
    return res


def check_cap(args):
    act, repo, commits = args
    z = build.fetch_zip(act['zip'], True)
    out = {'slug': act['slug'], 'versions': 0, 'files': 0, 'bad': [], 'wbad': [], 'lbad': [], 'words': 0}
    for v in build.versions(act, offline=True):
        raw = z.read(v['member'])
        parsed = build.read_version(raw)
        expected = {build.file_name(k): u['text'] for k, u in parsed['units'].items()}
        expected[build.ORDER_FILE] = build.order_text(parsed['order']).decode('utf-8')
        commit = next((h for h, d in commits if d and d <= v['in_force']), '')
        got = files_at(repo, commit, act['slug']) if commit else {}
        out['versions'] += 1
        out['files'] += len(expected)
        if got != expected:
            diff = sorted(set(got) ^ set(expected)) or [k for k in expected if got.get(k) != expected[k]]
            out['bad'].append(f'{act["slug"]} {v["in_force"]}: {diff[:5]}')
        # The whole Cap. in the order its order.txt in git gives, as tools/hkhistory.py prints it.
        listed = [n for n in got.get(build.ORDER_FILE, '').split('\n') if n in got]
        rest = sorted((f for f in got if f not in listed and f != build.ORDER_FILE),
                      key=lambda f: order(f'{act["slug"]}/{f}'))
        whole = ''.join(got[f] + '\n' for f in listed + rest)
        off, mine = official_text(raw), repo_text(whole)
        ow, rw = TOKEN.findall(off), TOKEN.findall(mine)
        out['words'] += len(ow)
        if ow != rw:
            i = next((i for i, (a, b) in enumerate(zip(ow, rw)) if a != b), min(len(ow), len(rw)))
            out['wbad'].append(f'{act["slug"]} {v["in_force"]}: official {len(ow)} vs repo {len(rw)} words; first difference '
                               f'at {i}: {" ".join(ow[max(0, i - 5):i + 5])!r} / {" ".join(rw[max(0, i - 5):i + 5])!r}')
        if letters(off) != letters(mine):
            out['lbad'].append(f'{act["slug"]} {v["in_force"]}')
    return out


def tool_checks(repo: str) -> list[str]:
    """tools/hkhistory.py on a few provisions at several dates: the output changes across a known amendment."""
    cases = [('cap-486', '2', '2021-10-07', '2021-10-08'), ('cap-383', '3', '1998-02-27', '1998-02-28'),
             ('cap-1', '3', '2024-03-22', '2024-03-23')]
    res = []
    for cap, prov, a, b in cases:
        ta, tb = (subprocess.run([sys.executable, '-X', 'utf8', 'tools/hkhistory.py', d, cap, prov], cwd=repo,
                                 capture_output=True, text=True, encoding='utf-8') for d in (a, b))
        ok = ta.returncode == 0 and tb.returncode == 0 and ta.stdout and tb.stdout and ta.stdout != tb.stdout
        res.append(f'{"ok" if ok else "FAIL"} {cap} {prov} {a} -> {b}')
    return res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--repo', default=str(build.ROOT.parent / 'hong-kong-law'))
    ap.add_argument('--caps', default=None)
    ap.add_argument('--no-record', action='store_true')
    args = ap.parse_args()
    acts, _undated = build.discover(True)
    acts = build.select(acts, args.caps)
    by_cap = commits_by_cap(args.repo)
    versions = files = words = 0
    bad, wbad, lbad = [], [], []
    with mp.Pool(4) as pool:   # at most 4 workers: the machine runs several builders at once
        for i, r in enumerate(pool.imap(check_cap, [(a, args.repo, by_cap.get(a['slug'], [])) for a in acts], chunksize=4)):
            versions += r['versions']
            files += r['files']
            words += r['words']
            bad += r['bad']
            wbad += r['wbad']
            lbad += r['lbad']
            for m in r['bad'] + r['wbad']:
                print(('MISMATCH ' if m in r['bad'] else 'WORDS ') + m, flush=True)
            if (i + 1) % 250 == 0:
                print(f'  {i + 1}/{len(acts)} Caps', flush=True)
    tools = tool_checks(args.repo) if not args.caps else []
    print(f'{versions} versions checked ({files} files), {len(bad)} mismatches; {versions} versions word for word '
          f'({words} words), {len(wbad)} mismatches; letters and digits {len(lbad)} mismatches')
    for t in tools:
        print('tool:', t)
    if not args.no_record and not args.caps:
        p = HERE / 'verification.json'
        rec = json.loads(p.read_text(encoding='utf-8')) if p.exists() else {}
        rec['check'] = {'versions': versions, 'files': files, 'mismatches': len(bad), 'wordcheck': versions,
                        'words': words, 'word_mismatches': len(wbad), 'letter_mismatches': len(lbad), 'caps': len(acts),
                        'tool': tools}
        p.write_text(json.dumps(rec, indent=1, sort_keys=True) + '\n', encoding='utf-8', newline='\n')
    raise SystemExit(1 if bad or wbad or lbad or any(t.startswith('FAIL') for t in tools) else 0)


if __name__ == '__main__':
    main()
