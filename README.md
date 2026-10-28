# Hong Kong law, change by change

Every Cap. of the laws of the Hong Kong Special Administrative Region that the Department of Justice publishes with past
versions, as a git repository, in English: the ordinances (Cap. 1 to Cap. 600-odd, such as the Personal Data (Privacy)
Ordinance, Cap. 486) and the subsidiary legislation made under them (Cap. 486A, ...). Each amending law is one commit,
credited to that law and dated the day it took effect, at noon in Hong Kong. The history starts on 1 July 1997. The text
is the version text that the Department of Justice publishes as bulk data on [DATA.GOV.HK](https://data.gov.hk).
[`caps.csv`](caps.csv) lists every Cap. with its versions.

Each Cap. is a folder (`cap-486/`) with one file per section or schedule (`s-002.md`, `sch-1.md`), the opening matter
(`intro.md`) and any closing matter (`outro.md`). `order.txt` in the folder lists the files in the order of the
official text on that day; the file names cannot give it, because newer Caps put s. 3AA before s. 3A and older ones
after it. A line of text that begins with `#` or `- ` is printed with a backslash before it (`\# Commencement date`),
so it is not read as a heading or a list item. A table row is one line with its cells separated by ` | `; a `|`
printed in the text is written `\|`.

## The questions, as git commands

| Question | Command |
| --- | --- |
| What did section 14 of the Personal Data (Privacy) Ordinance say on 1 January 2010? | `python tools/hkhistory.py 2010-01-01 cap-486 14` |
| The whole Ordinance as it stood in 2000 | `python tools/hkhistory.py 2000-01-01 cap-486` |
| The Bill of Rights Ordinance, section 3, on 1 January 1998 | `python tools/hkhistory.py 1998-01-01 cap-383 3` |
| Which law wrote each line of section 2 (the definitions)? | `git blame cap-486/s-002.md` |
| Every change to section 14, with the law and the day | `git log --follow cap-486/s-014.md` |
| Everything one law changed on one day | `git show --stat ord/2012-18/2013-04-01` |
| What changed in Cap. 486 on one day | `git show --stat cap-486/2021-10-08` |
| The commit that holds a day's text, and why it was made | `python tools/hkhistory.py 2015-06-01 cap-486 --commit` |
| Everything one law changed, across all Caps, on one day | `git show --stat ord/2024-6` |
| The laws with all their dates | [`laws.csv`](laws.csv) |
| Changes credited by date only (no new source note) | `git log --grep="Evidence: date only"` |
| Changes no law explains | `git log --grep="Kind: Change no law explains"` |
| Versions whose English text did not change | `git log --grep="Kind: Version with no change"` |
| Laws made in 2012 that changed Cap. 486 | `git log --format="%an %s" --author=" of 2012" -- cap-486` |

## The dates, and which one we use

A Hong Kong law has the day it was enacted or made, the day it was published in the Gazette, and the day it took effect.
**Commits are dated the day the change took effect**, at noon in Hong Kong (UTC+8; Hong Kong has no summer time): that is
the day that decides which text applies, and it is the date of the version in the Department of Justice's file. Many laws
take effect in steps: 18 of 2012 changed Cap. 486 on 1 October 2012 and again on 1 April 2013, which are two commits and two
tags. The bulk data gives no enactment or gazette date, so this repository records none. Every commit carries an
`In-force: YYYY-MM-DD` trailer. To ask what the law was on a day with plain git, use the end of that day:
`git rev-list -1 --before="2013-04-01T23:59:59+08:00" main -- cap-486` (a bare date is read at the time of day you run
it). `tools/hkhistory.py` does this by the trailer.

## What "author" means

The author of a commit is the law that made the change: `18 of 2012` (an Ordinance, with an address ending
`@hkel.invalid`, which cannot exist), `L.N. 130 of 2007` (a legal notice), so `git blame` names the law. Each provision in
the source prints the laws that added, amended or repealed it ("(Added 18 of 2012 s. 3. Amended 32 of 2021 s. 3)"), and a
change is credited to the law whose citation is new in that provision's notes. Rules, each labelled in the commit:

- Where two or more laws are new in a provision, the change is credited to none of them: it is committed by the
  `Department of Justice (HKeL)`, with the laws named in `Candidate:` trailers.
- Where no note is new but the added text cites one law in words that the provision did not cite before (the daily
  specifications printed in editorial notes, "G.N. (E.) 212 of 2020"), the change is credited to it, labelled.
- Where no note is new but the source dates the provision to the day, and exactly one law is new anywhere in that version,
  the change is credited to it "by date only" (`Evidence: date only`). On an editorial revision day, when the version
  prints a note of that revision on the Cap. ("(Format changes—E.R. 3 of 2015)") and the other laws newly cited in it
  were already cited in the Cap. before, those are reprinted citations, and the change is credited to the revision by
  date only (`Evidence: date only, editorial revision`).
- A citation that only moves from one provision to another (the whole Cap. prints it no more often than before) is not
  new, and neither is a law the provision already cited in words before a later version made those words a link.
- A change that no note and no date explains is committed by the publisher and labelled.
- A source note that cites a later law than the version (HKeL prints E.R. 1 of 2013 into the version of 1 October 2012) is
  ignored and labelled.
- **E.R. 1 of 2013** is an editorial revision (a revised printing by the Department of Justice: part headings, the way defined terms are
  printed, spent sections omitted), not an amending law. It changed 55 files on 25 April 2013, so it is the author of that
  commit, and the commit says what it is.
- The first version of each Cap. (the text in force on 1 July 1997) is authored by the Cap. itself: the history before the
  handover is not in the record.
- Blame credits whole lines. Where two laws changed words of one line, the later one is credited with the line; use
  `git log -p --word-diff` for the words.

## How it is checked

`tools/check_repo.py` reads every version of each Cap. back from git on the day it took effect and compares it with the
official file: file by file with the text parsed from the XML (0 mismatches), and word for word with all the words of the
XML, read independently of the parser. `tools/test_repo.py` checks that the commands above work. The results are in
[`REPRODUCE.md`](REPRODUCE.md).

## Files

Each Cap. is a folder named after its number in lower case (`cap-486/`, `cap-486a/`). Each section is one file named after
its number: `cap-486/s-033.md` is section 33, `cap-486/s-002A.md` section 2A (the rules, regulations and paragraphs of
subsidiary legislation carry the same identifiers in the source and the same file names); `sch-1.md` is Schedule 1;
`intro.md` is the long title or title, commencement note and enacting words; `outro.md` is matter after the last
provision. The headings of the parts that begin with a section are `##` lines at the top of its file; its number and
heading are the `#` line; each subsection is one line, and paragraphs, subparagraphs and definitions are list items. The
source notes that print the amending law ("(Added 18 of 2012 s. 3)") and the commencement notes are part of the text and are
kept. A repealed section stays as a file holding its heading and the note that repealed it. A provision not yet in
operation is in the file with the official note "(Not yet in operation)". Each Cap.'s folder has a `README.md` listing its
files with how often each changed. Images in schedules (forms, diagrams) are not in the text.

## What it does not show

- The Basic Law and the other instruments: the bulk data has only the Basic Law's current text, with no versions and no
  source notes, so it has no history; instruments are not Caps.
- History before 1 July 1997, and Caps. that the bulk files hold only as an undated placeholder ("will be incorporated
  ... as soon as possible"); see `REPRODUCE.md`.
- Which of two laws of the same day made a change (above), or the words of a law that is not in the Cap.'s notes.
- The Chinese text. The English text prints the Chinese equivalents of defined terms in brackets; they are kept as printed.
- Versions of the Chinese text that changed alone: versions with the same English text as the one before are empty
  labelled commits.

The version text is for information: the authoritative text is the one published in the Gazette and by the Department of
Justice on elegislation.gov.hk.

## How it is built

`tools/build.py` reads the bulk files and writes this repository from scratch; the same data gives the same hashes. Every
step, the software, the decisions made by hand and what an AI model did are in [`REPRODUCE.md`](REPRODUCE.md).
[`corpus.json`](corpus.json) describes the corpus for tools that read several of Lexifina's law repositories.
After a rebuild, `git fetch --force --tags` replaces stale tags in an existing clone.

## Licence

Source: Department of Justice, the Government of the Hong Kong Special Administrative Region, Hong Kong e-Legislation, as
published on DATA.GOV.HK. The Government owns the intellectual property rights in the Data. Reuse is governed by the
DATA.GOV.HK Terms and Conditions of Use; see [`LICENSE`](LICENSE) for the text and for what is not settled. **This
repository is private and stays private until its reuse terms are cleared.**
