"""Prints a Cap., or one provision of it, as it stood on a given day, from this repository's history.

    python tools/hkhistory.py 2010-01-01 cap-486 33       # section 33 of Cap. 486 on 1 January 2010
    python tools/hkhistory.py 2010-01-01 486 33           # the same (the folder name or the Cap. number)
    python tools/hkhistory.py 2020-01-01 cap-486          # the whole Ordinance on 1 January 2020
    python tools/hkhistory.py 2020-01-01 cap-486 2A       # section 2A (letters follow the number)
    python tools/hkhistory.py 2020-01-01 cap-486 sch1     # Schedule 1
    python tools/hkhistory.py 2020-01-01 cap-486 intro    # long title and commencement
    python tools/hkhistory.py 2020-01-01 cap-486 --commit # the commit that holds that day's text, with the law that made it

Each commit carries the day its change took effect in an `In-force:` trailer. The text in force on a day is the last
commit on or before it. The record starts on 1 July 1997. Standard library only.
"""
import re
import subprocess
import sys


def git(*args: str) -> str:
    return subprocess.run(['git', *args], capture_output=True, text=True, encoding='utf-8', check=True).stdout


def order(path: str) -> tuple:
    """The order of a Cap.'s files: opening, sections by number and letters, schedules, anything else."""
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


def folder(cap: str) -> str:
    cap = cap.lower().removeprefix('cap').strip('-. ')
    return f'cap-{cap}'


def file_for(key: str) -> str:
    """'33' -> s-033.md, '2A' -> s-002A.md, 'sch1' or 'sch-1' -> sch-1.md; anything else is a file name."""
    k = key.strip()
    m = re.fullmatch(r's?\.?\s*(\d+)([A-Za-z]*)', k)
    if m:
        return f's-{int(m.group(1)):03d}{m.group(2).upper()}.md'
    m = re.fullmatch(r'sch(?:edule)?-?\s*(\d*)([A-Za-z]*)', k, re.I)
    if m:
        return (f'sch-{m.group(1)}{m.group(2).upper()}' if m.group(1) or m.group(2) else 'sch') + '.md'
    return k if k.endswith('.md') else f'{k}.md'


def commit_on(day: str, slug: str) -> str:
    out = git('log', '--format=%H%x09%(trailers:key=In-force,valueonly,separator=)', 'main', '--', slug)
    for line in out.splitlines():
        h, _, d = line.partition('\t')
        if d.strip() and d.strip() <= day:
            return h
    return ''


def main():
    sys.stdout.reconfigure(encoding='utf-8')
    args = [a for a in sys.argv[1:] if a != '--commit']
    if len(args) < 2:
        sys.exit(__doc__)
    day, slug = args[0], folder(args[1])
    if not re.fullmatch(r'\d{4}-\d{2}-\d{2}', day):
        sys.exit(f'{day} is not a date (YYYY-MM-DD).')
    commit = commit_on(day, slug)
    if not commit:
        sys.exit(f'{slug} is not in the record on {day} (the record starts on 1997-07-01).')
    if '--commit' in sys.argv:
        sys.stdout.write(git('show', '-s', '--format=%H%n%an%n%B', commit))
        return
    if len(args) > 2:
        name = file_for(args[2])
        try:
            sys.stdout.write(git('show', f'{commit}:{slug}/{name}'))
        except subprocess.CalledProcessError:
            sys.exit(f'{slug}/{name} was not in the text on {day}.')
        return
    files = [f for f in git('ls-tree', '-r', '--name-only', commit, f'{slug}/').split('\n')
             if f.endswith('.md') and not f.endswith('/README.md')]
    for f in in_order(commit, slug, files):
        sys.stdout.write(git('show', f'{commit}:{f}') + '\n')


def in_order(commit: str, slug: str, files: list[str]) -> list[str]:
    """The files in the order of the official text, as the Cap.'s order.txt lists it on that day (the file names
    cannot give it: newer Caps put s. 3AA before s. 3A, older ones after it); any file it does not list comes after,
    by name."""
    try:
        listed = [f'{slug}/{n}' for n in git('show', f'{commit}:{slug}/order.txt').split('\n') if n]
    except subprocess.CalledProcessError:
        listed = []
    have = set(files)
    first = [f for f in listed if f in have]
    return first + sorted((f for f in files if f not in set(first)), key=order)


if __name__ == '__main__':
    main()
