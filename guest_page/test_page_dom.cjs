/*
 * Runs index.html's OWN JavaScript in a DOM (jsdom), pointed at a real Odoo,
 * and checks the two things test_worker.mjs cannot see, because that harness
 * is a fetch client and never executes the page:
 *
 *   1. do the dish names actually change when the language changes?
 *   2. does adding a dish and pressing Book put an order on the till?
 *
 * The first is what the owner reported broken. The second places a REAL
 * order, so point ODOO at test and never at production.
 *
 *   npm install --no-save jsdom && node test_page_dom.cjs
 *
 * Set NO_ORDER=1 to run only the read-only half. That is the ONLY way this
 * file may be pointed at production:
 *
 *   NO_ORDER=1 ODOO=https://pms.laktentedcamp.com node test_page_dom.cjs
 */
const { JSDOM } = require("jsdom");
const fs = require("fs");
const ODOO = process.env.ODOO || "http://103.200.20.13:8070";

const HEB = /[֐-׿]/;
let fails = 0;
const check = (ok, label, extra) => {
  console.log((ok ? "  PASS  " : "  FAIL  ") + label + (extra ? "  " + extra : ""));
  if (!ok) fails++;
};

(async () => {
  const dom = new JSDOM(fs.readFileSync("index.html", "utf8"), {
    runScripts: "dangerously", pretendToBeVisual: true,
    url: "https://lak-guest-page.example/",
    beforeParse(w) {
      w.IntersectionObserver = class { observe(){} unobserve(){} disconnect(){} };
      w.Element.prototype.scrollTo = w.Element.prototype.scrollIntoView = function(){};
      w.scrollTo = function(){};
      w.HTMLDialogElement.prototype.showModal = function(){ this.open = true; };
      w.HTMLDialogElement.prototype.close = function(){ this.open = false; };
      w.fetch = (u, o) => fetch(String(u).startsWith("http") ? u : ODOO + u, o);
    }
  });
  await new Promise(r => setTimeout(r, 5000));
  const w = dom.window, d = w.document;
  const first = () => {
    const el = d.querySelector("#mlist .mitem .mvi");
    return el ? el.textContent.trim() : "";
  };

  console.log("\n--- the reported bug: do dish names follow the language? ---");
  const seen = {};
  for (const L of ["en", "vi", "fr", "he"]) { w.setLang(L); seen[L] = first(); }
  console.log("   en:", seen.en);
  console.log("   vi:", seen.vi);
  console.log("   fr:", seen.fr);
  console.log("   he:", seen.he);
  check(seen.en !== seen.vi, "Vietnamese differs from English");
  check(seen.fr !== seen.en, "French differs from English", "<- the reported bug");
  check(HEB.test(seen.he), "Hebrew renders in Hebrew");
  w.setLang("he");
  check(d.documentElement.dir === "rtl", "Hebrew sets dir=rtl");
  w.setLang("en");

  console.log("\n--- the till ---");
  const rows = d.querySelectorAll("#mlist .mitem").length;
  const steppers = d.querySelectorAll("#mlist .mqty").length;
  const variants = d.querySelectorAll("#mlist select[data-var]").length;
  const asks = d.querySelectorAll("#mlist .moff").length;
  const narrowed = d.querySelectorAll("#mlist .mone").length;
  console.log("   rows " + rows + ", orderable " + steppers +
              ", variant pickers " + variants + ", not sold " + asks + ", narrowed to one variant " + narrowed);
  check(rows > 80, "the curated menu still renders", "(" + rows + " rows)");

  // Catalog-independent: whatever this Odoo happens to stock, every dish
  // whose linked product IS on the feed must have resolved. That is what
  // catches build_link.py and order/ui.js drifting apart on name
  // normalisation -- the failure that once showed as "orderable 0".
  const link = JSON.parse(fs.readFileSync("menu_link.json", "utf8"));
  const feed = await (await fetch(ODOO + "/api/lak/menu")).json();
  const have = new Set((feed.items || []).map(i => w.onorm(i.name_vi)));
  const expect = Object.values(link.items).filter(v => {
    const names = v.p ? [v.p] : (v.v || []);
    return names.some(n => have.has(w.onorm(n)));
  }).length;
  check(steppers === expect, "every dish this till stocks is orderable",
        "(" + steppers + " of an expected " + expect + "; prod expects 85/86)");
  check(d.querySelectorAll("#setlist .mqty").length === 12, "all 12 set menus orderable");
  check(d.querySelectorAll("#oroom option").length > 5, "room picker filled from the PMS");
  const opts = [...d.querySelectorAll("#oroom option")].map(o => o.textContent);
  const bun = opts.find(o => o.includes("BUN01")) || "";
  const kpn = opts.find(o => o.includes("KPAN04")) || "";
  check(bun.includes("Jun"), "bungalows show the guest-facing name", "(" + bun + ")");
  check(kpn.includes("Dur Kman"), "KPAN04 is Dur Kman", "(" + kpn + ")");
  check(!d.body.innerHTML.includes("In-tent dining"), "no in-tent dining offer");
  check(!/a hat|un chapeau|và mũ|וכובע/.test(d.body.innerHTML), "no hat promised");

  if (process.env.NO_ORDER) {
    console.log("\n--- ordering: SKIPPED (NO_ORDER set) ---");
    console.log(fails ? "\n" + fails + " FAILED" : "\nall read-only checks passed");
    process.exit(fails ? 1 : 0);
  }

  console.log("\n--- ordering ---");
  d.querySelector("#mlist .mqty button[data-step='1']").click();
  await new Promise(r => setTimeout(r, 120));
  check(d.getElementById("obar").dataset.show === "true", "order bar appears");
  d.getElementById("obook").click();
  check(d.getElementById("osheet").open, "order sheet opens");

  const sel = d.getElementById("oroom");
  sel.value = [...sel.options].map(o => o.value).filter(Boolean)[0];
  d.getElementById("oname").value = "DOM Probe";
  d.getElementById("otime").value = "19:30";
  d.getElementById("onote").value = "placed by test_page_dom.cjs";
  d.getElementById("osend").click();
  // The success banner clears itself after 2.6s, so poll for it rather than
  // sleeping past it -- an earlier version of this test slept 6s and reported
  // a perfectly good order as a failure.
  const m = d.getElementById("omsg");
  for (let i = 0; i < 40 && !m.dataset.kind; i++) await new Promise(r => setTimeout(r, 250));
  console.log("   room " + sel.value + " -> " + m.textContent.trim());
  check(m.dataset.kind === "ok", "the order reached the till");

  console.log(fails ? "\n" + fails + " FAILED" : "\nall checks passed");
  process.exit(fails ? 1 : 0);
})();
