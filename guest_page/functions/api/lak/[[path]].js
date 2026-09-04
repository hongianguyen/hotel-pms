/**
 * Cloudflare Pages Function: proxies /api/lak/* through to Odoo.
 *
 * This exists to solve a problem that has no fix on the page itself. Pages
 * serves the site over HTTPS, and a browser will not let an HTTPS page call
 * an HTTP address -- so the page cannot talk to http://14.225.192.16
 * directly, silently, no error the guest can see. Routing through here keeps
 * every request the browser makes same-origin: no mixed content, no CORS
 * preflight, and the Odoo address is never exposed to the guest's device.
 *
 * Set ODOO_ORIGIN in the Pages project (Settings -> Environment variables),
 * e.g.  https://pms.laktentedcamp.com   or   http://14.225.192.16
 *
 * If you point it at the plain-HTTP address, note that the hop from
 * Cloudflare's edge to the camp is then unencrypted. It carries guest names
 * and room numbers, so prefer the HTTPS hostname once the managed-challenge
 * rule is lifted for /api/.
 */
export async function onRequest(context) {
  const { request, env, params } = context;
  const origin = (env.ODOO_ORIGIN || "").replace(/\/$/, "");
  if (!origin) {
    return json({ ok: false, error: "not_configured" }, 503);
  }

  const path = Array.isArray(params.path) ? params.path.join("/") : (params.path || "");
  if (!/^(menu|rooms|order)$/.test(path)) {
    return json({ ok: false, error: "not_found" }, 404);
  }

  const url = new URL(request.url);
  const target = `${origin}/api/lak/${path}${url.search}`;

  // Only the method and the body travel on. Not the guest's cookies, and not
  // their Origin header -- Odoo's allowlist is for direct browser calls, and
  // this hop is server to server.
  const init = {
    method: request.method,
    headers: { "Content-Type": "application/json", "Accept": "application/json" },
  };
  if (request.method === "POST") {
    init.body = await request.text();
  }

  try {
    const upstream = await fetch(target, init);
    const body = await upstream.text();
    return new Response(body, {
      status: upstream.status,
      headers: {
        "Content-Type": "application/json; charset=utf-8",
        // The menu changes when the kitchen changes it; a stale cached menu
        // would quote prices that no longer exist.
        "Cache-Control": path === "order" ? "no-store" : "public, max-age=60",
      },
    });
  } catch (err) {
    return json({ ok: false, error: "upstream_unreachable" }, 502);
  }
}

function json(obj, status) {
  return new Response(JSON.stringify(obj), {
    status,
    headers: { "Content-Type": "application/json; charset=utf-8", "Cache-Control": "no-store" },
  });
}
