/*
 * CeX scanner через поиск сайта (Algolia) — для случая, когда /v3/boxes отдаёт 403.
 * 1) Открой REGION.webuy.com/search?stext=iphone (ie / es / pt / uk) и дождись товаров.
 * 2) F12 → Console, вставь этот скрипт, Enter. Через 5–30 мин скачается cex-REGION-ДАТА.json.
 * Ключ и индекс берутся из запросов, которые страница уже сделала сама. Пауза 0.6 с между запросами.
 */
(async () => {
  const region = (location.hostname.match(/^(\w+)\.webuy\.com$/) || [])[1];
  const src = performance.getEntriesByType('resource').map(e => e.name).find(u => /search\.webuy\.io\/1\/indexes\//.test(u));
  if (!region || !src) { alert('Сначала открой поиск на сайте (например /search?stext=iphone), дождись товаров и запусти снова'); return; }
  const u = new URL(src), key = u.searchParams.get('x-algolia-api-key'), app = u.searchParams.get('x-algolia-application-id');
  const index = (src.match(/indexes\/(prod_[\w-]+)\//) || [])[1] || `prod_cex_${region}`;
  const URL_Q = `https://search.webuy.io/1/indexes/${index}/query?x-algolia-api-key=${key}&x-algolia-application-id=${app}`;
  const DELAY_MS = 600, sleep = ms => new Promise(r => setTimeout(r, ms));
  const q = async body => {
    for (let i = 0; i < 4; i++) {
      const r = await fetch(URL_Q, { method: 'POST', body: JSON.stringify(body) });
      if (r.ok) { await sleep(DELAY_MS); return r.json(); }
      if (r.status === 403) throw new Error('403 от поиска — останавливаемся');
      await sleep(3000 * (i + 1));
    }
    throw new Error('Поиск не ответил');
  };

  // 1. Какие есть фасеты (поля для фильтра) и как выглядит товар
  const probe = await q({ query: '', hitsPerPage: 1, facets: ['*'], maxValuesPerFacet: 1000 });
  const facets = probe.facets || {}, fk = Object.keys(facets);
  console.log(`[${region}] индекс ${index}, всего ${probe.nbHits}; фасеты:`, fk.join(', '));
  console.log(`[${region}] поля товара:`, Object.keys(probe.hits[0] || {}).join(', '));
  const superKey = fk.find(k => /supercat/i.test(k) && /name/i.test(k)) || fk.find(k => /supercat/i.test(k));
  const catKey = fk.find(k => /categor/i.test(k) && !/supercat/i.test(k) && /friendly/i.test(k))
              || fk.find(k => /categor/i.test(k) && !/supercat/i.test(k) && /name/i.test(k));
  if (!catKey) { console.error('Не нашёл фасет категории — пришли скриншот этого лога'); return; }
  const superVals = superKey ? Object.keys(facets[superKey]).filter(v => /gaming|phones/i.test(v)) : [];
  const superFilter = superVals.length ? [superVals.map(v => `${superKey}:${v}`)] : [];
  if (!superVals.length) console.warn('Не нашёл фильтр Gaming/Phones — соберу все категории');

  // 2. Категории внутри Gaming + Phones
  const catResp = await q({ query: '', hitsPerPage: 0, facets: [catKey], maxValuesPerFacet: 1000, facetFilters: superFilter });
  const cats = Object.keys((catResp.facets || {})[catKey] || {});
  console.log(`[${region}] категорий: ${cats.length}`);

  // 3. Постранично по каждой категории
  const pick = (h, ...ks) => { for (const k of ks) if (h[k] !== undefined && h[k] !== null) return h[k]; return null; };
  const out = new Map();
  for (const [ci, cat] of cats.entries()) {
    let page = 0, pages = 1;
    while (page < pages) {
      const d = await q({ query: '', hitsPerPage: 1000, page, facetFilters: [...superFilter, `${catKey}:${cat}`] });
      pages = d.nbPages || 0;
      if (page === 0 && d.nbHits > 1000 * Math.max(pages, 1)) console.warn(`  ${cat}: ${d.nbHits} товаров, часть может не попасть (лимит поиска)`);
      for (const h of d.hits) {
        const stock = pick(h, 'ecomQuantityOnHand', 'ecomQuantity', 'stockQuantity');
        const item = {
          boxId: pick(h, 'boxId', 'objectID'), name: pick(h, 'boxName', 'name'),
          category: pick(h, 'categoryFriendlyName', 'categoryName') ?? cat,
          superCat: pick(h, 'superCatFriendlyName', 'superCatName'),
          sell: pick(h, 'sellPrice'), cash: pick(h, 'cashPrice', 'cashPriceCalculated'),
          voucher: pick(h, 'exchangePrice', 'exchangePriceCalculated'),
          stock, outOfStock: !!pick(h, 'outOfStock') || stock === 0,
        };
        if (item.boxId) out.set(item.boxId, item);
      }
      page++;
    }
    console.log(`[${region}] ${ci + 1}/${cats.length} ${cat}: всего товаров ${out.size}`);
  }
  const items = [...out.values()];
  const miss = ['sell', 'cash'].filter(f => !items.some(i => i[f] != null));
  if (miss.length) console.error(`Нет полей ${miss} — пришли скриншот строки «поля товара» выше`);
  const blob = new Blob([JSON.stringify({ region, scannedAt: new Date().toISOString(), source: 'search', items })], { type: 'application/json' });
  const a = Object.assign(document.createElement('a'), { href: URL.createObjectURL(blob), download: `cex-${region}-${new Date().toISOString().slice(0, 10)}.json` });
  document.body.appendChild(a); a.click(); a.remove();
  console.log(`[${region}] готово: ${items.length} товаров, файл скачан`);
})();
