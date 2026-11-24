#!/usr/bin/env python3
"""
Из JSON (cex_scan.py или cex-scan.js) делает два CSV:
  arbitrage-cex.csv  — купить в CeX ES/PT/UK, сдать за кэш в CeX IE (прибыль >= --min-profit, только в наличии)
  anomalies-ie.csv   — товары IE, где кэш / цена продажи >= --ratio

    python3 make_csv.py cex-ie-*.json cex-es-*.json cex-pt-*.json cex-uk-*.json
Курс GBP→EUR берётся с ECB (eurofxref-daily), иначе --gbp.
"""
import argparse, csv, json, re, sys, urllib.request

UK_NOTE = "не ЕС, таможня: НДС 23% при ввозе для перепродажи"


def ecb_gbp_eur():
    xml = urllib.request.urlopen("https://www.ecb.europa.eu/stats/eurofxref/eurofxref-daily.xml", timeout=15).read().decode()
    day = re.search(r"time='([\d-]+)'", xml).group(1)
    return 1 / float(re.search(r"currency='GBP' rate='([\d.]+)'", xml).group(1)), day


def flags(src, ie, profit, cost):
    f = []
    if ie["name"] != src["name"]:
        f.append("разные названия")
    if cost and profit / cost > 1.0:
        f.append("прибыль > 100% цены")
    if ie["sell"] and ie["cash"] >= ie["sell"] * 0.9:
        f.append("кэш IE почти = продажа IE")
    return "; ".join(f)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("files", nargs="+")
    ap.add_argument("--min-profit", type=float, default=20)
    ap.add_argument("--ratio", type=float, default=0.6)
    ap.add_argument("--gbp", type=float, help="курс GBP→EUR вручную")
    a = ap.parse_args()

    data = {}
    for fn in a.files:
        j = json.load(open(fn))
        data[j["region"]] = {i["boxId"]: i for i in j["items"]}
    if "ie" not in data:
        sys.exit("Нужен файл cex-ie-*.json")
    ie = data["ie"]

    rate, day = (a.gbp, "вручную") if a.gbp else ecb_gbp_eur()
    print(f"GBP→EUR = {rate:.4f} ({day})", file=sys.stderr)

    rows = []
    for region, items in data.items():
        if region == "ie":
            continue
        for bid, s in items.items():
            t = ie.get(bid)
            if not t or not t.get("cash") or not s.get("sell") or s.get("outOfStock"):
                continue
            cost = s["sell"] * rate if region == "uk" else s["sell"]
            profit = t["cash"] - cost
            if profit < a.min_profit:
                continue
            rows.append({
                "profit_eur": round(profit, 2), "source": region.upper(), "boxId": bid, "name": t["name"],
                "category": t["category"], "buy_price_src": s["sell"], "buy_currency": "GBP" if region == "uk" else "EUR",
                "buy_price_eur": round(cost, 2), "cash_ie_eur": t["cash"], "voucher_ie_eur": t.get("voucher"),
                "sell_ie_eur": t.get("sell"), "src_stock": s.get("stock"),
                "note": UK_NOTE if region == "uk" else "", "suspicious": flags(s, t, profit, cost),
            })
    rows.sort(key=lambda r: -r["profit_eur"])
    write("arbitrage-cex.csv", rows)

    an = []
    for bid, t in ie.items():
        if t.get("sell") and t.get("cash") and t["cash"] / t["sell"] >= a.ratio:
            an.append({"ratio": round(t["cash"] / t["sell"], 3), "boxId": bid, "name": t["name"], "category": t["category"],
                       "sell_ie_eur": t["sell"], "cash_ie_eur": t["cash"], "voucher_ie_eur": t.get("voucher"),
                       "outOfStock": t.get("outOfStock"), "stock": t.get("stock")})
    an.sort(key=lambda r: (-r["ratio"], -r["cash_ie_eur"]))
    write("anomalies-ie.csv", an)


def write(fn, rows):
    with open(fn, "w", newline="", encoding="utf-8-sig") as f:
        if rows:
            w = csv.DictWriter(f, fieldnames=list(rows[0]))
            w.writeheader()
            w.writerows(rows)
    print(f"{fn}: {len(rows)} строк", file=sys.stderr)


if __name__ == "__main__":
    main()
