---
name: mom-update
description: Refresh the Sharesies NZ MoM Performance + Budgets figures and rebuild both the working doc and the client-facing visual report. Use when asked to update the MoM doc, run the weekly/monthly Sharesies numbers, refresh the performance report, or produce the client report. Pulls Meta and Google/YouTube automatically via MCP; prompts for the four manual channels.
---

# Sharesies MoM update

Refreshes one month of figures and regenerates both outputs. Takes a few minutes,
most of it waiting on you to paste the manual channels.

**Why this is a skill and not a cron job:** the Meta and Google numbers arrive
through MCP connectors that are authenticated to a Claude session. A standalone
script on a timer has no access to them. So the pull happens here, and everything
downstream is deterministic Python that can be re-run and diffed.

Run from the repo root. Target month is normally the current month (for an in-flight
check) or the one just finished (to close it off).

---

## 1. Establish the month

```bash
python3 scripts/new_month.py <YYYY-MM>     # skip if the file already exists
```

Creates `manual_input/<YYYY-MM>.yml`, pre-annotated with last month's values.

## 2. Pull Google + YouTube

Both live in **one** Google Ads account, `3844401760` (Sharesies NZ - Search).
They are split by campaign channel type: `VIDEO` is YouTube, everything else is
Google. Do not look for a separate YouTube account — there isn't one.

Two GAQL queries via `mcp__GAds_MCP__search`, with `<START>`/`<END>` as the
month's first and last day:

```sql
SELECT campaign.advertising_channel_type, metrics.cost_micros
FROM campaign WHERE segments.date BETWEEN '<START>' AND '<END>'
```
```sql
SELECT campaign.advertising_channel_type, segments.conversion_action_name,
       metrics.all_conversions
FROM campaign WHERE segments.date BETWEEN '<START>' AND '<END>'
```

Save the two result arrays as `data/raw/google-<YYYY-MM>.json`:

```json
{"cost": [ ...rows from query 1... ], "conversions": [ ...rows from query 2... ]}
```

Then:

```bash
python3 scripts/build_pull.py google <YYYY-MM> data/raw/google-<YYYY-MM>.json
```

> **The account carries three parallel tracking stacks** — `rudderstack_*`,
> `Sharesies - GA4 - MAIN (web) *`, and bare names like `save_account_opened`.
> They measure the same events three times. **Never sum them.** The doc has always
> used `rudderstack_*`; that is what `config/schema.yml` maps and what
> `build_pull.py` filters to. Everything else is ignored on purpose.

## 3. Pull Meta

`mcp__Meta_Ads_MCP__ads_get_ad_entities` on account `1432660143475665`:

- `level`: `ad_account`
- `fields`: `["amount_spent","cost_per_conversion","impressions"]`
- `time_range`: `{"since":"<START>","until":"<END>"}`
- `time_increment`: `"monthly"`

Save the returned entity object as `data/raw/meta-<YYYY-MM>.json`, then:

```bash
python3 scripts/build_pull.py meta <YYYY-MM> data/raw/meta-<YYYY-MM>.json
```

> **Why the odd shape:** this MCP surface exposes no raw action counts — `results`
> returns "Not available" and `actions` is rejected as a field. It *does* return
> `cost_per_conversion:offsite_conversion.fb_pixel_custom.<event>` per named pixel
> event, so conversions are recovered as `spend / cost_per_conversion`.
> `build_pull.py` asserts each result lands within 0.02 of a whole number and
> refuses the value otherwise — if you see that warning, Meta changed the field and
> the mapping needs revisiting rather than patching.

## 4. Fill in the manual channels

`TikTok`, `Reddit`, `Spotify`, `Stackadapt` have no connector. Open
`manual_input/<YYYY-MM>.yml` and fill in spend plus conversions per product from
each platform's UI. Ask the user for these — do not guess, and do not carry last
month's numbers forward.

Blank and `0` are different: `0` means measured zero, blank means not reported.
They render differently.

## 4b. Refresh campaign attribution

Product-level cost comes from campaign-level attribution, so the campaign pulls
need refreshing too. Two calls cover all months at once:

```sql
SELECT segments.month, campaign.name, campaign.advertising_channel_type,
       metrics.cost_micros
FROM campaign WHERE segments.date BETWEEN '<13-MONTHS-AGO>' AND '<TODAY>'
  AND metrics.cost_micros > 0
```

and `ads_get_ad_entities` at `level: campaign` with
`fields: ["id","name","amount_spent"]`, `time_increment: "monthly"` over the same
range. Save as `data/raw/google-campaigns-13mo.json` (list of
`{month, name, channel_type, cost}`) and `data/raw/meta-campaigns-13mo.json`
(list of `{month, name, spend}`), then:

```bash
python3 scripts/attribute.py            # dry run -- READ the output
python3 scripts/attribute.py --apply
```

The dry run aborts if any campaign with spend matches no rule in
`config/campaign_map.yml` — add a rule rather than letting it fall into a bucket.
It also prints channel-months where the doc total disagrees with the sum of its
campaigns; those are data-quality findings, and the split is still applied to the
stored total so client-facing figures do not move.

## 5. Merge, verify, render

```bash
python3 scripts/update_month.py <YYYY-MM>            # dry run -- read this output
python3 scripts/update_month.py <YYYY-MM> --apply    # add --force to replace figures
                                                     # imported from the original doc
python3 scripts/verify.py                            # arithmetic regression check
python3 scripts/render_workbook.py                   # -> reports/workbook.csv
python3 scripts/render_report.py                     # -> reports/report.html
```

`update_month.py` refuses to overwrite an original-doc figure unless you pass
`--force`, and prints every value it would change. Read the dry run before applying.
`--force` is right when refreshing the current month (a mid-month snapshot being
superseded); it is a red flag on a closed month.

`verify.py` should report **794 passed / 31 failed** and **39 channel-months
reconciled** for attribution. Those 31 failures are
pre-existing errors in the exported doc, catalogued in `docs/doc-discrepancies.md`.
A *new* failure means something broke — investigate before shipping.

## 6. Deliver

- `reports/workbook.csv` — paste back into the Google Sheet.
- `reports/report.html` — publish with the `Artifact` tool for the client link.
  Same file path each time keeps the same URL. Pass the existing `url` if the
  artifact was created in an earlier session.

Note in your summary: which month, which channels came from where, and anything
the verifier flagged.

---

## Notes

- Every fact carries a `source` (`doc`, `meta_ads`, `google_ads`, `manual`) in
  `data/history.csv`, so provenance is always answerable.
- CPAs, totals and budget variance are **never stored** — they are derived at
  render time. That is why `#DIV/0!` cannot come back.
- Event renames on either platform are a `config/schema.yml` edit, not a code edit.
- The report is Atlas-branded and deliberately single-theme (the identity is
  light-first). Products are faceted into per-product panels rather than given
  seven hues, because the five-colour palette can't separate that many series;
  KPI direction is carried by wording, not the red/green the brand rules out.
- LinkedIn is configured as `auto` but has spent $0 for the doc's whole history.
  If it restarts, wire up the LinkedIn MCP in `build_pull.py`.
