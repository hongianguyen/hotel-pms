
/* ================= guest ordering (added 04 Sep 2026) =================

   Bolted onto the 24 Aug page rather than replacing it. The page keeps its
   own curated, fully translated menu; this layer only asks the till which of
   those dishes exist right now, what they cost today, and which product id
   to put on the order. Nothing here re-renders the prose, the schedule or
   the set-menu descriptions.

   LINK maps a page dish to the product(s) it became on the till -- see
   menu_link.py for why that mapping is curated by hand.
   ==================================================================== */

const OAPI  = (window.LAK_API || "/api/lak").replace(/\/$/, "");
const TILL  = {};        // normalised till name -> {id, price}
const VSEL  = {};        // page dish -> index of the chosen variant
let   CART  = {};        // product id -> {qty, label, price}
let   ROOMS = [];

/* The PMS calls the rooms BUN01..KPAN04; guests know them by name. Both are
   shown -- "Jun (BUN01)" -- and the CODE is what gets sent, so reception
   reads the code it already uses and any mis-pairing here is visible on the
   order rather than silently wrong. Owner's list, 04 Sep 2026. */
const ROOMNAME = {
  BUN01: "Jun", BUN02: "Mlieng", BUN03: "B'Hok", BUN04: "Drung",
  KPAN01: "Kpan 1", KPAN02: "Kpan 2", KPAN03: "Kpan 3",
  KPAN04: "Kpan 4 (Dur Kman)"
};
function roomLabel(r){
  const n = ROOMNAME[r.code];
  if(n) return n + " · " + r.code;
  if(/^TENT(\d+)$/.test(r.code))
    return "Lake View Tent " + Number(r.code.slice(4)) + " · " + r.code;
  return r.code + (r.type ? " — " + r.type : "");
}
let   SENDING = false;

/* Same normalisation as build_link.py. Keep the two in step: the lake is
   spelled Lăk, Lak and Lắk across the till, the deck and the page. */
function onorm(s){
  s = (s || "").normalize("NFC").toLowerCase();
  s = s.split("lăk").join("lắk").split("lak").join("lắk");
  return s.replace(/[+\/]/g, " ").replace(/\s+/g, " ").trim();
}

const OT = {
  bar1:   {en:"1 item",  vi:"1 món",     fr:"1 plat",     he:"מנה אחת"},
  barN:   {en:"%n items",vi:"%n món",    fr:"%n plats",   he:"%n מנות"},
  clear:  {en:"Clear",   vi:"Xoá",       fr:"Vider",      he:"נקה"},
  book:   {en:"Book",    vi:"Đặt món",   fr:"Commander",  he:"להזמין"},
  title:  {en:"Send this to the kitchen",       vi:"Gửi đơn xuống bếp",
           fr:"Envoyer en cuisine",             he:"לשלוח למטבח"},
  sub:    {en:"Meals are served in the restaurant. Reception will confirm before anything is charged.",
           vi:"Các món được phục vụ tại nhà hàng. Lễ tân sẽ xác nhận trước khi tính tiền.",
           fr:"Les repas sont servis au restaurant. La réception confirmera avant toute facturation.",
           he:"הארוחות מוגשות במסעדה. הקבלה תאשר לפני שנחייב אתכם."},
  total:  {en:"Total",   vi:"Tổng cộng", fr:"Total",      he:"סה״כ"},
  room:   {en:"Room",    vi:"Phòng",     fr:"Chambre",    he:"חדר"},
  name:   {en:"Your name",vi:"Tên của bạn",fr:"Votre nom",he:"השם שלכם"},
  time:   {en:"Time you would like to eat", vi:"Giờ bạn muốn dùng bữa",
           fr:"Heure du repas",             he:"שעת הארוחה"},
  note:   {en:"Anything we should know? Allergies, no chilli…",
           vi:"Bạn cần lưu ý gì không? Dị ứng, không cay…",
           fr:"Quelque chose à signaler ? Allergies, sans piment…",
           he:"משהו שכדאי שנדע? אלרגיות, בלי חריף…"},
  cancel: {en:"Not yet",  vi:"Để sau",   fr:"Pas encore", he:"עוד לא"},
  send:   {en:"Send order",vi:"Gửi đơn", fr:"Envoyer",    he:"שליחה"},
  sending:{en:"Sending…", vi:"Đang gửi…",fr:"Envoi…",     he:"שולח…"},
  pick:   {en:"Choose a room", vi:"Chọn phòng", fr:"Choisissez une chambre",
           he:"בחרו חדר"},
  off:    {en:"Ask us",   vi:"Hỏi nhân viên", fr:"Demandez-nous", he:"שאלו אותנו"},
  ok:     {en:"Order %r is with the kitchen. Reception will confirm it.",
           vi:"Đơn %r đã xuống bếp. Lễ tân sẽ xác nhận.",
           fr:"Commande %r transmise à la cuisine. La réception confirmera.",
           he:"הזמנה %r הועברה למטבח. הקבלה תאשר."},
  need:   {en:"Please give your room and name.",
           vi:"Vui lòng cho biết phòng và tên.",
           fr:"Indiquez votre chambre et votre nom.",
           he:"נא למלא חדר ושם."},
  bad:    {en:"That did not go through. Please call reception.",
           vi:"Gửi không thành công. Vui lòng gọi lễ tân.",
           fr:"L'envoi a échoué. Appelez la réception.",
           he:"השליחה נכשלה. התקשרו לקבלה."},
  closed: {en:"The kitchen is not taking orders on the app right now.",
           vi:"Bếp hiện chưa nhận đơn qua ứng dụng.",
           fr:"La cuisine ne prend pas de commandes ici pour le moment.",
           he:"המטבח לא מקבל כרגע הזמנות דרך האתר."}
};
function ot(k, sub){
  let s = (OT[k] && (OT[k][LANG] || OT[k].en)) || "";
  if(sub) Object.keys(sub).forEach(x => { s = s.split(x).join(sub[x]); });
  return s;
}

/* ---------- what the till actually sells ---------- */
function loadTill(){
  return fetch(OAPI + "/menu", {headers:{accept:"application/json"}})
    .then(r => r.ok ? r.json() : Promise.reject(r.status))
    .then(d => {
      (d.items || []).forEach(it => {
        TILL[onorm(it.name_vi)] = {id: it.id, price: it.price};
      });
      drawFood();
    })
    .catch(() => { /* no till: the page stays a menu, ordering just never appears */ });
}

function loadRooms(){
  return fetch(OAPI + "/rooms", {headers:{accept:"application/json"}})
    .then(r => r.ok ? r.json() : Promise.reject(r.status))
    .then(d => { ROOMS = d.rooms || []; drawRooms(); })
    .catch(() => {});
}

/* A page dish -> the till options behind it, or null if it is not sellable. */
function options(m){
  const L = LINK.items[m.vi];
  if(!L || L.absent) return null;
  const names = L.p ? [L.p] : (L.v || []);
  const out = [];
  names.forEach(n => {
    const t = TILL[onorm(n)];
    if(t) out.push({label: n, id: t.id, price: t.price});
  });
  return out.length ? out : null;
}
function chosen(m){
  const o = options(m);
  if(!o) return null;
  const i = Math.min(VSEL[m.vi] || 0, o.length - 1);
  return o[i];
}

/* ---------- cart ---------- */
function bump(m, delta){
  const c = chosen(m);
  if(!c) return;
  const cur = (CART[c.id] || {}).qty || 0;
  const next = Math.max(0, Math.min(30, cur + delta));
  if(next === 0) delete CART[c.id];
  else CART[c.id] = {qty: next, label: c.label, price: c.price};
  drawMenu(); drawSets(); drawBarTotals();
}
function cartCount(){ return Object.values(CART).reduce((a, l) => a + l.qty, 0); }
function cartTotal(){ return Object.values(CART).reduce((a, l) => a + l.qty * l.price, 0); }

function stepper(m){
  const c = chosen(m);
  if(!c) return '<div class="moff">' + ot("off") + '</div>';
  const n = (CART[c.id] || {}).qty || 0;
  const k = encodeURIComponent(m.vi);
  return '<div class="mqty">' +
    '<button type="button" data-step="-1" data-k="' + k + '" aria-label="-"' +
      (n ? '' : ' disabled') + '>−</button>' +
    '<span class="n" data-zero="' + (n ? "false" : "true") + '">' + n + '</span>' +
    '<button type="button" data-step="1" data-k="' + k + '" aria-label="+">+</button>' +
    '</div>';
}
function variantPicker(m){
  const o = options(m);
  const L = LINK.items[m.vi];
  const asked = (L && L.v) ? L.v.length : 1;
  if(!o) return "";
  // The till may carry only some of a group -- it sells four kinds of fried
  // noodle but only three glass-noodle ones. Say which one the guest is
  // actually getting rather than silently narrowing the choice to it.
  if(o.length === 1) return asked > 1
    ? '<div class="mvar"><span class="mone">' + o[0].label + '</span></div>' : "";
  const i = Math.min(VSEL[m.vi] || 0, o.length - 1);
  return '<div class="mvar"><select data-var="' + encodeURIComponent(m.vi) + '">' +
    o.map((x, j) => '<option value="' + j + '"' + (j === i ? " selected" : "") +
                    '>' + x.label + '</option>').join("") +
    '</select></div>';
}

/* ---------- re-render the menu with steppers ----------
   drawMenu and drawSets are replaced, not edited: the originals stay in the
   page above, and this reassignment keeps the same grouping, sorting and
   empty-state wording so the only visible change is the quantity control. */
const _origDrawMenu = drawMenu;
drawMenu = function(){
  _origDrawMenu();                                  // wording, groups, sorting
  const box = document.getElementById("mlist");
  if(!box) return;
  const q = strip(MQ.trim());
  const hits = MENU.filter(m =>
    (MCAT === "all" || m.c === MCAT) &&
    !(m.t || []).some(t => OFF.has(t)) &&
    (!q || strip(m.vi).includes(q) || strip(m.en).includes(q)));
  const order = CATS.map(c => c.k).filter(k => k !== "all");
  const sorted = hits.slice().sort((a, b) => order.indexOf(a.c) - order.indexOf(b.c));

  const rows = box.querySelectorAll(".mitem");
  sorted.forEach((m, i) => {
    const row = rows[i];
    if(!row) return;
    const c = chosen(m);
    if(c){                                          // live price beats the printed one
      const p = row.querySelector(".mp");
      if(p) p.textContent = vnd(c.price);
    }
    const txt = row.querySelector(".mtxt");
    if(txt) txt.insertAdjacentHTML("beforeend", variantPicker(m));
    row.insertAdjacentHTML("beforeend", stepper(m));
  });
};

const _origDrawSets = drawSets;
drawSets = function(){
  _origDrawSets();
  const box = document.getElementById("setlist");
  if(!box) return;
  box.querySelectorAll(".setcard").forEach((card, i) => {
    const s = SETS[i];
    if(!s) return;
    const name = LINK.sets[s.n + "|" + s.p];
    const t = name ? TILL[onorm(name)] : null;
    if(!t) return;
    const n = (CART[t.id] || {}).qty || 0;
    const k = "set:" + i;
    card.insertAdjacentHTML("beforeend",
      '<div class="mqty">' +
      '<button type="button" data-sstep="-1" data-k="' + k + '" aria-label="-"' +
        (n ? '' : ' disabled') + '>−</button>' +
      '<span class="n" data-zero="' + (n ? "false" : "true") + '">' + n + '</span>' +
      '<button type="button" data-sstep="1" data-k="' + k + '" aria-label="+">+</button>' +
      '</div>');
  });
};

function bumpSet(i, delta){
  const s = SETS[i];
  if(!s) return;
  const name = LINK.sets[s.n + "|" + s.p];
  const t = name ? TILL[onorm(name)] : null;
  if(!t) return;
  const cur = (CART[t.id] || {}).qty || 0;
  const next = Math.max(0, Math.min(30, cur + delta));
  if(next === 0) delete CART[t.id];
  else CART[t.id] = {qty: next, label: name, price: t.price};
  drawMenu(); drawSets(); drawBarTotals();
}

/* ---------- the bar and the sheet ---------- */
function drawBarTotals(){
  const bar = document.getElementById("obar");
  if(!bar) return;
  const n = cartCount();
  bar.dataset.show = n > 0 ? "true" : "false";
  document.getElementById("osum").innerHTML =
    (n === 1 ? ot("bar1") : ot("barN", {"%n": n})) + " · <b>" + vnd(cartTotal()) + "</b>";
  document.getElementById("oclear").textContent = ot("clear");
  document.getElementById("obook").textContent = ot("book");
}

function drawRooms(){
  const sel = document.getElementById("oroom");
  if(!sel) return;
  const keep = sel.value;
  sel.innerHTML = '<option value="">' + ot("pick") + "</option>" +
    ROOMS.map(r => '<option value="' + r.code + '">' + roomLabel(r) +
                   "</option>").join("");
  if(keep) sel.value = keep;
}

function drawSheet(){
  document.getElementById("otitle").textContent    = ot("title");
  document.getElementById("osubtitle").textContent = ot("sub");
  document.getElementById("ototlab").textContent   = ot("total");
  document.getElementById("oroomlab").textContent  = ot("room");
  document.getElementById("onamelab").textContent  = ot("name");
  document.getElementById("otimelab").textContent  = ot("time");
  document.getElementById("onotelab").textContent  = ot("note");
  document.getElementById("ocancel").textContent   = ot("cancel");
  document.getElementById("osend").textContent     = SENDING ? ot("sending") : ot("send");
  document.getElementById("olines").innerHTML =
    Object.values(CART).map(l =>
      "<div><span>" + l.qty + " × " + l.label + "</span><span>" +
      vnd(l.qty * l.price) + "</span></div>").join("");
  document.getElementById("ototal").textContent = vnd(cartTotal());
  drawRooms();
}

function msg(kind, text){
  const el = document.getElementById("omsg");
  el.dataset.kind = kind || "";
  el.textContent = text || "";
  if(!kind) el.removeAttribute("data-kind");
}

function send(){
  if(SENDING) return;
  const room = document.getElementById("oroom").value.trim();
  const name = document.getElementById("oname").value.trim();
  if(!room || !name){ msg("err", ot("need")); return; }
  SENDING = true; drawSheet(); msg("", "");
  fetch(OAPI + "/order", {
    method: "POST",
    headers: {"content-type": "application/json"},
    body: JSON.stringify({
      room: room, name: name,
      dine_at: document.getElementById("otime").value.trim(),
      note: document.getElementById("onote").value.trim(),
      lang: LANG,
      lines: Object.keys(CART).map(id => ({id: Number(id), qty: CART[id].qty}))
    })
  })
  .then(r => r.json().catch(() => ({ok: false})))
  .then(d => {
    SENDING = false;
    if(d && d.ok){
      msg("ok", ot("ok", {"%r": d.reference || ""}));
      CART = {};
      drawMenu(); drawSets(); drawBarTotals();
      setTimeout(() => { document.getElementById("osheet").close(); msg("", ""); }, 2600);
    } else {
      msg("err", (d && d.error === "disabled") ? ot("closed") : ot("bad"));
    }
    drawSheet();
  })
  .catch(() => { SENDING = false; msg("err", ot("bad")); drawSheet(); });
}

/* ---------- wiring ---------- */
document.addEventListener("click", e => {
  const b = e.target.closest("button[data-step], button[data-sstep]");
  if(!b) return;
  if(b.dataset.sstep) bumpSet(Number(b.dataset.k.split(":")[1]), Number(b.dataset.sstep));
  else {
    const vi = decodeURIComponent(b.dataset.k);
    const m = MENU.find(x => x.vi === vi);
    if(m) bump(m, Number(b.dataset.step));
  }
});
document.addEventListener("change", e => {
  const s = e.target.closest("select[data-var]");
  if(!s) return;
  VSEL[decodeURIComponent(s.dataset.var)] = Number(s.value);
  drawMenu();
});
document.getElementById("oclear").addEventListener("click", () => {
  CART = {}; drawMenu(); drawSets(); drawBarTotals();
});
document.getElementById("obook").addEventListener("click", () => {
  drawSheet(); msg("", "");
  const d = document.getElementById("osheet");
  d.showModal ? d.showModal() : (d.open = true);
});
document.getElementById("ocancel").addEventListener("click",
  () => document.getElementById("osheet").close());
document.getElementById("osend").addEventListener("click", send);

/* Language: the page's own setLang calls drawFood(); extend that so the
   ordering chrome follows the same switch instead of staying in English. */
const _origDrawFood = drawFood;
drawFood = function(){ _origDrawFood(); drawBarTotals(); drawSheet(); };

drawBarTotals();
loadTill();
loadRooms();
