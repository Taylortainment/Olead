"""Shared helpers for the Sharesies MoM pipeline.

The store (data/history.csv) is deliberately long/narrow and holds only
*measured* facts: spend and conversion counts. Everything the client doc
shows on top of that -- CPAs, channel totals, budget variance -- is derived
at render time, so a formula can never go stale or divide by zero.
"""
import csv
import os
import re
from datetime import date

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HISTORY = os.path.join(ROOT, "data", "history.csv")
SCHEMA = os.path.join(ROOT, "config", "schema.yml")

FIELDS = ["month", "channel", "metric", "value", "source"]

# Money metrics, listed explicitly. Do NOT switch this to a "spend" prefix
# test -- the Sharesies product named "Spend" stores as `spend_signup`, which
# is a conversion count, not currency.
MONEY_METRICS = {"spend_actual", "spend_forecast"}


def load_schema():
    import yaml
    with open(SCHEMA) as fh:
        return yaml.safe_load(fh)


def month_range(start, count):
    """['2024-09', '2024-10', ...] of length `count`."""
    y, m = (int(x) for x in start.split("-"))
    out = []
    for _ in range(count):
        out.append(f"{y:04d}-{m:02d}")
        m += 1
        if m == 13:
            y, m = y + 1, 1
    return out


def months_between(start, end):
    """Inclusive month list from start to end."""
    out, cur = [], start
    y, m = (int(x) for x in start.split("-"))
    while True:
        cur = f"{y:04d}-{m:02d}"
        out.append(cur)
        if cur == end:
            return out
        m += 1
        if m == 13:
            y, m = y + 1, 1
        if len(out) > 600:
            raise ValueError(f"month_range runaway: {start}..{end}")


def month_label(month, short=False):
    y, m = (int(x) for x in month.split("-"))
    names = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
             "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
    full = ["January", "February", "March", "April", "May", "June", "July",
            "August", "September", "October", "November", "December"]
    return f"{names[m-1]} {str(y)[2:]}" if short else f"{full[m-1]} {y}"


def month_bounds(month):
    """(first_day, last_day) as ISO strings for a YYYY-MM."""
    y, m = (int(x) for x in month.split("-"))
    first = date(y, m, 1)
    last = date(y + (m == 12), (m % 12) + 1, 1)
    last = date.fromordinal(last.toordinal() - 1)
    return first.isoformat(), last.isoformat()


_NUM_JUNK = re.compile(r"[,$\s\"']")


def parse_number(raw):
    """Parse a spreadsheet cell into a float, or None if it isn't a number.

    Handles the quirks present in the exported doc:
      '#DIV/0!' / '-' / ''      -> None   (missing, not zero)
      '-$171.70'                -> -171.70
      '$8.098.73'               -> 8098.73  (typo'd thousands separator)
      '"1,150"'                 -> 1150.0
    """
    if raw is None:
        return None
    s = str(raw).strip()
    if s in ("", "-", "--", "#DIV/0!", "#REF!", "#N/A", "#VALUE!", "N/A"):
        return None
    neg = s.startswith("-") or (s.startswith("(") and s.endswith(")"))
    s = _NUM_JUNK.sub("", s).lstrip("-").strip("()")
    if s.count(".") > 1:
        # '8.098.73' -> the leading dots are mistyped thousands separators
        head, _, tail = s.rpartition(".")
        s = head.replace(".", "") + "." + tail
    if s in ("", "."):
        return None
    try:
        val = float(s)
    except ValueError:
        return None
    return -val if neg else val


def read_store(path=HISTORY):
    """-> {(month, channel, metric): {'value': float, 'source': str}}"""
    store = {}
    if not os.path.exists(path):
        return store
    with open(path, newline="") as fh:
        for row in csv.DictReader(fh):
            val = parse_number(row["value"])
            if val is None:
                continue
            store[(row["month"], row["channel"], row["metric"])] = {
                "value": val,
                "source": row.get("source", ""),
            }
    return store


def write_store(store, path=HISTORY):
    """Deterministic ordering so git diffs stay readable week to week."""
    rows = sorted(store.items(), key=lambda kv: (kv[0][0], kv[0][2], kv[0][1]))
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=FIELDS)
        w.writeheader()
        for (month, channel, metric), rec in rows:
            val = rec["value"]
            w.writerow({
                "month": month,
                "channel": channel,
                "metric": metric,
                "value": f"{val:.2f}" if metric in MONEY_METRICS else f"{val:g}",
                "source": rec["source"],
            })
    return len(rows)


def get(store, month, channel, metric):
    rec = store.get((month, channel, metric))
    return rec["value"] if rec else None


def total(store, month, metric, channels):
    """Sum across channels; None if no channel reported anything."""
    vals = [get(store, month, c, metric) for c in channels]
    vals = [v for v in vals if v is not None]
    return sum(vals) if vals else None


def cpa(spend, conversions):
    if spend is None or not conversions:
        return None
    return spend / conversions


def fmt_money(v, dp=2):
    if v is None:
        return ""
    return f"-${abs(v):,.{dp}f}" if v < 0 else f"${v:,.{dp}f}"


def fmt_int(v):
    return "" if v is None else f"{round(v):,}"
