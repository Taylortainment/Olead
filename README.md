# Sharesies NZ — MoM Performance + Budgets pipeline

Replaces the hand-updated *MoM Performance + Budgets* sheet with a small data
store, a few deterministic scripts, and a client-facing visual report.

Two outputs from one source of truth:

| Output | File | For |
|---|---|---|
| Working doc | `reports/workbook.csv` | paste back into the Google Sheet |
| Client report | `reports/report.html` | publish as a shareable link |

## The idea

The sheet held ~170 rows, but almost all of it was arithmetic on two kinds of
measured fact: **spend per channel per month** and **conversions per channel per
product per month**. Everything else — every CPA, every `Total`, the budget
variance row — was derived, and drifted whenever a formula missed a row.

So the store keeps only the facts (`data/history.csv`, one fact per line with its
provenance), and both outputs are rendered from it. Recomputing the old sheet from
those facts found **31 errors in it**, including a $8,098.73 spend understatement
and a Save figure reported 47% low — see [`docs/doc-discrepancies.md`](docs/doc-discrepancies.md).

## Where the numbers come from

| Channel | Source |
|---|---|
| Meta | Meta Ads MCP, account `1432660143475665` |
| Google | Google Ads MCP, account `3844401760`, non-`VIDEO` campaigns |
| YouTube | the *same* Google Ads account, `VIDEO` campaigns |
| TikTok, Reddit, Spotify, Stackadapt | manual — one small YAML file per month |
| LinkedIn | configured, but $0 for the doc's entire history |

There is no API connector available for the four manual channels, so they stay
manual. What changed is that the manual work is now one short file with last
month's values printed beside each field, instead of hunting cells across a wide
sheet.

## Branding

The client report carries the Atlas Digital identity — Navy/Violet/Purple/Lilac,
Plus Jakarta Sans with DM Mono for metadata labels, and the wordmark embedded as a
data URI (`scripts/_logo_b64.txt`) so the page stays self-contained.

Two consequences of staying inside the five-colour palette, both deliberate:

- **The report is single-theme.** The Atlas identity is light-first (Off-White page,
  Navy type), so rather than invent a dark palette the page commits to the light one
  and paints every colour explicitly, holding on any host background.
- **Products are faceted, not colour-coded.** Seven products can't be given seven
  distinguishable hues from a five-colour palette without going off-brand, so each
  product gets its own small-multiple panel in Purple and takes its identity from the
  panel title. Direction on the KPI chips is carried by wording — "more expensive" /
  "cheaper" — rather than the red/green the brand rules out.

## Weekly run

A Routine (`Sharesies MoM update (weekly)`) fires Mondays 8am NZ time and runs the
skill below, then asks for the four manual channels. It is bound to the Claude
session that holds the Meta and Google connectors, because this org can't attach
connectors to a Routine via the API — if it ever fires without them, recreate the
Routine from the claude.ai Routines UI and attach GAds MCP + Meta Ads MCP there.

Manually, or on demand:

Ask Claude to **run the MoM update** — that invokes
[`.claude/skills/mom-update/SKILL.md`](.claude/skills/mom-update/SKILL.md), which
does the MCP pulls, prompts for the manual channels, and renders both outputs.

```bash
python3 scripts/new_month.py     2026-09    # create the manual-entry stub
# ... Claude writes data/raw/{google,meta}-2026-09.json from the MCP pulls ...
python3 scripts/build_pull.py    google 2026-09 data/raw/google-2026-09.json
python3 scripts/build_pull.py    meta   2026-09 data/raw/meta-2026-09.json
python3 scripts/update_month.py  2026-09            # dry run
python3 scripts/update_month.py  2026-09 --apply
python3 scripts/verify.py                           # expect 794 passed / 31 failed
python3 scripts/render_workbook.py
python3 scripts/render_report.py
```

## Layout

```
config/schema.yml     channels, products, sourcing, platform event mapping
data/history.csv      the store: month, channel, metric, value, source
data/source_snapshot.csv   the original export, kept verbatim
data/raw/             raw MCP responses, as an audit trail
data/pulls/           normalised pull files ready to merge
manual_input/         one YAML per month for the connector-less channels
scripts/              lib · parse_source · build_pull · update_month
                      verify · render_workbook · render_report
docs/                 the discrepancy catalogue
```

## Design decisions worth knowing

- **CPAs and totals are never stored.** Deriving them at render time is why
  `#DIV/0!` cannot return, and why a `Total` can't quietly miss a row.
- **Blank ≠ 0.** Blank means not reported; `0` means measured zero. They render
  differently, so a channel that genuinely did nothing doesn't look like a gap.
- **Nothing overwrites silently.** `update_month.py` blocks changes to figures
  imported from the original doc unless you pass `--force`, and prints every diff.
- **Three tracking stacks exist on the Google account** (`rudderstack_*`, GA4, and
  bare names). They measure the same events three times and must never be summed.
  The mapping pins `rudderstack_*`, which is what the doc has always used.
- **Event renames are config, not code** — `config/schema.yml`.
- **Partial months are labelled.** The current month is flagged in the report and
  hatched on the charts, so an in-flight month is never read as a full one.

## Verifying

`python3 scripts/verify.py` recomputes every derived figure and diffs it against the
original export. It should report **794 passed / 31 failed**; those 31 are the
catalogued doc errors. A new failure means a regression — investigate it.
