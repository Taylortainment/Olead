"""Attribute channel spend to products using campaign names.

Why not apportion by conversion share: splitting spend S across products in
proportion to their conversion counts n_p gives S*(n_p/N) for product p, so
CPA_p = S*(n_p/N)/n_p = S/N -- the SAME number for every product. It looks like
a fix and carries no information. Campaign-level attribution is the real basis.

The product *split* comes from campaign data; it is then applied to the channel
total already in the store, so the attributed figures always reconcile to the
spend the client has already been shown.

Usage:
  python3 scripts/attribute.py            # dry run: coverage + reconciliation
  python3 scripts/attribute.py --apply
"""
import argparse
import json
import os
import re
import sys
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lib

MAP = os.path.join(lib.ROOT, "config", "campaign_map.yml")
BUCKETS = ("brand", "other")


def load_map():
    import yaml
    with open(MAP) as fh:
        cfg = yaml.safe_load(fh)
    rules = [(re.compile(r["pattern"], re.I), r["product"]) for r in cfg["rules"]]
    return rules, cfg


def classify(name, rules):
    for rx, product in rules:
        if rx.search(name):
            return product
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()

    rules, cfg = load_map()
    schema = lib.load_schema()
    store = lib.read_store()

    # campaign spend -> (month, channel, product)
    raw = defaultdict(float)
    unmatched = defaultdict(float)

    with open(os.path.join(lib.ROOT, "data", "raw", "google-campaigns-13mo.json")) as fh:
        for r in json.load(fh):
            ch = "YouTube" if r["channel_type"] in ("VIDEO", "DEMAND_GEN") else "Google"
            p = classify(r["name"], rules)
            if p is None:
                unmatched[r["name"]] += r["cost"]
                continue
            raw[(r["month"], ch, p)] += r["cost"]

    with open(os.path.join(lib.ROOT, "data", "raw", "meta-campaigns-13mo.json")) as fh:
        for r in json.load(fh):
            p = classify(r["name"], rules)
            if p is None:
                unmatched[r["name"]] += r["spend"]
                continue
            raw[(r["month"], "Meta", p)] += r["spend"]

    if unmatched:
        print("UNCLASSIFIED campaigns — fix config/campaign_map.yml before applying:")
        for n, v in sorted(unmatched.items(), key=lambda kv: -kv[1]):
            print(f"   {lib.fmt_money(v):>12}  {n}")
        return 1
    print("coverage: every campaign with spend is classified\n")

    # expand shared pools (insure -> insure_quote + insure_payment)
    shared = cfg.get("shared_spend", {})

    months = sorted({k[0] for k in raw})
    channels = sorted({k[1] for k in raw})
    rows, warnings, gaps = [], [], []

    print(f"{'month':8} {'channel':8} {'campaign $':>12} {'stored $':>12} {'scale':>7}  split")
    for mo in months:
        for ch in channels:
            per = {p: v for (m, c, p), v in raw.items() if m == mo and c == ch}
            if not per:
                continue
            camp_total = sum(per.values())
            stored = lib.get(store, mo, ch, "spend_actual")
            if stored is None:
                warnings.append(f"{mo} {ch}: no stored channel spend — skipped")
                continue
            # Scale the campaign split onto the stored channel total so the
            # attributed figures sum exactly to what the client has been shown.
            scale = stored / camp_total if camp_total else 0.0
            share = {p: v / camp_total for p, v in per.items()} if camp_total else {}
            bits = " ".join(f"{p}:{share[p]*100:.0f}%" for p in sorted(share, key=lambda x: -share[x]))
            flag = ""
            if camp_total > 50 and (stored == 0 or abs(1 - scale) > 0.05):
                flag = "  <-- CHECK"
                gaps.append((mo, ch, camp_total, stored))
            print(f"{mo:8} {ch:8} {camp_total:12,.0f} {stored:12,.0f} {scale:7.3f}  {bits}{flag}")

            for p, v in per.items():
                targets = shared.get(p, [p])
                for t in targets:
                    rows.append({"month": mo, "channel": ch,
                                 "metric": f"spend_p_{t}", "value": round(v * scale, 2)})

    for w in warnings:
        print("  ! " + w)

    if gaps:
        print("\nchannel totals that disagree with the sum of their campaigns.\n"
              "The split is still applied to the STORED total so the client-facing\n"
              "figures do not move; these are logged as data-quality findings:")
        for mo, ch, camp, stored in gaps:
            print(f"   {mo} {ch:8} campaigns {camp:>10,.2f}  doc {stored:>10,.2f}"
                  f"  gap {camp-stored:>+10,.2f}")

    # reconciliation: product spend + buckets must equal channel spend
    print("\nreconciliation (attributed sum vs stored channel spend):")
    agg = defaultdict(float)
    for r in rows:
        # shared pools are counted once for the reconciliation total
        p = r["metric"][len("spend_p_"):]
        if p == "insure_payment":
            continue
        agg[(r["month"], r["channel"])] += r["value"]
    bad = 0
    for (mo, ch), v in sorted(agg.items()):
        stored = lib.get(store, mo, ch, "spend_actual")
        if stored is None:
            continue
        if abs(v - stored) > 0.05:
            print(f"  MISMATCH {mo} {ch}: attributed {v:,.2f} vs stored {stored:,.2f}")
            bad += 1
    print(f"  {len(agg)-bad}/{len(agg)} channel-months reconcile exactly")

    out = os.path.join(lib.ROOT, "data", "pulls", "attribution.json")
    if a.apply:
        by_month = defaultdict(list)
        for r in rows:
            by_month[r["month"]].append({"channel": r["channel"], "metric": r["metric"],
                                         "value": r["value"]})
        for mo, rs in by_month.items():
            p = os.path.join(lib.ROOT, "data", "pulls", f"{mo}-attribution.json")
            with open(p, "w") as fh:
                json.dump({"month": mo, "connector": "attribution", "rows": rs}, fh, indent=1)
        print(f"\nwrote {len(by_month)} pull files ({len(rows)} rows)")
    else:
        print(f"\ndry run — {len(rows)} rows ready; re-run with --apply to write pull files")
    return 0


if __name__ == "__main__":
    sys.exit(main())
