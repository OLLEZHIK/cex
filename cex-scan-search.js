/*
 * CeX scanner через поиск сайта (Algolia) — для случая, когда /v3/boxes отдаёт 403.
 * 1) Открой REGION.webuy.com/search?stext=iphone (ie / es / pt / uk) и дождись товаров.
 * 2) F12 → Console, вставь этот скрипт, Enter. Через 5–30 мин скачается cex-REGION-ДАТА.json.
 * Ключ и индекс берутся из запросов, которые страница уже сделала сама. Пауза 2 с; на 429 ждём 1,2,4… мин.
 * Повторный запуск в той же вкладке продолжает с места остановки.
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
  const DELAY_MS = 2000, sleep = ms => new Promise(r => setTimeout(r, ms));
  let nreq = 0;
  // 429 приходит без CORS-заголовков, поэтому fetch падает исключением — тоже считаем это «притормози»
  const q = async body => {
    for (let i = 0; i < 5; i++) {
      let r = null;
      try { r = await fetch(URL_Q, { method: 'POST', body: JSON.stringify(body) }); } catch (e) {}
      nreq++;
      if (r && r.ok) { await sleep(DELAY_MS); return r.json(); }
      if (r && r.status === 403) throw new Error('403 от поиска — останавливаемся');
      const wait = 60000 * 2 ** i;
      console.warn(`[${region}] сервер просит притормозить (${r ? r.status : '429/сеть'}), ждём ${wait / 60000} мин`);
      await sleep(wait);
    }
    throw new Error('Поиск не отвечает после 5 попыток');
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
  // состояние живёт в окне: повторный запуск в той же вкладке продолжит с места остановки
  const st = window.__cexScan && window.__cexScan.region === region ? window.__cexScan : (window.__cexScan = { region, out: new Map(), done: new Set(), lost: 0 });
  const out = st.out;
  if (st.done.size) console.log(`[${region}] продолжаем: уже ${st.done.size} категорий, ${out.size} товаров`);
  const add = hits => { for (const h of hits) {
    const stock = pick(h, 'ecomQuantityOnHand', 'ecomQuantity');
    const item = {
      boxId: pick(h, 'boxId', 'objectID'), name: pick(h, 'boxName'),
      category: pick(h, 'categoryFriendlyName', 'categoryName'), superCat: pick(h, 'superCatFriendlyName', 'superCatName'),
      sell: pick(h, 'sellPrice'), cash: pick(h, 'cashPriceCalculated', 'cashBuyPrice'),
      voucher: pick(h, 'exchangePriceCalculated', 'exchangePrice'),
      stock, outOfStock: stock != null ? !(+stock > 0) : ['1', 1, true].includes(pick(h, 'outOfStock')),
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
    if (hi - lo <= 1) { st.lost += d.nbHits - 1000; console.warn(`  ${cat} €${lo}: ${d.nbHits} товаров по одной цене, взяли 1000`); return add(d.hits); }
    const mid = Math.round(hi > 4000 && lo < 2000 ? 2000 : (lo + hi) / 2);
    await collect(cat, lo, mid); await collect(cat, mid, hi);
  };
  let failed = null;
  for (const [ci, cat] of cats.entries()) {
    if (st.done.has(cat)) continue;
    try { await collect(cat, MIN_SELL, 100000); } catch (e) { failed = e; break; }
    st.done.add(cat);
    console.log(`[${region}] ${ci + 1}/${cats.length} ${cat}: всего ${out.size} (запросов ${nreq})`);
  }
  if (failed) console.error(`[${region}] остановились: ${failed.message}. Сохраняю собранное; через 15–30 мин запусти скрипт снова В ЭТОЙ ЖЕ вкладке — продолжит`);
  const lost = st.lost;
  const items = [...out.values()];
  const blob = new Blob([JSON.stringify({ region, scannedAt: new Date().toISOString(), source: 'search', minSell: MIN_SELL, complete: !failed, categoriesDone: st.done.size, categoriesTotal: cats.length, items })], { type: 'application/json' });
  const a = Object.assign(document.createElement('a'), { href: URL.createObjectURL(blob), download: `cex-${region}-${new Date().toISOString().slice(0, 10)}${failed ? '-partial' : ''}.json` });
  document.body.appendChild(a); a.click(); a.remove();
  console.log(`[${region}] готово: ${items.length} товаров${lost ? `, не влезло ${lost}` : ''}, файл скачан`);
})();
