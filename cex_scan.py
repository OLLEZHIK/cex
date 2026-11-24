#!/usr/bin/env python3
"""
Python-порт cex-scan.js: собирает цены CeX (Gaming + Phones) по региону.

    python3 cex_scan.py ie            # -> cex-ie-ДАТА.json
    python3 cex_scan.py es pt uk

Формат такой же, как у cex-scan.js: {region, scannedAt, items:[{boxId,name,category,superCat,sell,cash,voucher,stock,outOfStock}]}
Только stdlib. Пауза 0.6 с между запросами. Если CeX/Cloudflare отвечает 403, скрипт останавливается
и ничего не обходит: тогда запусти cex-scan.js в консоли браузера на REGION.webuy.com.
"""
import datetime, json, sys, time, urllib.error, urllib.request

SUPERCATS = [1, 4]  # 1 = Gaming, 4 = Phones
PAGE, DELAY = 50, 0.6


class Blocked(Exception):
    pass


def get(api, path):
    for i in range(4):
        try:
            with urllib.request.urlopen(api + path, timeout=30) as r:
                return json.load(r)["response"]["data"]
        except urllib.error.HTTPError as e:
            if e.code == 403:
                raise Blocked(f"403 (Cloudflare) на {path}")
            err = e
        except (urllib.error.URLError, ValueError) as e:
            err = e
        time.sleep(3 * (i + 1))
    raise RuntimeError(f"Запрос не удался: {path}: {err}")


def scan(region):
    api = f"https://wss2.cex.{region}.webuy.io/v3"
    ids = lambda xs: "[" + ",".join(map(str, xs)) + "]"
    lines = [p["productLineId"] for p in get(api, f"/productlines?superCatIds={ids(SUPERCATS)}")["productLines"]]
    cats, seen = [], set()
    for lid in lines:  # API принимает только одну линейку за запрос
        time.sleep(DELAY)
        for c in (get(api, f"/categories?productLineIds=[{lid}]") or {}).get("categories", []):
            if c["categoryId"] not in seen:
                seen.add(c["categoryId"])
                cats.append(c)
    print(f"[{region}] категорий: {len(cats)}", file=sys.stderr)
    out = []
    for ci, c in enumerate(cats, 1):
        first, total = 1, float("inf")
        while first <= total:
            time.sleep(DELAY)
            d = get(api, f"/boxes?categoryIds=[{c['categoryId']}]&firstRecord={first}&count={PAGE}&sortBy=relevance&sortOrder=desc")
            if not d or not d.get("boxes"):
                break
            total = d["totalRecords"]
            for b in d["boxes"]:
                out.append({
                    "boxId": b["boxId"], "name": b["boxName"],
                    "category": b.get("categoryFriendlyName") or b.get("categoryName"),
                    "superCat": b.get("superCatFriendlyName") or b.get("superCatName"),
                    "sell": b.get("sellPrice"), "cash": b.get("cashPrice"), "voucher": b.get("exchangePrice"),
                    "stock": b.get("ecomQuantityOnHand"), "outOfStock": bool(b.get("outOfStock")),
                })
            first += PAGE
        print(f"[{region}] {ci}/{len(cats)} {c['categoryFriendlyName']}: всего {len(out)}", file=sys.stderr)
    now = datetime.datetime.now(datetime.timezone.utc)
    fn = f"cex-{region}-{now:%Y-%m-%d}.json"
    with open(fn, "w") as f:
        json.dump({"region": region, "scannedAt": now.isoformat().replace("+00:00", "Z"), "items": out}, f)
    print(f"[{region}] готово: {len(out)} товаров -> {fn}", file=sys.stderr)


if __name__ == "__main__":
    for region in sys.argv[1:] or ["ie"]:
        try:
            scan(region)
        except Blocked as e:
            sys.exit(f"[{region}] {e}. Обходить не будем: открой {region}.webuy.com, F12 → Console и запусти cex-scan.js.")
