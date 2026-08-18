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


def load_campaign_cfg():
    import yaml
    with open(os.path.join(lib.ROOT, "config", "campaign_map.yml")) as fh:
        return yaml.safe_load(fh)


def build_payload(store, schema, months, today):
    channels = schema["channels"]
    cur_month = today.strftime("%Y-%m")
    ccfg = load_campaign_cfg()
    cross_cutting = set(ccfg.get("cross_cutting") or [])
    # channels that carry campaign-level attribution at all
    attr_channels = [c for c in channels
                     if any(k[1] == c and k[2].startswith(lib.SPEND_P) for k in store)]

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
            asp = [lib.get(store, m, c, lib.SPEND_P + key) for m in months]
            by_ch[c] = {
                "conv": cv,
                # legacy basis, kept only so the older figures stay traceable
                "cpaLegacy": [lib.cpa(lib.get(store, months[j], c, "spend_actual"), cv[j])
                              for j in range(len(months))],
                "attrSpend": asp,
                "attrCpa": [lib.cpa(asp[j], cv[j]) for j in range(len(months))],
            }
        # --- attributed basis -------------------------------------------
        # Spend really is attributable at campaign level, so CPA is computed
        # over ONLY the channels that have attribution -- both numerator and
        # denominator restricted to the same channel set, which keeps it
        # apples-to-apples. Channels with no campaign data are excluded from
        # both rather than quietly inflating the denominator.
        attr_spend, attr_conv, attr_cpa, attr_used = [], [], [], []
        for j, m in enumerate(months):
            sp, cv, used = 0.0, 0.0, []
            for c in attr_channels:
                if c not in pch:
                    continue
                s_pc = lib.get(store, m, c, lib.SPEND_P + key)
                if s_pc is None:
                    continue
                cv_pc = lib.get(store, m, c, key)
                sp += s_pc
                cv += cv_pc or 0.0
                used.append(c)
            has = bool(used) and key not in cross_cutting
            attr_spend.append(round(sp, 2) if has else None)
            attr_conv.append(cv if has else None)
            attr_cpa.append(lib.cpa(sp, cv) if has and cv else None)
            attr_used.append(used if has else [])

        products.append({
            "key": key, "label": p["label"],
            "light": SERIES_LIGHT[i % len(SERIES_LIGHT)],
            "dark": SERIES_DARK[i % len(SERIES_DARK)],
            "conv": conv, "cpa": cpa, "byChannel": by_ch,
            "attrSpend": attr_spend, "attrConv": attr_conv, "attrCpa": attr_cpa,
            "attrUsed": attr_used,
            "crossCutting": key in cross_cutting,
            "sharesPoolWith": next((sorted(set(v) - {key})
                                    for v in (ccfg.get("shared_spend") or {}).values()
                                    if key in v), []),
        })

    # aggregate conversion events across every product
    grand = []
    for j in range(len(months)):
        vals = [p["conv"][j] for p in products if p["conv"][j] is not None]
        grand.append(sum(vals) if vals else None)

    # share of each month's spend that campaign attribution covers
    coverage = []
    for j, m in enumerate(months):
        tot = spend[j]
        cov = sum(v for v in (lib.get(store, m, c, "spend_actual") for c in attr_channels)
                  if v is not None)
        coverage.append(round(cov / tot, 4) if tot else None)

    # spend going to products the doc does not track at all
    untracked = {}
    tracked = {p["key"] for p in schema["products"]} | {"brand", "other"}
    for k in store:
        if not k[2].startswith(lib.SPEND_P):
            continue
        pk = k[2][len(lib.SPEND_P):]
        if pk in tracked:
            continue
        untracked.setdefault(pk, [0.0] * len(months))
        if k[0] in months:
            untracked[pk][months.index(k[0])] += store[k]["value"]
    brand_spend = [lib.total(store, m, lib.SPEND_P + "brand", attr_channels) for m in months]

    # --- spend allocation, derived here so the page never recomputes it -----
    # Every dollar lands in exactly one bucket. insure_payment is skipped
    # because it shares the insure pool with insure_quote -- counting both
    # would double it. The result is asserted against the month total.
    plabel = {p["key"]: p["label"] for p in schema["products"]}
    alloc = []
    for j, m in enumerate(months):
        buckets, tot = {}, spend[j]
        for c in attr_channels:
            for k in list(store):
                if k[0] != m or k[1] != c or not k[2].startswith(lib.SPEND_P):
                    continue
                pk = k[2][len(lib.SPEND_P):]
                if pk == "insure_payment":
                    continue
                buckets[pk] = buckets.get(pk, 0.0) + store[k]["value"]
        covered = sum(buckets.values())
        rows_a = []
        prod_sum = sum(v for k, v in buckets.items()
                       if k in plabel or k == "insure_quote")
        if prod_sum:
            rows_a.append({"label": "To tracked products", "value": round(prod_sum, 2),
                           "note": "attributed from the campaigns that targeted them"})
        if buckets.get("brand"):
            rows_a.append({"label": "Brand &amp; upper funnel",
                           "value": round(buckets["brand"], 2),
                           "note": "works across every product, so held separately"})
        if buckets.get("other"):
            rows_a.append({"label": "Other &amp; tests", "value": round(buckets["other"], 2),
                           "note": "campaigns targeting things this report doesn't track"})
        for pk, v in sorted(buckets.items()):
            if pk in plabel or pk in ("brand", "other", "insure_quote") or not v:
                continue
            rows_a.append({"label": pk.capitalize() + " (not in this report)",
                           "value": round(v, 2),
                           "note": "live campaigns for a product the doc doesn't track yet"})
        uncov = (tot or 0) - covered
        if uncov > 1:
            missing = [c for c in channels if c not in attr_channels
                       and lib.get(store, m, c, "spend_actual")]
            rows_a.append({"label": "Channels without campaign data",
                           "value": round(uncov, 2),
                           "note": ", ".join(missing) +
                                   " - no API, so spend can't be split by product yet"})
        if tot:
            got = sum(r["value"] for r in rows_a)
            if abs(got - tot) > 0.5:
                raise SystemExit(f"allocation for {m} sums to {got:,.2f}, "
                                 f"month total is {tot:,.2f}")
        alloc.append(rows_a)

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
        "attrChannels": attr_channels,
        "coverage": coverage,
        "brandSpend": brand_spend,
        "untracked": untracked,
        "alloc": alloc,
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
