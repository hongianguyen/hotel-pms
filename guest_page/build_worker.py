#!/usr/bin/env python3
"""Inline index.html into a single Cloudflare Worker script.

`index.html` stays the source of truth -- edit that, re-run this, paste the
result. The page is embedded with json.dumps rather than a JS template
literal so that a backtick, a ``${`` or a ``</script>`` appearing in the HTML
one day cannot break the script; JSON string escaping is total.

    python3 build_worker.py        ->  worker.js
"""
import json
import pathlib

HERE = pathlib.Path(__file__).parent
HTML = (HERE / "index.html").read_text(encoding="utf-8")

WORKER = '''/**
 * Lak Tented Camp - guest page + order API, as ONE Cloudflare Worker.
 *
 * GENERATED FILE. Edit index.html and re-run build_worker.py; changes made
 * here are lost on the next build.
 *
 * Routes
 *   GET  /                  the page
 *   GET  /api/lak/menu      -> Odoo
 *   GET  /api/lak/rooms     -> Odoo
 *   POST /api/lak/order     -> Odoo
 *
 * Serving the page and the API from one Worker is what makes the ordering
 * work at all. The browser only ever talks to this Worker, so every request
 * is same-origin: no CORS preflight, and -- the one that actually bites -- no
 * mixed content. A Worker is served over HTTPS, and a browser silently
 * refuses to let an HTTPS page call http://14.225.192.16. It fails with no
 * error the guest can see; the menu simply never loads. The hop to Odoo
 * happens here instead, server-side, where that rule does not apply.
 *
 * Set one variable on the Worker (Settings -> Variables and Secrets):
 *
 *   ODOO_ORIGIN = http://14.225.192.16
 *          or     https://pms.laktentedcamp.com
 *
 * Prefer the hostname: the edge-to-camp hop carries guest names and room
 * numbers, and over plain HTTP it is unencrypted. It only works once a
 * Cloudflare WAF skip rule exists for /api/lak/* -- without one the managed
 * challenge answers this Worker's own subrequest with a 403 challenge page,
 * and the page reports that it cannot reach the kitchen.
 */

const PAGE = %(html)s;

const ALLOWED = new Set(["menu", "rooms", "order"]);

export default {
  async fetch(request, env) {
    const url = new URL(request.url);

    if (url.pathname === "/" || url.pathname === "/index.html") {
      return new Response(PAGE, {
        headers: {
          "Content-Type": "text/html; charset=utf-8",
          // Short: the camp edits the page more often than a guest reloads it.
          "Cache-Control": "public, max-age=300",
          "X-Content-Type-Options": "nosniff",
          "Referrer-Policy": "same-origin",
        },
      });
    }

    if (url.pathname.startsWith("/api/lak/")) {
      return proxy(request, env, url);
    }

    return new Response("Not found", { status: 404 });
  },
};

async function proxy(request, env, url) {
  const origin = (env.ODOO_ORIGIN || "").replace(/\\/$/, "");
  if (!origin) return json({ ok: false, error: "not_configured" }, 503);

  const path = url.pathname.slice("/api/lak/".length);
  if (!ALLOWED.has(path)) return json({ ok: false, error: "not_found" }, 404);

  if (request.method === "OPTIONS") return new Response(null, { status: 204 });
  if (request.method !== "GET" && request.method !== "POST") {
    return json({ ok: false, error: "method_not_allowed" }, 405);
  }

  // Only the method and the body travel on -- not the guest's cookies, and
  // not their Origin header. This hop is server to server; Odoo's own origin
  // allowlist is there for the case where a browser calls it directly.
  const init = {
    method: request.method,
    headers: { "Content-Type": "application/json", "Accept": "application/json" },
  };
  if (request.method === "POST") init.body = await request.text();

  let upstream;
  try {
    upstream = await fetch(origin + "/api/lak/" + path + url.search, init);
  } catch (err) {
    return json({ ok: false, error: "upstream_unreachable" }, 502);
  }

  const body = await upstream.text();
  return new Response(body, {
    status: upstream.status,
    headers: {
      "Content-Type": "application/json; charset=utf-8",
      // Never cache an order. A briefly cached menu is fine and takes load
      // off the camp's single Odoo box.
      "Cache-Control": path === "order" ? "no-store" : "public, max-age=60",
    },
  });
}

function json(obj, status) {
  return new Response(JSON.stringify(obj), {
    status,
    headers: {
      "Content-Type": "application/json; charset=utf-8",
      "Cache-Control": "no-store",
    },
  });
}
''' % {"html": json.dumps(HTML)}

out = HERE / "worker.js"
out.write_text(WORKER, encoding="utf-8")
print("worker.js written: %d bytes (page %d of it)" % (len(WORKER), len(HTML)))
