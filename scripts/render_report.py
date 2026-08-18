"""Build the client-facing visual report (single self-contained HTML file).

All derivation happens here in Python -- the same helpers the workbook
renderer uses -- and the page receives finished series. The browser only
draws, so the report and the workbook can never disagree.

Usage: python3 scripts/render_report.py [--months 13] [--out reports/report.html]
"""
import argparse
import json
import os
import sys
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lib

SERIES_LIGHT = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#4a3aa7"]
SERIES_DARK = ["#3987e5", "#d95926", "#199e70", "#c98500", "#d55181", "#008300", "#9085e9"]


def build_payload(store, schema, months, today):
    channels = schema["channels"]
    cur_month = today.strftime("%Y-%m")

    spend = [lib.total(store, m, "spend_actual", channels) for m in months]
    fc = []
    for m in months:
        s = lib.total(store, m, "spend_forecast", channels)
        fc.append(s if s not in (None, 0) else None)

    # channels that actually spent anything in the window
    active = [c for c in channels
              if any(lib.get(store, m, c, "spend_actual") for m in months)]

    products = []
    for i, p in enumerate(schema["products"]):
        key = p["key"]
        pch = schema["product_channels"][key]
        conv = [lib.total(store, m, key, pch) for m in months]
        # doc convention: CPA divides all-channel spend by this product's convs
        cpa = [lib.cpa(spend[j], conv[j]) for j in range(len(months))]
        by_ch = {}
        for c in pch:
            if c not in active:
                continue
            cv = [lib.get(store, m, c, key) for m in months]
            by_ch[c] = {
                "conv": cv,
                "cpa": [lib.cpa(lib.get(store, months[j], c, "spend_actual"), cv[j])
                        for j in range(len(months))],
            }
        products.append({
            "key": key, "label": p["label"],
            "light": SERIES_LIGHT[i % len(SERIES_LIGHT)],
            "dark": SERIES_DARK[i % len(SERIES_DARK)],
            "conv": conv, "cpa": cpa, "byChannel": by_ch,
        })

    # aggregate conversion events across every product
    grand = []
    for j in range(len(months)):
        vals = [p["conv"][j] for p in products if p["conv"][j] is not None]
        grand.append(sum(vals) if vals else None)

    sources = {}
    for m in months:
        s = sorted({rec["source"] for (mm, _, _), rec in store.items() if mm == m})
        sources[m] = s

    return {
        "client": schema["client"],
        "currency": schema["currency"],
        "generated": today.isoformat(),
        "months": months,
        "labels": [lib.month_label(m) for m in months],
        "labelsShort": [lib.month_label(m, True) for m in months],
        "partial": [m for m in months if m == cur_month],
        "channels": active,
        "spend": spend,
        "forecast": fc,
        "spendByChannel": {c: [lib.get(store, m, c, "spend_actual") for m in months]
                           for c in active},
        "products": products,
        "grandConv": grand,
        "grandCpa": [lib.cpa(spend[j], grand[j]) for j in range(len(months))],
        "sources": sources,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--months", type=int, default=13)
    ap.add_argument("--out", default=os.path.join(lib.ROOT, "reports", "report.html"))
    ap.add_argument("--today", default=None, help="override 'today' (YYYY-MM-DD)")
    a = ap.parse_args()

    schema = lib.load_schema()
    store = lib.read_store()
    today = date.fromisoformat(a.today) if a.today else date.today()

    all_months = sorted({k[0] for k in store})
    months = all_months[-a.months:] if a.months else all_months
    payload = build_payload(store, schema, months, today)

    tpl_path = os.path.join(lib.ROOT, "scripts", "report_template.html")
    with open(tpl_path) as fh:
        html = fh.read()
    html = html.replace("/*__DATA__*/null", json.dumps(payload, separators=(",", ":")))
    with open(os.path.join(lib.ROOT, "scripts", "_logo_b64.txt")) as fh:
        html = html.replace("__LOGO__", fh.read().strip())
    html = html.replace("__CLIENT__", schema["client"])
    html = html.replace("__GENERATED__", today.strftime("%-d %B %Y"))

    os.makedirs(os.path.dirname(a.out), exist_ok=True)
    with open(a.out, "w") as fh:
        fh.write(html)
    kb = os.path.getsize(a.out) / 1024
    print(f"wrote {a.out}  ({kb:.0f} KB, {len(months)} months: {months[0]}..{months[-1]})")
    if payload["partial"]:
        print(f"flagged as partial: {', '.join(payload['partial'])}")


if __name__ == "__main__":
    main()
