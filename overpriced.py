#!/usr/bin/env python3
"""
Ищет телефоны, за которые CeX платит кэшем неоправданно много по сравнению с той же моделью:
  - «цвет»:   та же модель, память, грейд и сеть, но другой цвет выкупают заметно дешевле
  - «память»: версию с большей памятью (тот же грейд и сеть) выкупают дешевле, чем эту
Такой товар выгодно купить где угодно (в любом цвете, который CeX ценит дорого) и сдать за кэш.

    python3 overpriced.py cex-ie-ДАТА.json [--min-premium 50] [--min-pct 25]
Выход: overpriced-ie.csv
"""
import argparse, csv, json, re, sys
from collections import defaultdict

# память: "(8GB+256GB)", "128GB", "1TB"
STORAGE = re.compile(r"\((\d+\s?GB)\s?\+\s?(\d+\s?(?:GB|TB))\)|\b(\d+\s?(?:GB|TB))\b", re.I)


def gb(s):
    n = int(re.match(r"\d+", s).group())
    return n * 1024 if "TB" in s.upper() else n


def parse(name):
    """'Huawei P60 Pro (8GB+256GB) Rococo Pearl, Unlocked B' -> base, storage_gb, ram, colour, network, grade"""
    if "," not in name:
        return None
    left, right = name.rsplit(",", 1)
    rp = right.strip().split()
    if not rp or rp[-1] not in ("A", "B", "C"):
        return None
    grade, network = rp[-1], " ".join(rp[:-1]) or "?"
    ms = list(STORAGE.finditer(left))
    if not ms:
        return None
    m = ms[-1]
    ram, storage = (m.group(1), m.group(2)) if m.group(2) else ("", m.group(3))
    base = left[:m.start()].strip()
    colour = left[m.end():].strip(" ,") or "?"
    return base, gb(storage), ram.replace(" ", "").upper(), colour, network, grade


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("file")
    ap.add_argument("--min-premium", type=float, default=50, help="переплата CeX в € не меньше")
    ap.add_argument("--min-pct", type=float, default=25, help="и не меньше, чем в %%")
    ap.add_argument("-o", default="overpriced-ie.csv")
    a = ap.parse_args()

    items = [i for i in json.load(open(a.file))["items"] if i.get("superCat") == "Phones" and (i.get("cash") or 0) > 0]
    rows, parsed = [], []
    for i in items:
        p = parse(i["name"] or "")
        if p and "non" not in i["name"].lower():   # нерабочие — отдельная история
            parsed.append((i, p))

    same_model = defaultdict(list)   # (base, storage, ram, network, grade) -> items разных цветов
    by_base = defaultdict(list)      # (base, network, grade) -> items всех объёмов
    for i, (base, st, ram, col, net, gr) in parsed:
        same_model[(base, st, ram, net, gr)].append((i, col))
        by_base[(base, net, gr)].append((i, st, ram, col))

    for i, (base, st, ram, col, net, gr) in parsed:
        cash = i["cash"]
        # 1) тот же объём, другой цвет
        alts = [(j, c) for j, c in same_model[(base, st, ram, net, gr)] if j["boxId"] != i["boxId"]]
        if alts:
            j, c = min(alts, key=lambda x: x[0]["cash"])
            prem = cash - j["cash"]
            if prem >= a.min_premium and prem / j["cash"] * 100 >= a.min_pct:
                rows.append(row("цвет", i, prem, j, f"другой цвет: {c}"))
        # 2) больший объём выкупают дешевле
        bigger = [(j, s2, c) for j, s2, r2, c in by_base[(base, net, gr)] if s2 > st]
        if bigger:
            j, s2, c = min(bigger, key=lambda x: x[0]["cash"])
            prem = cash - j["cash"]
            if prem >= a.min_premium and prem / j["cash"] * 100 >= a.min_pct:
                rows.append(row("память", i, prem, j, f"больше памяти ({s2}GB), {c}"))

    # один товар — одна строка (с наибольшей переплатой)
    best = {}
    for r in rows:
        if r["boxId"] not in best or r["overpay_eur"] > best[r["boxId"]]["overpay_eur"]:
            best[r["boxId"]] = r
    out = sorted(best.values(), key=lambda r: -r["overpay_eur"])
    with open(a.o, "w", newline="", encoding="utf-8-sig") as f:
        if out:
            w = csv.DictWriter(f, fieldnames=list(out[0]))
            w.writeheader()
            w.writerows(out)
    print(f"{a.o}: {len(out)} строк (из {len(parsed)} разобранных телефонов)", file=sys.stderr)


def row(kind, i, prem, j, why):
    return {
        "overpay_eur": round(prem), "overpay_pct": round(prem / j["cash"] * 100), "type": kind,
        "name": i["name"], "boxId": i["boxId"], "cash_ie": i["cash"], "voucher_ie": i.get("voucher"), "sell_ie": i["sell"],
        "stock_ie": i.get("stock"), "cheaper_variant": j["name"], "cheaper_cash": j["cash"], "cheaper_sell": j["sell"],
        "cheaper_boxId": j["boxId"], "why": why,
    }


if __name__ == "__main__":
    main()
