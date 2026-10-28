# How this history was made, and how to make it again

This file records exactly how the repository was built: the sources, the commands, the software, the decisions made
by hand, and what an AI model did and did not do. The build writes it, so it describes the build that made this
commit.

## Short version

```sh
git clone https://github.com/lexifina/hong-kong-law && cd hong-kong-law
pip install lxml
python -X utf8 tools/build.py --repo ../rebuilt --today 2026-10-28
git -C ../rebuilt rev-parse main        # the same hash as this repository's main
python -X utf8 tools/check_repo.py --repo ../rebuilt
python -X utf8 tools/test_repo.py --repo ../rebuilt
```

`tools/build.py` needs Python 3.12 or later with `lxml`, git and curl. It downloads the bulk files below (or reads
them from its own cache, `.cache/` next to the script) and writes this repository into `--repo`, reading the Caps with
a pool of up to 8 parse workers and writing the history with `git fast-import`. With the same files and the same
`--today` it gives the same commits with the same hashes. `data/versions.json` lists every bulk file with its sha256
and every version file read with its sha256, so a rebuild can show it read the same bytes. The Department of Justice
replaces the bulk files from time to time; then the hashes change too. (`check_repo.py` and `test_repo.py` read the
bulk files from the same cache, so run them from a checkout of Lexifina's `scripts/hong-kong-law` or after a build that
filled `.cache/`.)

## Sources

All legal text and all information about versions and amending laws come from the **Hong Kong e-Legislation (HKeL)
bulk files** that the Department of Justice publishes on DATA.GOV.HK (https://data.gov.hk/en-data/dataset/hk-doj-hkel-legislation-past). Nothing was typed in, summarised
or rewritten. **Only the bulk files were fetched.** The website elegislation.gov.hk was not: its robots.txt says
`Disallow: /` and it runs a JavaScript client check.

| Bulk file | Bytes | sha256 | Last-Modified |
| --- | ---: | --- | --- |
| `hkel_p_leg_cap_1_cap_200_en.zip` | 402,720,930 | `27c20415530a0b421d38ce1a1d7776f93f097364b3ac90d8dbd7a3a184f837e5` | Mon, 12 Oct 2026 13:00:05 GMT |
| `hkel_p_leg_cap_201_cap_400_en.zip` | 1,049,686,792 | `98134d3688ad715c3c67f6db89205ef9baa5a85f8a414f69fc69af092724656e` | Mon, 21 Sep 2026 13:00:04 GMT |
| `hkel_p_leg_cap_401_cap_600_en.zip` | 481,489,025 | `95122730c28f5f79125036a87c5df271693e40dff51fd99e7816b1bedc2e2036` | Mon, 19 Oct 2026 13:00:05 GMT |
| `hkel_p_leg_cap_601_cap_end_en.zip` | 150,503,200 | `159858c76808c54937befe5980f26e26d4e2d4a1dbe8dac697b4d027b089099a` | Mon, 19 Oct 2026 13:00:05 GMT |

Each bulk file is one ZIP with a folder per Cap. and an XML file per dated version
(`cap_486_en_p/cap_486_20211008000000_en_p.xml`), in the Hong Kong Legislation Model (HKLM). The build read 14318
version files of 2912 Caps.: 794 ordinances and 2118 items of subsidiary legislation
(Cap. 486A, ...). [`caps.csv`](caps.csv) lists every Cap. with its versions and files.

**Fetch rate.** four ZIP files, each downloaded once with curl, one request at a time (one HEAD request and one GET per file); every build after that read only the cache. The data was retrieved on 2026-10-28; the response headers are kept next to each file in the
cache.

**Left out.** 35 files are named with dashes instead of a date (`cap_634_--------------_en_p.xml`): each is a
placeholder saying that the text "will be incorporated in Hong Kong e-Legislation as soon as possible", not a version,
and is not read. 5 Caps. have only such a placeholder and are not in the record
(Cap. 374AB, Cap. 374AC, Cap. 41W, Cap. 61J, Cap. 93B). 1050 versions dated before 1 July 1997 (the text of 30
June 1997, before the handover) are left out where a version of 1 July 1997 exists, and 4 versions are left out
because a later file of the same day replaces them (two files of one day, 000000 and 110000). All are listed in
`data/versions.json`.

**Terms of use.** DATA.GOV.HK's Terms and Conditions of Use (https://data.gov.hk/en/terms-and-conditions, version 1.2, last updated 26 May 2025, checked
again on 2026-10-28) allow browsing, downloading, distributing and reproducing the Data for commercial and non-commercial
purposes free of charge on conditions, among them that the source of the Data is identified clearly and the
Government's ownership of the intellectual property rights acknowledged, and that the user indemnifies the Government.
data.gov.hk has no robots.txt (404) and the file host has no robots rules. See `LICENSE`. This repository is private.

**The Basic Law** is in the dataset as instrument A101 (`hkel_c_instruments_en.zip`, the current version) but has no
past versions (the past instruments file holds only A303, A305, A401, A405, A501, A601 and A602), and its XML carries no
`startPeriod` or source notes, so no history of it can be built from this dataset. Instruments are not Caps. and are
not in the record.

## The build, step by step

1. `python -X utf8 scripts/hong-kong-law/build.py --today 2026-10-28` in Lexifina's own repository downloaded the bulk
   files into its cache and wrote this repository. `tools/build.py` here is the same file as
   `scripts/hong-kong-law/build.py` there (git blob `0f1bad4a2d4c9fa018432c8d55b2fadacf53a5d4`), with `tools/reproduce.py`, which writes this file,
   `tools/check_repo.py` and `tools/test_repo.py`. Every later build ran with `--offline`, from the cache.
2. `python -X utf8 scripts/hong-kong-law/check_repo.py` read every version of each Cap. back from this repository on the
   day it took effect (the last commit whose `In-force:` is on or before it, as `tools/hkhistory.py` reads it) and
   compared it file by file with the official text parsed afresh from the cached XML; then it compared the whole Cap.,
   word for word and again letters and digits only (casefolded), with all the text under `<main>` of the official
   file, read without the build's parser. Result: `14318 versions checked (824581 files), 0 mismatches; 14318 versions word for word (304799082 words) against the whole official text, 0 mismatches; letters and digits 0 mismatches`.
3. `python -X utf8 scripts/hong-kong-law/test_repo.py --record` ran the functional smoke test against this repository
   (6 of 6 passed):
   - pass: blame names a law: cap-486/s-002.md lines by 12 of 2000, 12 of 2015, 17 of 2018, 18 of 2006, 18 of 2012, 32 of 2021, 4 of 1998, 5 of 2002, Cap. 486 (text on 1 July 1997), E.R. 1 of 2013
   - pass: text before and after an amendment: cap-486/s-002.md 2021-10-07 != 2021-10-08; cap-383/s-003.md 1998-02-27 != 1998-02-28
   - pass: log --follow in date order: cap-486/s-002.md 10 commits; cap-486/s-014.md 4 commits; cap-486/s-058.md 5 commits
   - pass: tags resolve, In-force on every commit: 19682 tags resolve; 10357 commits carry In-force and a subject of at most 72 characters
   - pass: only the documentation commit is by Lexifina: only the documentation commit c09c3ad5a0 is by Lexifina; 7860 distinct authors
   - pass: README commands run: 13 README commands ran and printed output
4. `python -X utf8 scripts/hong-kong-law/build.py --offline --verify-rebuild` built the repository a second time from
   the same cache into a temporary folder and compared the hashes. A second build from the same cache into an empty folder gave the same history: the last law commit was `69dca16d7896ea842d7c0fb47d6a5bf2a0540391` in both, and every one of the 10356 law commits and 19682 tags had the same hash.
5. The build was run once more to write these results into this file, and the final `main` was rebuilt again in a
   temporary folder and compared hash for hash before it was pushed.
6. The first build (Cap. 383 and Cap. 486 only) was published on 2026-10-28. This full build replaced it once, by a
   force-push agreed with Lexifina's global-law coordinator, because the new Caps' changes reach back to 1997 and
   `main` must stay in the order the changes took effect. From then on `main` is append-only.

It ran with Python 3.12.10, lxml 6.1.3 and git version 2.46.0.windows.1 on Windows 11. No network service other than DATA.GOV.HK's file host
(`resource.data.one.gov.hk`) is involved.

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
  `\|`. Each Cap.'s `order.txt` lists its files in the
  order of the official text on that day.
- **Versions.** Every dated file in the bulk file is a version. History starts on 1 July 1997: the newest version
  dated on or before that day stands for it. A Cap. made later starts with its first version.
- **Changes.** Consecutive versions are compared file by file: 57,482 changes of a file were found.
- **Cause.** Each provision prints the laws that added, amended or repealed it, as links in its source notes. Tried in
  this order, for each changed file:
  1. a citation (of a law of the version's year or earlier) is new in the file's source notes, compared with the
     version before, and it is one law: that law (37,738 file changes);
  2. two or more laws are new in it: none is credited; the publisher commits it and names them as candidates
     (874);
  3. nothing is new in its notes but the added text cites a law in words and names the version's day ("On and from
     18 July 1997, ... (126 of 1997 s.2)"): that law, labelled (740);
  4. nothing is new in its notes, the source gives the provision (or the part heading above it) a `startPeriod` of the
     version's day, and exactly one law is new anywhere in the Cap. in this version: that law, by date only, labelled
     (11,249);
  5. the same, on an editorial revision day: exactly one E.R. is new in the version, the text the version adds prints
     it in a note on the Cap. ("(Format changes—E.R. 3 of 2015)"), and every other law new in the version was already
     cited in the Cap. (in a note or in words) the day before, so those are reprinted citations: the E.R., by date
     only, labelled `Evidence: date only, editorial revision` (407);
  6. the same, with more than one law new in the version: candidates (1,497);
  7. nothing is new in its notes, but the added text cites exactly one law of the version's year in words that the
     provision did not cite before (the daily specifications printed in editorial notes, "G.N. (E.) 212 of 2020"):
     that law, labelled `Evidence: plain citation only` (308);
  8. otherwise: no law; the publisher commits it and labels it (4,669).

  A citation is new only if the whole Cap. prints it (the same law, printed the same) more often than the version
  before: a note that leaves one provision and appears in another is moved, not new (E.R. 3 of 2015 moved
  "(2 of 2015 s. 73)" from the end of Cap. 138A into ss. 12, 19, 24B and 25). Nor is a law the provision already
  cited in words ("(L.N. 108 of 2015)") new when a later version turns those words into a linked note.

  Laws are Ordinances (`18 of 2012`), legal notices (`L.N. 130 of 2007`), government notices (`G.N.`, `G.N.A.`) and
  editorial revisions (`E.R. 1 of 2013`). A citation of a law of a later year in a source note of an earlier version is
  ignored and labelled (HKeL prints later editorial revisions into earlier versions): the commit says so in a
  `Date-note:`. A commencement notice is not an amending law and is not counted. Every change not credited by rule 1,
  and every labelled quirk (261), is listed in [`data/labelled.tsv`](data/labelled.tsv).
- **Editorial revisions.** An E.R. is a revised printing made by the Department of Justice under the Legislation
  Publication Ordinance (Cap. 614), not an amending law, but it is what changed those files, so it is the author of
  its commit; the commit says "Editorial revision ... not an amending law" (201 commits).
- **Date.** The version's date in the bulk file name, which is the day the version's text took effect. The same day's
  commits come in this order: the first version of each Cap., then one commit per law (ordinances, legal notices,
  government notices, editorial revisions, each by number) across all the Caps it changed that day, then candidate
  changes, then changes no law explains, then versions with no change.
- **Commits.** 2,912 first versions, 5,364 law commits (4,947 distinct laws), 577 commits with
  candidate laws, 873 changes no law explains, and 630 versions whose English text is word for word the
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
    has one tag per day, `ord/2012-18/2013-04-01`); 19,682 in all.
- **Documentation commit.** Dated 2026-10-28, the day the data was retrieved, not the day of the run, so a later rebuild
  of the same data gives the same hash.

## Decisions made by hand

These choices were made when the tool was written, after looking at the data. They are in the code.

1. **The Caps.** Every Cap. with a dated version in the four past-version bulk files (English): 794 ordinances and
   2118 items of subsidiary legislation, 71,263 files today. The first build held Cap. 383 and
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

This repository was built in **Claude Code**, Anthropic's coding tool: Claude Sonnet 5.5 (model id `claude-sonnet-5-5`) wrote the first build (Cap. 383 and Cap. 486); Claude Opus 5.5 (model id `claude-opus-5-5`) extended it to every Cap. in the bulk files, working from briefs by the user at
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
