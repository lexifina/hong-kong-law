# Hong Kong: law history in git


The law of Hong Kong as a git history: one file per section, one commit per change on the day it took effect, and the law that made each change as the commit's author. `git blame` names the law behind every line; `git log` lists every change to a section; picking a date gives the text in force that day.

Part of [lexifina/global-law](https://github.com/lexifina/global-law), one git history for every country's law: this is Hong Kong's national law, which global-law reads at `hong-kong/national/acts/`.

**What is in it now:** every Cap. that the Department of Justice publishes with past versions: 2,912 Caps (794 ordinances and 2,118 items of subsidiary legislation), with 14,318 versions from 1 July 1997 to 1 August 2026, changed by 4,947 laws. [`caps.csv`](caps.csv) lists every Cap. with its versions; [`data/labelled.tsv`](data/labelled.tsv) lists every change not credited to a law by its own source note.

Each Cap. is a folder with one file per section or schedule, plus `intro.md` (the long title), `order.txt` (the order of the official text) and a `README.md` listing its provisions and their changes (`cap-57/s-041AA.md` is section 41AA, Annual leave, of the Employment Ordinance, Cap. 57; its subsidiary legislation is in `cap-57a/`, `cap-57b/` and `cap-57c/`).

The text is in English, as the Department of Justice publishes it; the Chinese equivalents of defined terms are kept as printed. The Chinese text is not part of this record.

## Questions as git commands

| Question | Command |
| --- | --- |
| Every change to section 41AA of the Employment Ordinance | `git log -p --word-diff -- cap-57/s-041AA.md` |
| Which law wrote each line of section 41AA? | `git blame cap-57/s-041AA.md` |
| Every change to the Ordinance, with the day each took effect and the law that made it | `git log --format="%h %(trailers:key=In-force,valueonly,separator=) %an" -- cap-57 ':!cap-57/README.md'` |
| Section 41AA as it stood on 1 January 2015 | `python tools/hkhistory.py 2015-01-01 cap-57 41AA` |

**Outside git**, we also host this record publicly, for free:

- **[Ask Claude about Hong Kong law](https://global-law.lexifina.com/v1/try_claude?country=hong-kong)**: opens Claude with a first question ready.
- **[Ask ChatGPT](https://global-law.lexifina.com/v1/try_chatgpt?country=hong-kong)**: the same question in ChatGPT.
- **[Call the API in your browser](https://global-law.lexifina.com/v1/search_law?query=annual+leave&jurisdictions=hong-kong)**: a search of Hong Kong law for "annual leave", returned as JSON. See the [documentation here](https://lexifina.com/api/global-law).

Both assistants read the record through the free Global law connector (MCP, `https://global-law.lexifina.com/mcp`); the first time, the chat gives you the link that adds it. Ask in English.

**Host it yourself easily.** All it takes is git and Python, and the tools run on your machine:

```sh
git clone --depth 1 https://github.com/lexifina/global-law && cd global-law
python3 tools/countries.py add hong-kong/national/acts
python3 tools/law.py show 2026-01-01 hong-kong/national/acts/cap-57/s-041AA.md
```

Opened in Claude Code, Cursor, VS Code or Codex, the clone also starts a local MCP server with the same tools ([MCP.md](https://github.com/lexifina/global-law/blob/main/MCP.md)).

## Dates

Each commit is dated at noon, Asia/Hong_Kong (UTC+8, no summer time), on the day the change took effect, and carries it in its `In-force:` trailer:

- the day is the date of the version in the Department of Justice's file name (`cap_486_20211008000000_en_p.xml`); the bulk data gives no enactment or Gazette date, so none is recorded;
- a law that took effect in steps has one commit and one tag per day (18 of 2012 changed Cap. 486 on 1 October 2012 and again on 1 April 2013: `ord/2012-18/2012-10-01`, `ord/2012-18/2013-04-01`);
- the first version of each Cap. is the text in force on 1 July 1997, or its first version if it was made later.

Each change is credited to the law whose citation is new in the provision's source notes ("(Added 18 of 2012 s. 3)"), as `18 of 2012 <ord-2012-18@hkel.invalid>` or `L.N. 130 of 2007`; the first version is credited to the Cap. itself (`Cap. 57 (text on 1 July 1997)`), and editorial revisions (`E.R. 3 of 2015`) to the revision, which says it is not an amending law. Where two or more laws are new in a provision, or no note or date explains a change, the commit is the publisher's (`Department of Justice (HKeL)`) and labelled; changes credited by the day alone carry `Evidence: date only`.

## How it is checked

- `tools/check_repo.py` reads every version of each Cap. back from git on the day it took effect and compares it, file by file, with the text parsed from the official XML: 14,318 versions, 0 mismatches.
- It then compares the whole Cap., word for word and again letters and digits only, with all the text of the official file, read without the build's parser: 0 mismatches (see [`REPRODUCE.md`](REPRODUCE.md)).
- `tools/test_repo.py` checks that blame names a law, that the text differs before and after an amendment, that every tag resolves and that every commit carries `In-force:`.
- A second build from the same bulk files gave the same 10,356 law commits and 19,682 tags with the same hashes; `data/versions.json` lists every file read with its sha256.

## What it does not show

- **The Basic Law, and case law.** The bulk data has only the Basic Law's current text, with no past versions and no source notes, so no history can be built from it; court decisions are not part of this record.
- **History before 1 July 1997.** Each Cap. starts with the text in force that day; 5 Caps. that the bulk files hold only as a placeholder (Cap. 41W, 61J, 93B, 374AB and 374AC) are not here.
- **The Chinese text.** 630 versions whose English text did not change (perhaps only the Chinese did) are empty labelled commits.
- **Which law made some changes.** 577 commits name two or more candidate laws and 873 changes no law explains; both are the publisher's.
- **Images** in schedules (forms, diagrams) are not in the text.
- **Versions after 2026-10-28**, when the bulk files were retrieved; the latest version took effect on 2026-08-01.

## Sources

| Source | Kind | Past versions | Notes |
| --- | --- | --- | --- |
| [Hong Kong e-Legislation, past versions](https://data.gov.hk/en-data/dataset/hk-doj-hkel-legislation-past) (Department of Justice, on DATA.GOV.HK) | Bulk data: every Cap. as XML (Hong Kong Legislation Model) | yes, every dated version | The text, the day each version took effect and the source notes naming each amending law; for information: the authoritative text is the one in the Gazette and on elegislation.gov.hk, which this repository does not use |

## Licence

See [`LICENSE`](LICENSE). The text is data of the Department of Justice, the Government of the Hong Kong Special Administrative Region, Hong Kong e-Legislation, obtained through DATA.GOV.HK; the Government owns the intellectual property rights in it, and the DATA.GOV.HK Terms and Conditions of Use allow its reproduction and distribution free of charge on their conditions. The history, commit messages, tables and tools are CC0 1.0.

No AI model wrote or edited legal text, and none is called when the history is built or checked; the tools and documentation were written by an AI model (see [`REPRODUCE.md`](REPRODUCE.md)).

## More

From [lexifina/global-law](https://github.com/lexifina/global-law):

- [FEATURES.md](https://github.com/lexifina/global-law/blob/main/FEATURES.md): every feature, and what every corpus must support (`git blame`, `law.py`, the MCP tools)
- [FAQ.md](https://github.com/lexifina/global-law/blob/main/FAQ.md): questions and answers · [CONTRIBUTING.md](https://github.com/lexifina/global-law/blob/main/CONTRIBUTING.md): proposing changes · [MCP.md](https://github.com/lexifina/global-law/blob/main/MCP.md): the MCP server · [REPRODUCE.md](https://github.com/lexifina/global-law/blob/main/REPRODUCE.md): how it was built · [CHANGELOG.md](https://github.com/lexifina/global-law/blob/main/CHANGELOG.md)
- [FRESHNESS.md](https://github.com/lexifina/global-law/blob/main/FRESHNESS.md): how current each corpus is · [Monitoring](https://github.com/lexifina/global-law/tree/main/monitoring): whether updates are running · [WATCHING.md](https://github.com/lexifina/global-law/blob/main/WATCHING.md): how each official source is watched for changes
- [performance/](https://github.com/lexifina/global-law/tree/main/performance): how fast the tools are, measured
- [visualisations/](https://github.com/lexifina/global-law/tree/main/visualisations): charts and bridges across the world's law
- [Vulnerabilities](https://github.com/lexifina/global-law/tree/main/vulnerabilities): mistakes in legislation as published
