"""Prove the derived model reproduces the doc it replaces.

Recomputes every total, CPA and budget-variance figure from the stored
spend + conversion facts and diffs them against the values that were in the
exported doc. A clean run means the pipeline can regenerate the doc exactly;
any mismatch is either a doc typo or a bug here, and gets printed either way.
"""
import csv
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lib

TOL_MONEY = 0.02     # cents of float noise
TOL_CPA = 0.02
TOL_COUNT = 0.5


def main():
    schema = lib.load_schema()
    channels = schema["channels"]
    products = schema["products"]
    store = lib.read_store()

    doc = {}
    with open(os.path.join(lib.ROOT, "data", "doc_checks.csv"), newline="") as fh:
        for r in csv.DictReader(fh):
            doc[(r["month"], r["channel"], r["metric"])] = float(r["doc_value"])

    passes, fails = 0, []

    def check(key, derived, doc_val, tol, desc):
        nonlocal passes
        if doc_val is None:
            return
        if derived is None:
            fails.append((desc, "no data", doc_val))
            return
        if abs(derived - doc_val) <= tol:
            passes += 1
        else:
            fails.append((desc, derived, doc_val))

    months = lib.month_range(schema["start_month"], 24)

    # Months that have been refreshed from a connector no longer match the
    # original doc snapshot -- by design. Exclude them so this stays a real
    # regression test of the derivation, not a diff against stale numbers.
    refreshed = sorted({m for (m, _, _), r in store.items() if r["source"] != "doc"})
    if refreshed:
        print(f"excluded (refreshed since export): {', '.join(refreshed)}\n")

    for mo in months:
        if mo in refreshed:
            continue
        tot_spend = lib.total(store, mo, "spend_actual", channels)
        tot_fc = lib.total(store, mo, "spend_forecast", channels)

        # summary budget block
        check(None, tot_spend, doc.get((mo, "__BUDGET__", "actual")),
              TOL_MONEY, f"{mo} total actual spend")
        d_fc = doc.get((mo, "__BUDGET__", "forecast"))
        if d_fc is not None and tot_fc is not None:
            check(None, tot_fc, d_fc, TOL_MONEY, f"{mo} total forecast spend")
        d_diff = doc.get((mo, "__BUDGET__", "difference"))
        if d_diff is not None and tot_fc is not None and tot_spend is not None:
            check(None, tot_fc - tot_spend, d_diff, TOL_MONEY,
                  f"{mo} budget difference")

        for p in products:
            key, pchans = p["key"], schema["product_channels"][p["key"]]
            tot_conv = lib.total(store, mo, key, pchans)
            check(None, tot_conv, doc.get((mo, "__TOTAL__", key)),
                  TOL_COUNT, f"{mo} {key} total conversions")

            # per-channel CPA: that channel's whole spend / that product's convs
            for ch in pchans:
                d_cpa = doc.get((mo, ch, "cpa_" + key))
                if d_cpa is None:
                    continue
                spend = lib.get(store, mo, ch, "spend_actual")
                conv = lib.get(store, mo, ch, key)
                derived = lib.cpa(spend, conv)
                if derived is None:
                    # doc writes $0.00 where there were no conversions
                    if abs(d_cpa) <= TOL_CPA:
                        passes += 1
                    else:
                        fails.append((f"{mo} {ch} {key} CPA", "n/a", d_cpa))
                    continue
                check(None, derived, d_cpa, max(TOL_CPA, abs(d_cpa) * 0.005),
                      f"{mo} {ch} {key} CPA")

            # total CPA row = all-channel spend / product total conversions
            d_tcpa = doc.get((mo, "__TOTAL__", "cpa_" + key))
            if d_tcpa is not None and tot_conv:
                check(None, lib.cpa(tot_spend, tot_conv), d_tcpa,
                      max(TOL_CPA, abs(d_tcpa) * 0.005), f"{mo} {key} TOTAL CPA")

    print(f"checks passed : {passes}")
    print(f"checks failed : {len(fails)}")
    if fails:
        print("\nmismatches (derived vs doc):")
        for desc, dv, doc_v in fails[:40]:
            dv_s = dv if isinstance(dv, str) else f"{dv:,.2f}"
            print(f"  {desc:<44} derived={dv_s:>14}  doc={doc_v:,.2f}")
        if len(fails) > 40:
            print(f"  ... and {len(fails)-40} more")
    return 0 if not fails else 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except BrokenPipeError:
        # stdout closed early (e.g. piped into `head`) -- not a failure
        os._exit(0)
