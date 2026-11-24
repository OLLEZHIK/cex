/*
 * CeX scanner — вставь в консоль браузера (F12 → Console), открыв сайт CeX:
 *   ie.webuy.com  — соберёт цены выкупа (cash) в Ирландии
 *   uk.webuy.com / es.webuy.com / pt.webuy.com — соберёт цены продажи там
 * Скрипт пройдёт по категориям «Phones» и «Gaming» и скачает JSON-файл.
 * Потом открой compare.html и загрузи туда файлы.
 */
(async () => {
  const region = (location.hostname.match(/^(\w+)\.webuy\.com$/) || [])[1];
  if (!region) { alert('Открой ie/uk/es/pt.webuy.com и запусти снова'); return; }
  const API = `https://wss2.cex.${region}.webuy.io/v3`;
  const SUPERCATS = [1, 4];          // 1 = Gaming, 4 = Phones (поменяй при желании)
  const PAGE = 50, DELAY_MS = 600;   // не долбим сервер: ~1.5 запроса в секунду
  const sleep = ms => new Promise(r => setTimeout(r, ms));
  const get = async path => {
    for (let i = 0; i < 4; i++) {
      const r = await fetch(API + path, { credentials: 'omit' });
      if (r.ok) return (await r.json()).response.data;
      await sleep(3000 * (i + 1));
    }
    throw new Error('Запрос не удался: ' + path);
  };

  const cats = (await get(`/categories?superCatIds=[${SUPERCATS}]`)).categories;
  console.log(`[${region}] категорий: ${cats.length}`);
  const out = [];
  for (const [ci, c] of cats.entries()) {
    let first = 1, total = Infinity;
    while (first <= total) {
      const d = await get(`/boxes?categoryIds=[${c.categoryId}]&firstRecord=${first}&count=${PAGE}&sortBy=relevance&sortOrder=desc`);
      if (!d || !d.boxes) break;
      total = d.totalRecords;
      for (const b of d.boxes) out.push({
        boxId: b.boxId, name: b.boxName, category: b.categoryFriendlyName || b.categoryName,
        superCat: b.superCatFriendlyName || b.superCatName,
        sell: b.sellPrice, cash: b.cashPrice, voucher: b.exchangePrice,
        stock: b.ecomQuantityOnHand ?? null, outOfStock: !!b.outOfStock,
      });
      first += PAGE;
      await sleep(DELAY_MS);
    }
    console.log(`[${region}] ${ci + 1}/${cats.length} ${c.categoryFriendlyName}: всего товаров ${out.length}`);
  }
  const blob = new Blob([JSON.stringify({ region, scannedAt: new Date().toISOString(), items: out })], { type: 'application/json' });
  const a = Object.assign(document.createElement('a'), { href: URL.createObjectURL(blob), download: `cex-${region}-${new Date().toISOString().slice(0, 10)}.json` });
  document.body.appendChild(a); a.click(); a.remove();
  console.log(`[${region}] готово: ${out.length} товаров, файл скачан`);
})();
