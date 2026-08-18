"""Regenerate the working doc (wide CSV) from the normalized store.

Output matches the original layout section-for-section so it can be pasted
straight back into the Google Sheet -- but every total, CPA and variance row
is computed fresh from the stored facts, so the arithmetic is always right.

Usage:  python3 scripts/render_workbook.py [--out PATH] [--from YYYY-MM]
"""
import argparse
import csv
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lib


def build_rows(store, schema, months):
    channels = schema["channels"]
    products = schema["products"]
    cur = schema["currency"]
    R = []

    def blank():
        R.append([""] * (2 + len(months)))

    def section(title):
        R.append(["", "", title] + [""] * (len(months) - 1))

    def header(first, label_row=True):
        R.append(["", first] + [lib.month_label(m) for m in months])

    def row(label, cells):
        R.append(["", label] + cells)

    blank()
    R.append(["", "", "MoM Performance + Budgets"] + [""] * (len(months) - 1))
    blank()

    # ---- summary budget block -------------------------------------------
    section(f"Total Monthly Media Budget ${cur}")
    header("Budget")
    actual = {m: lib.total(store, m, "spend_actual", channels) for m in months}
    fc = {}
    for m in months:
        s = lib.total(store, m, "spend_forecast", channels)
        if s is None:
            s = lib.get(store, m, "__TOTAL__", "spend_forecast")
        fc[m] = s
    row("Actual", [lib.fmt_money(actual[m]) for m in months])
    row("Forecasted", [lib.fmt_money(fc[m]) for m in months])
    row("Difference", [
        lib.fmt_money(fc[m] - actual[m]) if (fc[m] is not None and actual[m] is not None) else ""
        for m in months])
    blank()

    # ---- channel spend --------------------------------------------------
    for metric, title in (("spend_forecast", f"Channel Spend ${cur} - Forecasted"),
                          ("spend_actual", f"Channel Spend ${cur} - Actual")):
        section(title)
        header("Channel")
        for ch in channels:
            row(ch, [lib.fmt_money(lib.get(store, m, ch, metric)) for m in months])
        row("Total", [lib.fmt_money(lib.total(store, m, metric, channels)) for m in months])
        blank()

    # ---- per-product conversions + CPA ----------------------------------
    for p in products:
        key, label = p["key"], p["label"]
        pch = schema["product_channels"][key]

        section(f"{label} Conversions")
        header("Channel")
        for ch in pch:
            row(ch, [lib.fmt_int(lib.get(store, m, ch, key)) for m in months])
        totals = {m: lib.total(store, m, key, pch) for m in months}
        row("Total", [lib.fmt_int(totals[m]) for m in months])
        blank()

        # Attributed basis: the campaigns that actually targeted this product.
        # Blank where a channel has no campaign-level data -- a blank is honest,
        # a number would not be.
        section(f"{label} CPA ${cur} - attributed")
        header("Channel")
        for ch in pch:
            row(ch, [lib.fmt_money(lib.cpa(lib.get(store, m, ch, lib.SPEND_P + key),
                                          lib.get(store, m, ch, key))) for m in months])
        a_sp, a_cv = {}, {}
        for m in months:
            sp = [lib.get(store, m, c, lib.SPEND_P + key) for c in pch]
            sp = [v for v in sp if v is not None]
            a_sp[m] = sum(sp) if sp else None
            a_cv[m] = sum(v for c in pch
                          for v in [lib.get(store, m, c, key)]
                          if v is not None and lib.get(store, m, c, lib.SPEND_P + key) is not None)
        row("Total", [lib.fmt_money(lib.cpa(a_sp[m], a_cv[m])) for m in months])
        blank()

        section(f"{label} attributed spend ${cur}")
        header("Channel")
        for ch in pch:
            row(ch, [lib.fmt_money(lib.get(store, m, ch, lib.SPEND_P + key)) for m in months])
        row("Total", [lib.fmt_money(a_sp[m]) for m in months])
        blank()

        # Legacy basis, retained so two years of history stays traceable. It
        # divides a channel's ENTIRE spend by this one product's conversions,
        # which inflates every figure -- clearly labelled so it is not reused.
        section(f"{label} CPA ${cur} - LEGACY (all channel spend / product convs)")
        header("Channel")
        for ch in pch:
            row(ch, [lib.fmt_money(lib.cpa(lib.get(store, m, ch, "spend_actual"),
                                          lib.get(store, m, ch, key))) for m in months])
        row("Total", [lib.fmt_money(lib.cpa(actual[m], totals[m])) for m in months])
        blank()

    return R


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=os.path.join(lib.ROOT, "reports", "workbook.csv"))
    ap.add_argument("--from", dest="frm", default=None,
                    help="first month to render, e.g. 2025-09 (default: all)")
    a = ap.parse_args()

    schema = lib.load_schema()
    store = lib.read_store()
    all_months = sorted({k[0] for k in store})
    months = [m for m in all_months if not a.frm or m >= a.frm]

    rows = build_rows(store, schema, months)
    os.makedirs(os.path.dirname(a.out), exist_ok=True)
    with open(a.out, "w", newline="") as fh:
        csv.writer(fh).writerows(rows)
    print(f"wrote {a.out}  ({len(rows)} rows x {len(months)} months: "
          f"{months[0]} .. {months[-1]})")


if __name__ == "__main__":
    main()
