"""One-off: read the exported doc CSV and build data/history.csv.

Only measured facts are kept -- channel spend (actual + forecast) and
conversion counts per product. Every CPA, total and variance row in the
source doc is recomputed downstream instead of being imported, so the
imported CPA rows (including the #DIV/0! cells) are read purely to
cross-check the arithmetic, never to seed the store.
"""
import csv
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lib

SRC = os.path.join(lib.ROOT, "data", "source_snapshot.csv")

# doc section title (normalised) -> metric key stored
SECTION_METRIC = {
    "channel spend $nzd - actual": "spend_actual",
    "channel spend $nzd - forecasted": "spend_forecast",
}
# CPA sections are read only for verification, never stored.
CPA_SECTIONS = {
    "kiwisaver cpa": "kiwisaver",
    "crypto cpa": "crypto",
    "spend cpa": "spend_signup",
    "subscription cpa (plan started) $nzd": "subscription",
    "insure cpa (quote) $nzd": "insure_quote",
    "save cpa $nzd": "save",
    "insure cpa (payment) $nzd": "insure_payment",
}


def norm(s):
    return " ".join(str(s or "").split()).strip().lower()


def main():
    # This rebuilds the store from the original export. Any month already
    # refreshed from a connector would be silently reverted, so refuse unless
    # the caller is explicit about it.
    if os.path.exists(lib.HISTORY) and "--force" not in sys.argv:
        existing = lib.read_store()
        refreshed = sorted({m for (m, _, _), r in existing.items() if r["source"] != "doc"})
        if refreshed:
            sys.exit(
                f"refusing to rebuild: {len(refreshed)} month(s) carry connector or "
                f"manual data that would be lost ({', '.join(refreshed)}).\n"
                f"Pass --force only if you really mean to discard it.")

    schema = lib.load_schema()
    channels = schema["channels"]
    chan_lookup = {norm(c): c for c in channels}
    months = lib.month_range(schema["start_month"], 24)

    for p in schema["products"]:
        SECTION_METRIC[norm(p["doc_section"])] = p["key"]

    with open(SRC, newline="") as fh:
        rows = list(csv.reader(fh))

    store = {}
    checks = {}          # (month, channel, metric) -> imported CPA, for verification
    budget_total = {}    # month -> {'actual':x,'forecast':y} from the summary block
    section = None
    stats = {"stored": 0, "skipped_rows": 0, "sections": []}

    for row in rows:
        row = row + [""] * (26 - len(row))
        label_col, title_col = norm(row[1]), norm(row[2])

        # A section title sits in column C with column B empty.
        if title_col and not label_col:
            section = title_col
            stats["sections"].append(row[2].strip())
            continue
        if not label_col:
            continue
        # Skip the repeated month header rows.
        if label_col in ("channel", "budget"):
            continue

        values = [lib.parse_number(row[2 + i]) for i in range(24)]

        # --- summary budget block -------------------------------------
        if section and section.startswith("total monthly media budget"):
            key = {"actual": "actual", "forcasted": "forecast",
                   "forecasted": "forecast", "difference": "difference"}.get(label_col)
            if key:
                for mo, v in zip(months, values):
                    if v is not None:
                        budget_total.setdefault(mo, {})[key] = v
            continue

        metric = SECTION_METRIC.get(section or "")
        cpa_product = CPA_SECTIONS.get(section or "")

        # 'Total' rows are derived downstream -- read only to verify.
        if label_col == "total":
            if metric:
                for mo, v in zip(months, values):
                    if v is not None:
                        checks[(mo, "__TOTAL__", metric)] = v
            continue

        channel = chan_lookup.get(label_col)
        if channel is None:
            stats["skipped_rows"] += 1
            continue

        if metric:
            for mo, v in zip(months, values):
                if v is None:
                    continue
                store[(mo, channel, metric)] = {"value": v, "source": "doc"}
                stats["stored"] += 1
        elif cpa_product:
            for mo, v in zip(months, values):
                if v is not None:
                    checks[(mo, channel, "cpa_" + cpa_product)] = v

    n = lib.write_store(store)

    # persist the summary block + imported CPAs for the verifier
    with open(os.path.join(lib.ROOT, "data", "doc_checks.csv"), "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["month", "channel", "metric", "doc_value"])
        for (mo, ch, mt), v in sorted(checks.items()):
            w.writerow([mo, ch, mt, repr(v)])
        for mo, d in sorted(budget_total.items()):
            for k, v in sorted(d.items()):
                w.writerow([mo, "__BUDGET__", k, repr(v)])

    print(f"sections found ({len(stats['sections'])}):")
    for s in stats["sections"]:
        print("   -", s)
    print(f"\nrows written to history.csv : {n}")
    print(f"cells skipped (unknown row) : {stats['skipped_rows']}")
    print(f"verification cells captured : {len(checks)}")
    print(f"months                      : {months[0]} .. {months[-1]}")


if __name__ == "__main__":
    main()
