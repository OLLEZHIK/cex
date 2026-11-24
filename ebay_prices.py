#!/usr/bin/env python3
"""
Ищет на eBay (страны ЕС) цены на товары, которые CeX Ирландия выкупает за кэш.

Вход:  JSON из cex-scan.js, снятый на ie.webuy.com
Выход: cex-ebay-ДАТА.json (загружается в compare.html как источник "EBAY") + CSV

Нужны бесплатные ключи eBay Developer (Production keyset):
    export EBAY_APP_ID=...   # Client ID
    export EBAY_CERT_ID=...  # Client Secret
    python3 ebay_prices.py cex-ie-2026-11-24.json --min-cash 60 --markets DE,FR,IT,ES,NL

Только стандартная библиотека Python 3.8+.
"""
import argparse, base64, csv, datetime, json, os, re, statistics, sys, time, urllib.parse, urllib.request, urllib.error

API = os.environ.get("EBAY_API_BASE", "https://api.ebay.com")
MARKET_CURRENCY_COUNTRY = {  # маркетплейс -> страна продавца (чтобы товар был из ЕС, без таможни)
    "DE": "DE", "FR": "FR", "IT": "IT", "ES": "ES", "NL": "NL", "AT": "AT", "BE": "BE", "IE": "IE",
}
# Б/у, восстановленные, новые; без "for parts / не работает" (7000)
CONDITIONS = "1000|1500|2000|2010|2020|2030|2500|3000"
NEGATIVE = ["defekt", "defect", "broken", "kaputt", "ersatzteil", "hülle", "case", "cover", "panne",
            "pièces", "guasto", "ricambi", "averiado", "piezas", "leergut", "karton", "box only", "only box", "attrappe", "dummy"]
COLORS = set("""black white blue red green purple pink gold silver grey gray graphite midnight starlight yellow
orange coral sierra pacific alpine phantom space rose titanium natural desert cream lavender violet mint bronze
aura mystic cloud prism awesome navy teal lime jet matte glossy product (product)red light dark deep ice
lilac burgundy charcoal onyx obsidian porcelain hazel sage bay lemongrass snow arctic glacier ocean""".split())
JUNK = {"unlocked", "unboxed", "boxed", "discounted", "console", "&", "-", "/", "with", "no", "controller"}
GRADE = re.compile(r"\s+[ABC]$")
STORAGE = re.compile(r"\b(\d+)\s?(GB|TB)\b", re.I)


def make_query(name):
    """'Apple iPhone 13 128GB Midnight, Unlocked A' -> 'Apple iPhone 13 128GB'"""
    name = GRADE.sub("", name.strip())
    parts = [p.strip() for p in name.split(",")]
    words = [w for w in parts[0].split() if w.lower() not in COLORS and w.lower() not in JUNK]
    q = " ".join(words)
    if not STORAGE.search(q):
        for p in parts[1:]:
            m = STORAGE.search(p)
            if m:
                q += f" {m.group(1)}{m.group(2).upper()}"
                break
    return q.strip()


VARIANTS = {"pro", "max", "mini", "plus", "ultra", "lite", "slim", "fe", "oled", "digital", "edge", "note", "+", "xl", "s", "x"}
BRANDS = {"apple", "samsung", "sony", "microsoft", "nintendo", "google", "xiaomi", "huawei", "oneplus"}


def tokens(text):
    t = text.lower()
    t = re.sub(r"(\d+)\s+(gb|tb)\b", r"\1\2", t)          # "128 GB" -> "128gb"
    t = re.sub(r"\bps\s?(\d)\b", r"playstation \1", t)    # "PS4" -> "playstation 4"
    t = re.sub(r"\biphone(\d+)", r"iphone \1", t)           # "iPhone13" -> "iphone 13"
    return set(re.findall(r"[a-z0-9]+|\+", t))


def title_ok(title, query):
    """Все значимые слова запроса есть в заголовке, и нет «чужих» модификаций (Pro/Mini/Lite…)."""
    tl = title.lower()
    if any(n in tl for n in NEGATIVE):
        return False
    tt, qt = tokens(title), tokens(query) - BRANDS
    if not qt <= tt:
        return False
    return not ((tt & VARIANTS) - qt)


class Ebay:
    def __init__(self, app_id, cert_id, ship_to):
        self.auth = base64.b64encode(f"{app_id}:{cert_id}".encode()).decode()
        self.ship_to = ship_to
        self.token, self.exp = None, 0
        self.calls = 0

    def _token(self):
        if self.token and time.time() < self.exp - 60:
            return self.token
        req = urllib.request.Request(
            f"{API}/identity/v1/oauth2/token",
            data=urllib.parse.urlencode({"grant_type": "client_credentials",
                                         "scope": "https://api.ebay.com/oauth/api_scope"}).encode(),
            headers={"Authorization": f"Basic {self.auth}", "Content-Type": "application/x-www-form-urlencoded"})
        d = json.load(urllib.request.urlopen(req, timeout=30))
        self.token, self.exp = d["access_token"], time.time() + d["expires_in"]
        return self.token

    def search(self, query, market, min_price):
        country = MARKET_CURRENCY_COUNTRY[market]
        filt = ",".join([
            "buyingOptions:{FIXED_PRICE}",
            f"conditionIds:{{{CONDITIONS}}}",
            f"itemLocationCountry:{country}",
            f"deliveryCountry:{self.ship_to}",
            f"price:[{min_price:.0f}..],priceCurrency:EUR",
        ])
        params = urllib.parse.urlencode({"q": query, "filter": filt, "sort": "price", "limit": 50})
        for attempt in range(4):
            req = urllib.request.Request(f"{API}/buy/browse/v1/item_summary/search?{params}", headers={
                "Authorization": f"Bearer {self._token()}",
                "X-EBAY-C-MARKETPLACE-ID": f"EBAY_{market}",
                "X-EBAY-C-ENDUSERCTX": "contextualLocation=" + urllib.parse.quote(f"country={self.ship_to}"),
            })
            try:
                self.calls += 1
                return json.load(urllib.request.urlopen(req, timeout=30)).get("itemSummaries", [])
            except urllib.error.HTTPError as e:
                if e.code in (429, 500, 502, 503):
                    time.sleep(5 * (attempt + 1)); continue
                print(f"  ! {market} '{query}': HTTP {e.code} {e.read()[:200]!r}", file=sys.stderr)
                return []
        return []


def total_price(it):
    p = float(it["price"]["value"])
    ship = 0.0
    for so in it.get("shippingOptions", []):
        c = so.get("shippingCost")
        if c and c.get("currency") == "EUR":
            ship = float(c["value"]); break
    return p + ship, p, ship


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("ie_json")
    ap.add_argument("--markets", default="DE,FR,IT,ES,NL")
    ap.add_argument("--min-cash", type=float, default=60, help="брать только товары, за которые CeX IE платит ≥ €")
    ap.add_argument("--ship-to", default="IE", help="страна доставки (куда закажешь: IE, DE, PL…)")
    ap.add_argument("--pick", type=int, default=3, help="какую по счёту цену брать как реальную (3 = третья самая дешёвая)")
    ap.add_argument("--max-queries", type=int, default=800, help="лимит уникальных запросов (у eBay ~5000 вызовов/сутки)")
    ap.add_argument("--cache", default="ebay-cache.json")
    a = ap.parse_args()

    app, cert = os.environ.get("EBAY_APP_ID"), os.environ.get("EBAY_CERT_ID")
    if not app or not cert:
        sys.exit("Задай EBAY_APP_ID и EBAY_CERT_ID (ключи с developer.ebay.com)")
    ie = json.load(open(a.ie_json, encoding="utf-8"))
    if ie.get("region") != "ie":
        sys.exit("Нужен файл, снятый на ie.webuy.com")
    markets = [m.strip().upper() for m in a.markets.split(",")]
    cache = json.load(open(a.cache)) if os.path.exists(a.cache) else {}
    ebay = Ebay(app, cert, a.ship_to.upper())

    items = [i for i in ie["items"] if (i.get("cash") or 0) >= a.min_cash]
    groups = {}  # один запрос на модель: грейды A/B/C ищутся вместе
    for i in items:
        groups.setdefault(make_query(i["name"]), []).append(i)
    queries = sorted(groups, key=lambda q: -max(x["cash"] for x in groups[q]))[: a.max_queries]
    print(f"Товаров с кэшем ≥ €{a.min_cash:.0f}: {len(items)}, уникальных запросов: {len(queries)}, рынков: {len(markets)}")

    out, rows = [], []
    for n, q in enumerate(queries, 1):
        floor = 0.35 * min(x["cash"] for x in groups[q])  # отсекаем чехлы/коробки
        offers = []
        for m in markets:
            key = f"{m}|{a.ship_to}|{q}"
            if key not in cache:
                res = ebay.search(q, m, floor)
                cache[key] = [{"title": r["title"], "url": r.get("itemWebUrl"), "price": total_price(r),
                               "cond": r.get("condition", "")} for r in res if r.get("price", {}).get("currency") == "EUR"]
                time.sleep(0.3)
            offers += [dict(o, market=m) for o in cache[key] if title_ok(o["title"], q)]
        offers.sort(key=lambda o: o["price"][0])
        if n % 20 == 0:
            json.dump(cache, open(a.cache, "w"))
            print(f"  {n}/{len(queries)} запросов, вызовов API: {ebay.calls}")
        if not offers:
            continue
        pick = offers[min(a.pick, len(offers)) - 1]
        median5 = statistics.median(o["price"][0] for o in offers[:5])
        for ci in groups[q]:
            out.append({"boxId": ci["boxId"], "name": ci["name"], "category": ci.get("category"),
                        "sell": round(pick["price"][0], 2), "cash": None, "outOfStock": False,
                        "url": pick["url"], "ebayTitle": pick["title"], "ebayMarket": pick["market"],
                        "ebayMin": round(offers[0]["price"][0], 2), "ebayMedian5": round(median5, 2),
                        "ebayCount": len(offers), "query": q})
            rows.append([ci["name"], q, ci["cash"], round(pick["price"][0], 2), round(ci["cash"] - pick["price"][0], 2),
                         round(offers[0]["price"][0], 2), round(median5, 2), len(offers), pick["market"], pick["cond"],
                         pick["title"], pick["url"]])
    json.dump(cache, open(a.cache, "w"))

    day = datetime.date.today().isoformat()
    json.dump({"region": "ebay", "scannedAt": datetime.datetime.now().isoformat(), "items": out},
              open(f"cex-ebay-{day}.json", "w", encoding="utf-8"), ensure_ascii=False)
    rows.sort(key=lambda r: -r[4])
    with open(f"cex-ebay-{day}.csv", "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(["CeX товар", "Запрос eBay", "Кэш IE €", f"eBay (#{a.pick} по цене) €", "Прибыль €",
                    "eBay мин €", "eBay медиана 5 €", "Найдено лотов", "Рынок", "Состояние", "Лот", "Ссылка"])
        w.writerows(rows)
    print(f"Готово: cex-ebay-{day}.json / .csv, вызовов API: {ebay.calls}")
    for r in rows[:15]:
        print(f"  +€{r[4]:>6.0f}  кэш €{r[2]:.0f} / eBay {r[8]} €{r[3]:.0f}  {r[0]}")


if __name__ == "__main__":
    main()
