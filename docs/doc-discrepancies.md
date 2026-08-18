# Errors found in the exported doc

Produced by `scripts/verify.py`, which recomputes every total, CPA and budget
variance from the stored spend and conversion facts and diffs the result against
the values that were in the exported CSV.

**Result: 794 checks passed, 31 failed.** All 31 are faults in the source doc, not
in the derivation. They are listed here so the fixes are traceable, because several
changed numbers that were shown to the client.

---

## 1. January 2025 spend understated by $8,098.73

Stackadapt's January 2025 spend was typed **`$8.098.73`** — two decimal points. The
sheet treated the cell as text, so the `SUM` skipped it entirely.

| | |
|---|---|
| Doc total | `$28,965.58` |
| Actual total | `$37,064.31` |
| **Understated by** | **`$8,098.73`** (28%) |

Every January 2025 CPA is correspondingly overstated, since the denominator was
short. The parser repairs the typo (`parse_number` collapses mistyped thousands
separators) and the total recomputes correctly.

## 2. Total rows that silently dropped a channel

Thirteen `Total` cells didn't cover every channel row beneath them. The two large
ones both dropped Reddit:

| Month | Product | Doc total | Actual | Missing |
|---|---|---|---|---|
| Sep 2025 | Save | 455 | **668** | Reddit's 213 |
| Jul 2025 | Subscription | 1,571 | **1,797** | 226 |
| Jan 2026 | Crypto | 7,489 | **7,763** | 274 |
| Aug 2025 | Save | 175 | **187** | Reddit's 12 |
| Jan 2026 | Insure (Payment) | 83 | **89** | 6 |
| Dec 2024 | KiwiSaver | 68 | **73** | 5 |
| Jul 2025 | Insure (Quote) | 1,592 | **1,597** | Google's 5 |
| Aug 2025 | Insure (Quote) | 846 | **848** | 2 |
| Dec 2025 | KiwiSaver | 457 | **454** | doc **over** by 3 |
| Apr 2025 · Oct 2025 · Nov 2025 · Jan 2026 | Subscription / KiwiSaver | — | +1 each | YouTube's single conversion |

September 2025 Save was reported to the client as **455 when it was 668** — a 47%
understatement.

## 3. Forecast row inconsistent with the channel forecast rows

February 2026's headline forecast reads `$161,000`, but the channel forecast rows
below it sum to `$147,054`. The `Difference` row inherits the error:

| | Doc | Actual |
|---|---|---|
| Feb 2026 forecast | `$161,000` | `$147,054` |
| Feb 2026 difference | `$22,247.33` | `$8,301.33` |

Separately, May–Oct 2025 and Apr–May 2026 carry a headline forecast with no channel
breakdown at all. That is just history — the renderer falls back to the headline
figure for those months rather than showing zero.

## 4. Roughly ten CPA cells reading `$0.00` where a real CPA existed

For example Dec 2024 Reddit KiwiSaver: $430.35 spend against 6 conversions is
**$71.73**, shown as `$0.00`. Others: Reddit KiwiSaver Jan–Mar 2025, Google
KiwiSaver Mar 2025 and Jul–Aug 2026, YouTube Insure (Quote) Aug 2025, YouTube
Subscription Oct 2025 / Jan–Apr 2026.

These can't recur — CPAs are no longer stored, only derived.

---

## A note on the CPA method itself

Not an error, but worth stating plainly: every CPA in the doc divides a channel's
**entire** spend by **one** product's conversions. Since one channel's spend drives
several products simultaneously, this inflates every product's CPA, and the
per-product CPAs cannot be compared with each other — they share a numerator.

The pipeline reproduces the convention exactly, to keep continuity with two years
of history. The client report labels the method openly and presents each product's
CPA as a trend over time rather than as a cross-product ranking.

A genuinely comparable version would apportion channel spend across products. That
is a methodology decision for the team, not something to change silently.
