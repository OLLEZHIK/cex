/*
 * CeX scanner через поиск сайта (Algolia) — для случая, когда /v3/boxes отдаёт 403.
 * 1) Открой REGION.webuy.com/search?stext=iphone (ie / es / pt / uk) и дождись товаров.
 * 2) F12 → Console, вставь этот скрипт, Enter. Через 5–30 мин скачается cex-REGION-ДАТА.json.
 * Ключ и индекс берутся из запросов, которые страница уже сделала сама. Пауза 0.6 с между запросами.
 * Поиск отдаёт максимум 1000 товаров на запрос, поэтому категории дробятся по диапазонам цены.
 */
(async () => {
  const MIN_SELL = 15;               // дешевле — не интересно (прибыль от €20 невозможна)
  const region = (location.hostname.match(/^(\w+)\.webuy\.com$/) || [])[1];
  const src = performance.getEntriesByType('resource').map(e => e.name).find(u => /search\.webuy\.io\/1\/indexes\//.test(u));
  if (!region || !src) { alert('Сначала открой поиск на сайте (например /search?stext=iphone), дождись товаров и запусти снова'); return; }
  const u = new URL(src), key = u.searchParams.get('x-algolia-api-key'), app = u.searchParams.get('x-algolia-application-id');
  const index = (src.match(/indexes\/(prod_[\w-]+)\//) || [])[1] || `prod_cex_${region}`;
  const URL_Q = `https://search.webuy.io/1/indexes/${index}/query?x-algolia-api-key=${key}&x-algolia-application-id=${app}`;
  const DELAY_MS = 600, sleep = ms => new Promise(r => setTimeout(r, ms));
  let nreq = 0;
  const q = async body => {
    for (let i = 0; i < 4; i++) {
      const r = await fetch(URL_Q, { method: 'POST', body: JSON.stringify(body) });
      nreq++;
      if (r.ok) { await sleep(DELAY_MS); return r.json(); }
      if (r.status === 403) throw new Error('403 от поиска — останавливаемся');
      await sleep(3000 * (i + 1));
    }
    throw new Error('Поиск не ответил');
  };

  const probe = await q({ query: '', hitsPerPage: 1, facets: ['*'], maxValuesPerFacet: 1000 });
  const facets = probe.facets || {}, fk = Object.keys(facets);
  const superKey = fk.find(k => /supercat/i.test(k) && /name/i.test(k)) || fk.find(k => /supercat/i.test(k));
  const catKey = fk.find(k => /categor/i.test(k) && !/supercat/i.test(k) && /friendly/i.test(k))
              || fk.find(k => /categor/i.test(k) && !/supercat/i.test(k) && /name/i.test(k));
  if (!catKey) { console.error('Не нашёл фасет категории. Фасеты:', fk.join(', ')); return; }
  const superVals = superKey ? Object.keys(facets[superKey]).filter(v => /gaming|phones/i.test(v)) : [];
  const superFilter = superVals.length ? [superVals.map(v => `${superKey}:${v}`)] : [];
  console.log(`[${region}] индекс ${index}; фильтр: ${superVals.join(', ') || 'нет'}; категория: ${catKey}`);

  const catResp = await q({ query: '', hitsPerPage: 0, facets: [catKey], maxValuesPerFacet: 1000, facetFilters: superFilter });
  const cats = Object.keys((catResp.facets || {})[catKey] || {});
  console.log(`[${region}] категорий: ${cats.length}`);

  const pick = (h, ...ks) => { for (const k of ks) if (h[k] !== undefined && h[k] !== null) return h[k]; return null; };
  const out = new Map();
  let lost = 0;
  const add = hits => { for (const h of hits) {
    const stock = pick(h, 'ecomQuantityOnHand', 'ecomQuantity');
    const item = {
      boxId: pick(h, 'boxId', 'objectID'), name: pick(h, 'boxName'),
      category: pick(h, 'categoryFriendlyName', 'categoryName'), superCat: pick(h, 'superCatFriendlyName', 'superCatName'),
      sell: pick(h, 'sellPrice'), cash: pick(h, 'cashPriceCalculated', 'cashBuyPrice'),
      voucher: pick(h, 'exchangePriceCalculated', 'exchangePrice'),
      stock, outOfStock: !!pick(h, 'outOfStock'),
      cashBuyPrice: pick(h, 'cashBuyPrice'), cashPriceCalculated: pick(h, 'cashPriceCalculated'),
      exchangePrice: pick(h, 'exchangePrice'), inStockOnline: pick(h, 'inStockOnline'),
      boxBuyAllowed: pick(h, 'boxBuyAllowed'),
    };
    if (item.boxId) out.set(item.boxId, item);
  } };
  // рекурсивно дробим диапазон цены, пока в нём ≤ 1000 товаров
  const collect = async (cat, lo, hi) => {
    const d = await q({ query: '', hitsPerPage: 1000, facetFilters: [...superFilter, `${catKey}:${cat}`],
                        numericFilters: [`sellPrice>=${lo}`, `sellPrice<${hi}`] });
    if (d.nbHits <= 1000) return add(d.hits);
    if (hi - lo <= 1) { lost += d.nbHits - 1000; console.warn(`  ${cat} €${lo}: ${d.nbHits} товаров по одной цене, взяли 1000`); return add(d.hits); }
    const mid = Math.round(hi > 4000 && lo < 2000 ? 2000 : (lo + hi) / 2);
    await collect(cat, lo, mid); await collect(cat, mid, hi);
  };
  for (const [ci, cat] of cats.entries()) {
    await collect(cat, MIN_SELL, 100000);
    console.log(`[${region}] ${ci + 1}/${cats.length} ${cat}: всего ${out.size} (запросов ${nreq})`);
  }
  const items = [...out.values()];
  const blob = new Blob([JSON.stringify({ region, scannedAt: new Date().toISOString(), source: 'search', minSell: MIN_SELL, items })], { type: 'application/json' });
  const a = Object.assign(document.createElement('a'), { href: URL.createObjectURL(blob), download: `cex-${region}-${new Date().toISOString().slice(0, 10)}.json` });
  document.body.appendChild(a); a.click(); a.remove();
  console.log(`[${region}] готово: ${items.length} товаров${lost ? `, не влезло ${lost}` : ''}, файл скачан`);
})();
