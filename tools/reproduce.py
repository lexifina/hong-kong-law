"""Writes data/versions.json, data/labelled.tsv, caps.csv, corpus.json and REPRODUCE.md into the Hong Kong law
repository, from the facts of the build that made it. Called by build.py; kept apart so the record of how the repository
was made reads as one document.

The results of the checks (check_repo.py, test_repo.py and the rebuild that compares hashes) are read from
verification.json next to this file, which check_repo.py, `test_repo.py --record` and `build.py --verify-rebuild` write.
They describe the build before the one that writes this file, from the same data; a rebuild with the same data and the
same verification.json gives the same hashes."""
from __future__ import annotations

import csv
import io
import json
import subprocess
from pathlib import Path

HERE = Path(__file__).resolve().parent
TERMS = 'https://data.gov.hk/en/terms-and-conditions'
DATASET = 'https://data.gov.hk/en-data/dataset/hk-doj-hkel-legislation-past'
MODELS = ('Claude Sonnet 5.5 (model id `claude-sonnet-5-5`) wrote the first build (Cap. 383 and Cap. 486); Claude Opus 5.5 '
          '(model id `claude-opus-5-5`) extended it to every Cap. in the bulk files')


def record_to(built: list[dict], today: str) -> str:
    days = [v['in_force'] for b in built for v in b['versions'] if v['in_force'] <= today]
    return max(days)


def label_of(ch: dict, k: str) -> str:
    return (ch['cur']['units'].get(k) or ch['prev']['units'][k])['label']


def write_manifest(repo: Path, built: list[dict], today: str, undated: list[dict]):
    """Every source file the text comes from, with its sha256, so a rebuild can show it read the same bytes."""
    zips = {}
    for b in built:
        zips[b['zipinfo']['name']] = b['zipinfo']
    out = {'built': today, 'source': DATASET, 'bulk_files': [zips[k] for k in sorted(zips)], 'caps': [],
           'undated_placeholders_not_read': sorted(u['member'] for u in undated)}
    for b in built:
        out['caps'].append({
            'cap': b['label'], 'slug': b['act']['slug'], 'title': b['title'], 'bulk_file': b['zipinfo']['name'],
            'versions': [{'date': v['date'], 'in_force': v['in_force'], 'member': v['member'], 'sha256': v['sha256']}
                         for v in b['versions']],
            'not_in_record': b['versions'][0]['skipped_before']
            + [s for v in b['versions'] for s in v.get('superseded_same_day', [])]})
    (repo / 'data').mkdir(exist_ok=True)
    (repo / 'data' / 'versions.json').write_text(json.dumps(out, ensure_ascii=False, indent=1) + '\n', encoding='utf-8',
                                                 newline='\n')
    # caps.csv: one row per Cap.
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator='\n')
    w.writerow(['cap', 'title', 'folder', 'kind', 'bulk_file', 'versions', 'first_in_force', 'last_in_force', 'files_now'])
    for b in built:
        kind = 'subsidiary legislation' if not b['act']['cap'].isdigit() else 'ordinance'
        w.writerow([b['label'], b['title'], b['act']['slug'] + '/', kind, b['zipinfo']['name'], len(b['versions']),
                    b['versions'][0]['in_force'], b['versions'][-1]['in_force'], len(b['versions'][-1]['units'])])
    (repo / 'caps.csv').write_text(buf.getvalue(), encoding='utf-8', newline='\n')
    # data/labelled.tsv: every file change whose cause is not a new source note, and every labelled source quirk.
    rows = ['cap\tin_force\tprovision\tlabel']
    for b in built:
        for ch in b['changes']:
            for k in sorted(ch['why']):
                if ch['why'][k] != 'new source note':
                    rows.append(f'{b["label"]}\t{ch["from"]}\t{label_of(ch, k)}\t{ch["why"][k]}')
            for k in sorted(ch['flags']):
                for f in ch['flags'][k]:
                    rows.append(f'{b["label"]}\t{ch["from"]}\t{label_of(ch, k)}\t{f}')
    (repo / 'data' / 'labelled.tsv').write_text('\n'.join(rows) + '\n', encoding='utf-8', newline='\n')


def write_corpus(repo: Path, built: list[dict], today: str):
    rt = record_to(built, today)
    n_ord = sum(1 for b in built if b['act']['cap'].isdigit())
    corpus = {
        'corpus': 'hk/national/acts',
        'name': (f'Hong Kong law: every Cap. in the Department of Justice bulk files ({n_ord} ordinances and '
                 f'{len(built) - n_ord} items of subsidiary legislation)'),
        'label': 'Hong Kong',
        'language': 'en',
        'acts': [f'{b["label"]} {b["title"]}' for b in built],
        'history_from': '1997-07-01',
        'record_to': rt,
        'record_note': (f'Every Cap. (ordinances and subsidiary legislation) in English, from the text in force on 1 July '
                        f'1997 (or a later first version) to the last version dated on or before {today} in the '
                        f'Department of Justice bulk files on DATA.GOV.HK; data retrieved {today}.'),
        'in_force_trailer': 'In-force',
        'built': today,
        'dates': {
            'commit': 'in-force',
            'other_trailers': ['Cited'],
            'time': '12:00 Hong Kong (UTC+8, no summer time)',
        },
        'scope': {
            'trailer': 'Applies',
            'when_absent': 'this corpus records no scope notes (no commit carries Applies:); the absence is not a statement '
                           'that the change reaches every case',
            'default_reach': {
                'rule': 'presumption against retrospective operation, and no retrospective criminal liability',
                'meaning': ('an Ordinance is presumed to operate from the day it takes effect and not to attach new legal '
                            'consequences to events completed before then unless it says so; in criminal matters the Bill of '
                            'Rights bars holding anyone guilty for an act that was not an offence when it was committed and '
                            'imposing a heavier penalty than the one then applicable, and a lighter penalty provided later '
                            'benefits the offender'),
                'authority': ('Hong Kong Bill of Rights, Article 12(1) (Cap. 383 s. 8): "No one shall be held guilty of any '
                              'criminal offence on account of any act or omission which did not constitute a criminal offence, '
                              'under Hong Kong or international law, at the time when it was committed. Nor shall a heavier '
                              'penalty be imposed than the one that was applicable at the time when the criminal offence was '
                              'committed. If, subsequent to the commission of the offence, provision is made by law for the '
                              'imposition of a lighter penalty, the offender shall benefit thereby."; the general presumption is '
                              'common law and is not checked in this corpus'),
                'decided_here': False,
            },
        },
        'tool': 'tools/hkhistory.py',
        'citation': {
            'file': '([a-z0-9-]+)/s-0*([0-9]+[A-Z]*)\\.md',
            'cites': '([Ss]ection|s\\.) ?{n}([^0-9A-Za-z]|$)',
        },
        'checked_on': today,
        'history': 'in-force',
    }
    (repo / 'corpus.json').write_text(json.dumps(corpus, ensure_ascii=False, indent=2) + '\n', encoding='utf-8', newline='\n')


def write_reproduce(repo: Path, built: list[dict], log: list[dict], tags: dict, requests: list[dict], today: str,
                    undated: list[dict]):
    blob = subprocess.run(['git', 'hash-object', str(HERE / 'build.py')], capture_output=True, text=True).stdout.strip()
    pyv = subprocess.run(['python', '--version'], capture_output=True, text=True).stdout.strip()
    gitv = subprocess.run(['git', '--version'], capture_output=True, text=True).stdout.strip()
    try:
        import lxml.etree
        lxmlv = '.'.join(str(x) for x in lxml.etree.LXML_VERSION[:3])
    except Exception:
        lxmlv = '?'
    ver = json.loads((HERE / 'verification.json').read_text(encoding='utf-8')) if (HERE / 'verification.json').exists() else {}
    n_start = sum(1 for c in log if c['kind'] == 'start')
    n_law = sum(1 for c in log if c['kind'] == 'law')
    n_cand = sum(1 for c in log if c['kind'] == 'candidates')
    n_unexp = sum(1 for c in log if c['kind'] == 'unexplained')
    n_same = sum(1 for c in log if c['kind'] == 'unchanged')
    n_er = sum(1 for c in log if c['kind'] == 'law' and (c['law'] or '').startswith('E.R. '))
    n_laws = len({c['law'] for c in log if c['kind'] == 'law'})
    why: dict[str, int] = {}
    n_flags = 0
    for b in built:
        for ch in b['changes']:
            for k, w in ch['why'].items():
                why[w] = why.get(w, 0) + 1
            n_flags += sum(len(f) for f in ch['flags'].values())
    n_changes = sum(why.values())
    zips = {}
    for b in built:
        zips[b['zipinfo']['name']] = b['zipinfo']
    zrows = '\n'.join(f'| `{z["name"]}` | {z["bytes"]:,} | `{z["sha256"]}` | {z["last_modified"] or "?"} |'
                      for _n, z in sorted(zips.items()))
    n_members = sum(len(b['versions']) for b in built)
    n_ord = sum(1 for b in built if b['act']['cap'].isdigit())
    n_files = sum(len(b['versions'][-1]['units']) for b in built)
    skipped = sum(len(b['versions'][0]['skipped_before']) for b in built)
    same_day = sum(len(v.get('superseded_same_day', [])) for b in built for v in b['versions'])
    only_placeholder = sorted({u['cap'] for u in undated if not u['has_versions']})
    chk = ver.get('check', {})
    det = ver.get('rebuild', {})
    smoke = ver.get('smoke', {})
    check_line = (f'`{chk["versions"]} versions checked ({chk["files"]} files), {chk["mismatches"]} mismatches; '
                  f'{chk["wordcheck"]} versions word for word ({chk["words"]} words) against the whole official text, '
                  f'{chk["word_mismatches"]} mismatches; letters and digits {chk.get("letter_mismatches", "?")} mismatches`'
                  if chk else '(not yet run)')
    rebuild_line = (f'A second build from the same bulk files into an empty folder gave the same history: the last law commit '
                    f'was `{det["history_tip"]}` in both, and every one of the {det["commits"]} law commits and {det["tags"]} '
                    f'tags had the same hash.' if det.get('identical') else '(not yet run)')
    smoke_lines = ('\n'.join(f'   - {"pass" if r["ok"] else "FAIL"}: {r["test"]}: {r["detail"]}' for r in smoke['results'])
                   if smoke else '   (not yet run)')
    smoke_head = f'{smoke["passed"]} of {smoke["total"]} passed' if smoke else 'not yet run'
    why_none = 'no new source note, and the provision does not start on this day'
    text = f"""# How this history was made, and how to make it again

This file records exactly how the repository was built: the sources, the commands, the software, the decisions made
by hand, and what an AI model did and did not do. The build writes it, so it describes the build that made this
commit.

## Short version

```sh
git clone https://github.com/lexifina/hong-kong-law && cd hong-kong-law
pip install lxml
python -X utf8 tools/build.py --repo ../rebuilt --today {today}
git -C ../rebuilt rev-parse main        # the same hash as this repository's main
python -X utf8 tools/check_repo.py --repo ../rebuilt
python -X utf8 tools/test_repo.py --repo ../rebuilt
```

`tools/build.py` needs Python 3.12 or later with `lxml`, and git. It reads the four bulk files below from a local
folder (`--sources <folder>`; by default the folder the script expects next to itself), each matching its sha256 in
the table, and writes this repository into `--repo`, writing the history with `git fast-import`. It makes no network
requests. With the same files and the same `--today` it gives the same commits with the same hashes. `data/versions.json`
lists every bulk file with its sha256 and every version file read with its sha256, so a rebuild can show it read the
same bytes. The Department of Justice replaces the bulk files from time to time; then the hashes change too.
(`check_repo.py` and `test_repo.py` read the bulk files from the same folder. Set `GITLAW_PUBLIC_REBUILD=1` when
running the published tools outside Lexifina's own repository.)

## Sources

All legal text and all information about versions and amending laws come from the **Hong Kong e-Legislation (HKeL)
bulk files** that the Department of Justice publishes on DATA.GOV.HK ({DATASET}). Nothing was typed in, summarised
or rewritten. **Only the bulk files were used**; nothing comes from the website elegislation.gov.hk.

| Bulk file | Bytes | sha256 | Last-Modified |
| --- | ---: | --- | --- |
{zrows}

Each bulk file is one ZIP with a folder per Cap. and an XML file per dated version
(`cap_486_en_p/cap_486_20211008000000_en_p.xml`), in the Hong Kong Legislation Model (HKLM). The build read {n_members}
version files of {len(built)} Caps.: {n_ord} ordinances and {len(built) - n_ord} items of subsidiary legislation
(Cap. 486A, ...). [`caps.csv`](caps.csv) lists every Cap. with its versions and files.

**Retrieved** on {today}. The Last-Modified column is the file host's date for each file.

**Left out.** {len(undated)} files are named with dashes instead of a date (`cap_634_--------------_en_p.xml`): each is a
placeholder saying that the text "will be incorporated in Hong Kong e-Legislation as soon as possible", not a version,
and is not read. {len(only_placeholder)} Caps. have only such a placeholder and are not in the record
({', '.join('Cap. ' + c for c in only_placeholder) or 'none'}). {skipped} versions dated before 1 July 1997 (the text of 30
June 1997, before the handover) are left out where a version of 1 July 1997 exists, and {same_day} versions are left out
because a later file of the same day replaces them (two files of one day, 000000 and 110000). All are listed in
`data/versions.json`.

**Terms of use.** DATA.GOV.HK's Terms and Conditions of Use ({TERMS}, version 1.2, last updated 26 May 2025, as read
on {today}) allow browsing, downloading, distributing and reproducing the Data for commercial and non-commercial
purposes free of charge on conditions, among them that the source of the Data is identified clearly and the
Government's ownership of the intellectual property rights acknowledged, and that the user indemnifies the Government.
See `LICENSE`. This repository is private.

**The Basic Law** is in the dataset as instrument A101 (`hkel_c_instruments_en.zip`, the current version) but has no
past versions (the past instruments file holds only A303, A305, A401, A405, A501, A601 and A602), and its XML carries no
`startPeriod` or source notes, so no history of it can be built from this dataset. Instruments are not Caps. and are
not in the record.

## The build, step by step

1. `python -X utf8 scripts/hong-kong-law/build.py --today {today}` in Lexifina's own repository read the retrieved
   bulk files and wrote this repository. `tools/build.py` here is the same file as
   `scripts/hong-kong-law/build.py` there (git blob `{blob}`), with `tools/reproduce.py`, which writes this file,
   `tools/check_repo.py` and `tools/test_repo.py`. How the bulk files were retrieved is not part of this record.
2. `python -X utf8 scripts/hong-kong-law/check_repo.py` read every version of each Cap. back from this repository on the
   day it took effect (the last commit whose `In-force:` is on or before it, as `tools/hkhistory.py` reads it) and
   compared it file by file with the official text parsed afresh from the bulk files' XML; then it compared the whole Cap.,
   word for word and again letters and digits only (casefolded), with all the text under `<main>` of the official
   file, read without the build's parser. Result: {check_line}.
3. `python -X utf8 scripts/hong-kong-law/test_repo.py --record` ran the functional smoke test against this repository
   ({smoke_head}):
{smoke_lines}
4. `python -X utf8 scripts/hong-kong-law/build.py --verify-rebuild` built the repository a second time from
   the same bulk files into a temporary folder and compared the hashes. {rebuild_line}
5. The build was run once more to write these results into this file, and the final `main` was rebuilt again in a
   temporary folder and compared hash for hash.
6. The first build (Cap. 383 and Cap. 486 only) was published on 2026-10-28. This full build replaces it once,
   because the new Caps' changes reach back to 1997 and `main` must stay in the order the changes took effect. From
   then on `main` is append-only.

It ran with {pyv}, lxml {lxmlv} and {gitv} on Windows 11. The build uses no network service.

## How the text and the commits are derived

Everything below is done by `tools/build.py`, deterministically.

- **Text.** Each Cap. is a folder named after its number in lower case (`cap-486/`, `cap-486a/`). Each section is one
  file named after the official identifier: `s33` is `cap-486/s-033.md`, `s2A` is `cap-486/s-002A.md` (the sections of
  subsidiary legislation, its rules, regulations and paragraphs, have the same identifiers in the source and the same
  file names); each schedule is `sch-1.md` (`sch.md` for an unnumbered one); `intro.md` holds the long title or title,
  the commencement note and the enacting words; `outro.md` holds matter after the last section or schedule; any other
  provision keeps its identifier (`section-s0-1.md`). The headings of the parts and divisions that come before a
  section are `##` lines at the top of its file; its number and heading are the `#` line; each subsection is one line
  beginning with its number, and each paragraph, subparagraph and definition is a list item one level deeper. Tables
  are one line per row, cells separated by ` | `. Images (forms and diagrams in some schedules) are not in the text. The
  source notes that print the amending law's citation ("(Added 18 of 2012 s. 3)") are part of the official text and are
  kept; the commencement notes too. The English text prints the Chinese equivalent of a defined term in brackets; it is
  kept as printed. A repealed or omitted provision stays as a file holding its heading and the note that repealed it.
- **Normalised.** Only white space: runs of spaces, line breaks inside a line of the XML, tabs and no-break spaces
  become one space. Every other character is kept; a line of text that begins with `#` or `- ` gets a backslash
  before it, so markdown does not read it as a heading or list item, and a `|` printed in the text is written
  `\\|`. Each Cap.'s `order.txt` lists its files in the
  order of the official text on that day.
- **Versions.** Every dated file in the bulk file is a version. History starts on 1 July 1997: the newest version
  dated on or before that day stands for it. A Cap. made later starts with its first version.
- **Changes.** Consecutive versions are compared file by file: {n_changes:,} changes of a file were found.
- **Cause.** Each provision prints the laws that added, amended or repealed it, as links in its source notes. Tried in
  this order, for each changed file:
  1. a citation (of a law of the version's year or earlier) is new in the file's source notes, compared with the
     version before, and it is one law: that law ({why.get('new source note', 0):,} file changes);
  2. two or more laws are new in it: none is credited; the publisher commits it and names them as candidates
     ({why.get('two laws cited', 0):,});
  3. nothing is new in its notes but the added text cites a law in words and names the version's day ("On and from
     18 July 1997, ... (126 of 1997 s.2)"): that law, labelled ({why.get('plain citation', 0):,});
  4. nothing is new in its notes, the source gives the provision (or the part heading above it) a `startPeriod` of the
     version's day, and exactly one law is new anywhere in the Cap. in this version: that law, by date only, labelled
     ({why.get('date only', 0):,});
  5. the same, on an editorial revision day: exactly one E.R. is new in the version, the text the version adds prints
     it in a note on the Cap. ("(Format changes—E.R. 3 of 2015)"), and every other law new in the version was already
     cited in the Cap. (in a note or in words) the day before, so those are reprinted citations: the E.R., by date
     only, labelled `Evidence: date only, editorial revision` ({why.get('date only, editorial revision', 0):,});
  6. the same, with more than one law new in the version: candidates ({why.get('two laws in this version', 0):,});
  7. nothing is new in its notes, but the added text cites exactly one law of the version's year in words that the
     provision did not cite before (the daily specifications printed in editorial notes, "G.N. (E.) 212 of 2020"):
     that law, labelled `Evidence: plain citation only` ({why.get('plain citation, day not named', 0):,});
  8. otherwise: no law; the publisher commits it and labels it ({why.get(why_none, 0):,}).

  A citation is new only if the whole Cap. prints it (the same law, printed the same) more often than the version
  before: a note that leaves one provision and appears in another is moved, not new (E.R. 3 of 2015 moved
  "(2 of 2015 s. 73)" from the end of Cap. 138A into ss. 12, 19, 24B and 25). Nor is a law the provision already
  cited in words ("(L.N. 108 of 2015)") new when a later version turns those words into a linked note.

  Laws are Ordinances (`18 of 2012`), legal notices (`L.N. 130 of 2007`), government notices (`G.N.`, `G.N.A.`) and
  editorial revisions (`E.R. 1 of 2013`). A citation of a law of a later year in a source note of an earlier version is
  ignored and labelled (HKeL prints later editorial revisions into earlier versions): the commit says so in a
  `Date-note:`. A commencement notice is not an amending law and is not counted. Every change not credited by rule 1,
  and every labelled quirk ({n_flags:,}), is listed in [`data/labelled.tsv`](data/labelled.tsv).
- **Editorial revisions.** An E.R. is a revised printing made by the Department of Justice under the Legislation
  Publication Ordinance (Cap. 614), not an amending law, but it is what changed those files, so it is the author of
  its commit; the commit says "Editorial revision ... not an amending law" ({n_er:,} commits).
- **Date.** The version's date in the bulk file name, which is the day the version's text took effect. The same day's
  commits come in this order: the first version of each Cap., then one commit per law (ordinances, legal notices,
  government notices, editorial revisions, each by number) across all the Caps it changed that day, then candidate
  changes, then changes no law explains, then versions with no change.
- **Commits.** {n_start:,} first versions, {n_law:,} law commits ({n_laws:,} distinct laws), {n_cand:,} commits with
  candidate laws, {n_unexp:,} changes no law explains, and {n_same:,} versions whose English text is word for word the
  text of the version before (the source does not say why; perhaps the Chinese text changed), in the order they took
  effect, then one for this documentation.
  - The author is the law: `18 of 2012` at `ord-2012-18@hkel.invalid`, `L.N. 130 of 2007` at
    `ln-2007-130@hkel.invalid`, `E.R. 1 of 2013` at `er-2013-1@hkel.invalid`. The first version of each Cap. is
    authored by the Cap. itself (`Cap. 486 (text on 1 July 1997)`, `Cap. 634 (first version)`). The source names no
    enactment date, so there is no `Enacted:` trailer.
  - Candidate, unexplained and no-change commits are by `Department of Justice (HKeL)`.
  - Author and committer dates are noon in Hong Kong on the day the change took effect: UTC+8, with no summer time
    (Hong Kong has had none since 1979). The committer is `Lexifina <hong-kong-law@lexifina.com>`.
  - Trailers: `Kind:`, `Cited:` (the citation as printed in the new source notes), `Evidence:`, `In-force:`,
    `Affecting:`, `Candidate:`, `Date-note:`, `Consolidated:` (the version file and the first 16 hexadecimal digits
    of its sha256) and `Source:` (the dataset page).
  - Tags: each Cap.'s days (`cap-486/2012-10-01`) and each law (`ord/2012-18`; a law that took effect on several days
    has one tag per day, `ord/2012-18/2013-04-01`); {len(tags):,} in all.
- **Documentation commit.** Dated {today}, the day the data was retrieved, not the day of the run, so a later rebuild
  of the same data gives the same hash.

## Decisions made by hand

These choices were made when the tool was written, after looking at the data. They are in the code.

1. **The Caps.** Every Cap. with a dated version in the four past-version bulk files (English): {n_ord} ordinances and
   {len(built) - n_ord} items of subsidiary legislation, {n_files:,} files today. The first build held Cap. 383 and
   Cap. 486 only.
2. **The source note is the evidence.** Each provision prints the laws that made it; a change is credited to a law only
   on a citation that is new in the provision's own notes, or by date only where the source dates the provision to the
   day (labelled). Where two laws are possible, none is credited.
3. **No law is credited for the first version.** The record starts on 1 July 1997 with the text in force that day;
   earlier amendments are not in it.
4. **English only.** The Chinese texts are separate files of the same dataset and are not read.
5. **A new version with identical English text** is kept as an empty labelled commit rather than dropped, so every
   dated version of the source has a commit and a tag.

## What an AI model did

This repository was built in **Claude Code**, Anthropic's coding tool: {MODELS}, working from briefs by the user at
Lexifina: a private "git for law" repository for Hong Kong to the same standard as Lexifina's other corpora.

The model:

- **Researched the source:** the dataset page, the terms of use, the shape of the XML, its source notes and start
  periods.
- **Wrote all the code and text in this repository:** `tools/build.py`, `tools/reproduce.py`, `tools/check_repo.py`,
  `tools/test_repo.py`, `tools/hkhistory.py`, the README, this file and the licence, and chose the design described in
  them.
- **Ran the commands above** and checked the results.

The model did **not**:

- **Write or edit any legal text.** Every word of every provision and every citation is copied by the script from the
  bulk files.
- **Take part in building the history.** No AI model is called when the history is built or checked.

The user decided what was in scope and decides whether the repository is ever made public. The work was not reviewed
line by line by a lawyer. The bulk files are provided "as is" and the Government gives no warranty of accuracy; the
authoritative text of Hong Kong law is the one published by the Government in the Gazette and by the Department of
Justice on elegislation.gov.hk.

## Prior art

Lexifina's other corpora, whose rules this one follows (Estonia, Liechtenstein, Luxembourg, Monaco, Slovakia, Slovenia,
Malta, Swiss federal law, the Grundgesetz, UK legislation and the US Code). No code was copied from outside Lexifina.
"""
    (repo / 'REPRODUCE.md').write_text(text, encoding='utf-8', newline='\n')
