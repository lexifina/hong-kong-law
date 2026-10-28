"""Functional smoke test of the built Hong Kong law repository: the things a reader does with it work. Standard library only.

    python -X utf8 scripts/hong-kong-law/test_repo.py [--repo ../hong-kong-law] [--record]
    python -X utf8 tools/test_repo.py                   # from inside the repository

It asserts that:
1. `git blame` on a changed provision names an amending law as author of its lines;
2. tools/hkhistory.py gives the text before and after a known amendment, and each equals the file at that law's tag;
3. `git log --follow` on a file lists its amending laws in the order they took effect;
4. every tag resolves to a commit, every commit has an `In-force:` trailer that git parses, and no subject is longer
   than 72 characters;
5. no commit is authored by Lexifina except the documentation commit (the last one);
6. every git or tool command in the README's table runs and prints something.
With --record the result is written to verification.json next to this script (for REPRODUCE.md).
"""
import argparse
import json
import re
import shlex
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
LAW = re.compile(r'^((L\.N\.|E\.R\.|G\.N\.|G\.N\.A\.|G\.N\. \(E\.\)) )?\d+ of \d{4}$')
BASELINE = re.compile(r'^Cap\. \d+[A-Z]* \((text on 1 July 1997|first version)\)$')
PUBLISHER = 'Department of Justice (HKeL)'


def default_repo() -> Path:
    if (HERE.parent / '.git').exists():
        return HERE.parent
    return HERE.parents[2] / 'hong-kong-law'


def ok_author(a: str) -> bool:
    return bool(LAW.match(a) or BASELINE.match(a) or a == PUBLISHER)


class Smoke:
    def __init__(self, repo: Path):
        self.repo = repo
        self.results: list[tuple[str, bool, str]] = []

    def git(self, *args: str) -> str:
        out = subprocess.run(['git', *args], cwd=self.repo, capture_output=True, text=True, encoding='utf-8')
        if out.returncode:
            raise AssertionError(f'git {" ".join(args)}: {out.stderr.strip()}')
        return out.stdout

    def tool(self, *args: str) -> str:
        out = subprocess.run([sys.executable, '-X', 'utf8', 'tools/hkhistory.py', *args], cwd=self.repo,
                             capture_output=True, text=True, encoding='utf-8')
        if out.returncode:
            raise AssertionError(f'hkhistory {" ".join(args)}: {out.stderr.strip()}')
        return out.stdout

    def check(self, name: str, fn):
        try:
            detail = fn() or ''
            self.results.append((name, True, detail))
            print(f'PASS {name}: {detail}')
        except AssertionError as exc:
            self.results.append((name, False, str(exc)))
            print(f'FAIL {name}: {exc}')

    # 1
    def blame(self):
        out = self.git('blame', '--line-porcelain', 'main', '--', 'cap-486/s-002.md')
        authors = {l[7:] for l in out.splitlines() if l.startswith('author ')}
        assert authors, 'no blame output'
        assert all(ok_author(a) for a in authors), f'unexpected authors {authors}'
        assert '32 of 2021' in authors, f'32 of 2021 not among the authors {authors}'
        assert '18 of 2012' in authors, f'18 of 2012 not among the authors {authors}'
        assert len(authors) >= 3, f'only {authors}'
        return f'cap-486/s-002.md lines by {", ".join(sorted(authors))}'

    # 2
    def on_date(self):
        done = []
        for cap, prov, path, tag, before, after in [
                ('cap-486', '2', 'cap-486/s-002.md', 'ord/2021-32', '2021-10-07', '2021-10-08'),
                ('cap-383', '3', 'cap-383/s-003.md', 'ord/1998-2', '1998-02-27', '1998-02-28')]:
            a, b = self.tool(before, cap, prov), self.tool(after, cap, prov)
            assert a and b and a != b, f'{path}: no change between {before} and {after}'
            assert b == self.git('show', f'{tag}:{path}'), f'{path} on {after} is not the file at {tag}'
            assert a == self.git('show', f'{tag}~1:{path}'), f'{path} on {before} is not the file before {tag}'
            done.append(f'{path} {before} != {after}')
        whole = self.tool('2000-01-01', 'cap-486')
        assert 'Personal Data (Privacy) Ordinance' in whole and '# 33.' in whole, 'whole Cap. 486 on 2000-01-01 incomplete'
        early = subprocess.run([sys.executable, '-X', 'utf8', 'tools/hkhistory.py', '1997-06-30', 'cap-486'], cwd=self.repo,
                               capture_output=True, text=True, encoding='utf-8')
        assert early.returncode != 0, 'a day before the record should say so'
        return '; '.join(done)

    # 3
    def follow(self):
        checked = []
        for path in ('cap-486/s-002.md', 'cap-486/s-014.md', 'cap-486/s-058.md'):
            out = self.git('log', '--follow', '--format=%an%x09%(trailers:key=In-force,valueonly,separator=)', 'main', '--', path)
            rows = [l.split('\t') for l in out.splitlines() if l]
            assert len(rows) >= 3, f'{path}: {len(rows)} commits'
            days = [d.strip() for _, d in rows]
            assert days == sorted(days, reverse=True), f'{path}: not in date order {days}'
            assert all(ok_author(a) for a, _ in rows), f'{path}: authors {[a for a, _ in rows]}'
            assert sum(1 for a, _ in rows if LAW.match(a)) >= 2, f'{path}: fewer than two laws'
            checked.append(f'{path} {len(rows)} commits')
        return '; '.join(checked)

    # 4
    def tags_and_trailers(self):
        tags = self.git('tag').split()
        assert tags, 'no tags'
        for t in tags:
            self.git('rev-parse', '--verify', '-q', f'{t}^{{commit}}')
        rows = self.git('log', '--format=%H%x09%an%x09%(trailers:key=In-force,valueonly,separator=)%x09%s', 'main').splitlines()
        missing = [r for r in rows if not r.split('\t')[2].strip()]
        assert not missing, f'{len(missing)} commits without In-force, e.g. {missing[:2]}'
        bad = [r for r in rows if not re.fullmatch(r'\d{4}-\d{2}-\d{2}', r.split('\t')[2].strip())]
        assert not bad, f'malformed In-force {bad[:2]}'
        long = [r for r in rows if len(r.split('\t')[3]) > 72]
        assert not long, f'{len(long)} subjects over 72 characters, e.g. {long[:1]}'
        return f'{len(tags)} tags resolve; {len(rows)} commits carry In-force and a subject of at most 72 characters'

    # 5
    def lexifina(self):
        rows = self.git('log', '--format=%H%x09%an%x09%ae%x09%cn', 'main').splitlines()
        by_lex = [r for r in rows if r.split('\t')[1] == 'Lexifina']
        assert len(by_lex) == 1 and by_lex[0] == rows[0], f'{len(by_lex)} commits by Lexifina'
        assert all(r.split('\t')[3] == 'Lexifina' for r in rows), 'a committer other than Lexifina'
        authors = {r.split('\t')[1] for r in rows[1:]}
        assert all(ok_author(a) for a in authors), f'unexpected authors {[a for a in authors if not ok_author(a)]}'
        assert all(r.split('\t')[2].endswith('.invalid') for r in rows[1:]), 'a law author address not ending .invalid'
        return f'only the documentation commit {rows[0][:10]} is by Lexifina; {len(authors)} distinct authors'

    # 6
    def readme(self):
        text = (self.repo / 'README.md').read_text(encoding='utf-8')
        table = text[text.index('## The questions'):text.index('## The dates')]
        cmds = [c for c in re.findall(r'`([^`]+)`', table) if c.startswith(('git ', 'python '))]
        assert len(cmds) >= 8, f'only {len(cmds)} commands found'
        for c in cmds:
            args = shlex.split(c)
            if args[0] == 'python':
                args[0] = sys.executable
                args.insert(1, '-X')
                args.insert(2, 'utf8')
            out = subprocess.run(args, cwd=self.repo, capture_output=True, text=True, encoding='utf-8')
            assert out.returncode == 0, f'{c}: exit {out.returncode} {out.stderr.strip()[:200]}'
            assert out.stdout.strip(), f'{c}: printed nothing'
        return f'{len(cmds)} README commands ran and printed output'


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--repo', default=None)
    ap.add_argument('--record', action='store_true')
    args = ap.parse_args()
    sys.stdout.reconfigure(encoding='utf-8')
    s = Smoke(Path(args.repo) if args.repo else default_repo())
    s.check('blame names a law', s.blame)
    s.check('text before and after an amendment', s.on_date)
    s.check('log --follow in date order', s.follow)
    s.check('tags resolve, In-force on every commit', s.tags_and_trailers)
    s.check('only the documentation commit is by Lexifina', s.lexifina)
    s.check('README commands run', s.readme)
    ok = all(r[1] for r in s.results)
    print(f'{sum(r[1] for r in s.results)}/{len(s.results)} passed')
    if args.record:
        p = HERE / 'verification.json'
        rec = json.loads(p.read_text(encoding='utf-8')) if p.exists() else {}
        rec['smoke'] = {'passed': sum(r[1] for r in s.results), 'total': len(s.results),
                        'results': [{'test': n, 'ok': o, 'detail': d} for n, o, d in s.results]}
        p.write_text(json.dumps(rec, indent=1, sort_keys=True, ensure_ascii=False) + '\n', encoding='utf-8', newline='\n')
    raise SystemExit(0 if ok else 1)


if __name__ == '__main__':
    main()
