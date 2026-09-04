/**
 * End-to-end check of worker.js against a running Odoo.
 *
 *   cp worker.js /tmp/w.mjs && node test_worker.mjs
 *
 * (the copy is only because Node needs an .mjs extension to load the Worker
 * as an ES module). Point ODOO_ORIGIN below at a server that has
 * lak_guest_order installed and enabled -- it places REAL orders on that
 * till, so never aim it at production.
 */
import worker from '/tmp/w.mjs';
const env = { ODOO_ORIGIN: 'http://103.200.20.13:8070' };
const call = (path, init) => worker.fetch(new Request('https://menu.example' + path, init), env);

let fails = 0;
const check = (label, cond, extra='') => {
  console.log((cond ? 'PASS  ' : 'FAIL  ') + label + (extra ? '  ' + extra : ''));
  if (!cond) fails++;
};

// 1. the page
let r = await call('/');
let body = await r.text();
check('GET / serves html', r.status === 200 && r.headers.get('content-type').startsWith('text/html'));
check('page carries the language switcher', body.includes('data-lang="he"') && body.includes('data-lang="vi"'));
check('page defaults to same-origin API', body.includes('window.LAK_API || "/api/lak"'));

// 2. menu proxy
r = await call('/api/lak/menu');
const menu = await r.json();
check('GET /api/lak/menu proxied', r.status === 200 && Array.isArray(menu.items), 'items=' + menu.count);
check('menu items carry both names', menu.items.every(i => 'name_vi' in i && 'name_en' in i));
check('menu is cacheable, briefly', r.headers.get('cache-control') === 'public, max-age=60');

// 3. rooms
r = await call('/api/lak/rooms');
const rooms = await r.json();
check('GET /api/lak/rooms proxied', r.status === 200 && rooms.rooms.length > 0, rooms.rooms.length + ' rooms');
check('rooms leak no guest data', rooms.rooms.every(x => Object.keys(x).sort().join() === 'code,type'));

// 4. a real order, exactly as the page sends it
const two = menu.items.filter(i => i.name_vi !== i.name_en).slice(0, 2);
r = await call('/api/lak/order', {
  method: 'POST', headers: {'Content-Type':'application/json'},
  body: JSON.stringify({ room:'BUN02', name:'Worker Test', dine_at:'20:00',
    note:'via worker', lang:'fr', lines: two.map((i,n) => ({id:i.id, qty:n+1})) })
});
const ord = await r.json();
check('POST /api/lak/order creates an order', r.status === 200 && ord.ok === true, JSON.stringify(ord));
check('order is never cached', r.headers.get('cache-control') === 'no-store');

// 5. rejections
r = await call('/api/lak/order', { method:'POST', headers:{'Content-Type':'application/json'},
  body: JSON.stringify({ room:'NOPE', name:'x', lines:[{id:two[0].id, qty:1}] }) });
check('unknown room rejected', (await r.json()).error === 'unknown_room');

r = await call('/api/lak/secrets');
check('unlisted api path 404s', r.status === 404);
r = await call('/wp-admin');
check('unknown path 404s', r.status === 404);
r = await call('/api/lak/menu', { method: 'DELETE' });
check('DELETE refused', r.status === 405);

// 6. unconfigured worker
r = await worker.fetch(new Request('https://menu.example/api/lak/menu'), {});
check('no ODOO_ORIGIN -> 503, not a crash', r.status === 503);

console.log(fails ? `\n${fails} FAILED` : '\nall green');
process.exit(fails ? 1 : 0);
