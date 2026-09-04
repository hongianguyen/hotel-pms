# -*- coding: utf-8 -*-
"""The public API the Cloudflare-hosted guest page talks to.

Three routes, all ``type='http'`` returning bare JSON -- not ``type='jsonrpc'``,
which would wrap every reply in ``{"jsonrpc": "2.0", "result": ...}`` and make
the page parse Odoo's envelope. (Same reasoning as
``hotel_channel_aiosell``'s webhook.)

Order creation deliberately goes through Odoo's OWN self-order path --
``pos.order._check_pos_order()`` then ``sync_from_ui()`` -- rather than
building a ``pos.order`` by hand. Three things come free that way and are
easy to get wrong alone: the POS reference and tracking number are allocated
by the config, ``recompute_prices()`` recalculates every line server-side so a
price edited in the request body is ignored, and ``pos_self_order``'s
``sync_from_ui`` override notifies the open POS so the order appears on the
cashier's screen immediately.
"""
import json
import logging
import time
import uuid
from collections import defaultdict, deque

from odoo import fields, http
from odoo.http import request

_logger = logging.getLogger(__name__)

MAX_LINES = 40           # distinct dishes in one order
MAX_QTY = 30             # of any one dish
MAX_TEXT = 200           # room / name / time / note field length
RATE_MAX = 12            # orders ...
RATE_WINDOW = 300        # ... per IP per 5 minutes

# Per-worker, so with N workers the real ceiling is N*RATE_MAX. That is fine
# for what this defends against -- a bored guest hammering the Book button --
# and it needs no table and no cron to prune.
_RECENT = defaultdict(deque)


class LakGuestOrder(http.Controller):

    # ------------------------------------------------------------------ util
    def _cors(self, origin):
        """Headers for the Cloudflare Pages origin.

        The allowlist is a system parameter rather than '*' because these
        routes write: '*' would let any page on the internet put orders on
        the till from a guest's browser.
        """
        allowed = [
            o.strip() for o in (request.env['ir.config_parameter'].sudo()
                                .get_param('lak_guest_order.allowed_origins') or '')
            .split(',') if o.strip()
        ]
        headers = [('Content-Type', 'application/json; charset=utf-8'),
                   ('Cache-Control', 'no-store'),
                   ('Vary', 'Origin')]
        if origin and origin in allowed:
            headers += [
                ('Access-Control-Allow-Origin', origin),
                ('Access-Control-Allow-Methods', 'GET, POST, OPTIONS'),
                ('Access-Control-Allow-Headers', 'Content-Type'),
                ('Access-Control-Max-Age', '86400'),
            ]
        return headers

    def _reply(self, payload, status=200):
        origin = request.httprequest.headers.get('Origin')
        return request.make_response(
            json.dumps(payload, ensure_ascii=False),
            headers=self._cors(origin), status=status)

    def _enabled(self):
        return (request.env['ir.config_parameter'].sudo()
                .get_param('lak_guest_order.enabled') or '0').strip() in (
                    '1', 'true', 'True')

    def _config(self):
        """The POS config the guest page orders against.

        Resolved by access token, the same token the built-in QR menu uses, so
        rotating it in the POS settings cuts the page off too.
        """
        token = (request.env['ir.config_parameter'].sudo()
                 .get_param('lak_guest_order.pos_access_token') or '').strip()
        if not token:
            return None
        return request.env['pos.config'].sudo().search(
            [('access_token', '=', token)], limit=1)

    def _rate_limited(self):
        ip = request.httprequest.remote_addr or '-'
        now = time.monotonic()
        hits = _RECENT[ip]
        while hits and now - hits[0] > RATE_WINDOW:
            hits.popleft()
        if len(hits) >= RATE_MAX:
            return True
        hits.append(now)
        return False

    def _clean(self, value, limit=MAX_TEXT):
        if not isinstance(value, str):
            return ''
        # Strip control characters: these end up in an email and in the POS
        # order label, and a newline in the middle of the room code makes both
        # unreadable.
        return ''.join(c for c in value if c.isprintable()).strip()[:limit]

    # ------------------------------------------------------------- preflight
    @http.route(['/api/lak/menu', '/api/lak/order', '/api/lak/rooms'],
                type='http', auth='public', methods=['OPTIONS'],
                csrf=False, save_session=False)
    def preflight(self, **kw):
        return self._reply({}, status=204)

    # ------------------------------------------------------------------ menu
    @http.route('/api/lak/menu', type='http', auth='public', methods=['GET'],
                csrf=False, save_session=False)
    def menu(self, **kw):
        if not self._enabled():
            return self._reply({'error': 'disabled'}, status=503)
        config = self._config()
        if not config:
            return self._reply({'error': 'not_configured'}, status=503)

        products = request.env['product.template'].sudo().search([
            ('available_in_pos', '=', True),
            ('list_price', '>', 0),
        ], order='name')

        items = []
        for product in products:
            # Names on this database are stored bilingual, "VIETNAMESE /
            # English" (see tools/ylak_menu_import). Split them so the page can
            # show one language at a time; a name with no separator is already
            # international (MOJITO, the wines) and is used for both.
            vi, sep, en = (product.name or '').partition(' / ')
            items.append({
                'id': product.product_variant_id.id,
                'name_vi': vi.strip(),
                'name_en': (en.strip() if sep else vi.strip()),
                'description': product.description_sale or '',
                'price': product.list_price,
                'category': (product.pos_categ_ids[:1].name
                             if product.pos_categ_ids else ''),
                'is_combo': product.type == 'combo',
            })
        return self._reply({
            'currency': config.currency_id.name,
            'count': len(items),
            'items': items,
        })

    # ----------------------------------------------------------------- rooms
    @http.route('/api/lak/rooms', type='http', auth='public', methods=['GET'],
                csrf=False, save_session=False)
    def rooms(self, **kw):
        """Room CODES only.

        Deliberately no guest names, no occupancy and no rates: this is an
        unauthenticated endpoint, and all the page needs is a valid list to
        build its picker from.
        """
        if not self._enabled():
            return self._reply({'error': 'disabled'}, status=503)
        rooms = request.env['hotel.room'].sudo().search([], order='name')
        return self._reply({'rooms': [
            {'code': r.name, 'type': r.room_type_id.name or ''} for r in rooms
        ]})

    # ----------------------------------------------------------------- order
    @http.route('/api/lak/order', type='http', auth='public', methods=['POST'],
                csrf=False, save_session=False, readonly=False)
    def order(self, **kw):
        # readonly=False is not decorative. Odoo gives public routes a
        # read-only cursor by default; this one writes. On a server with no
        # read replica the read-only cursor quietly falls back to the primary,
        # so the bug only appears the day one is added.
        if not self._enabled():
            return self._reply({'ok': False, 'error': 'disabled'}, status=503)
        if self._rate_limited():
            return self._reply({'ok': False, 'error': 'too_many_requests'},
                               status=429)

        try:
            payload = json.loads(request.httprequest.get_data() or b'{}')
        except ValueError:
            return self._reply({'ok': False, 'error': 'bad_json'}, status=400)
        if not isinstance(payload, dict):
            return self._reply({'ok': False, 'error': 'bad_json'}, status=400)

        config = self._config()
        if not config:
            return self._reply({'ok': False, 'error': 'not_configured'},
                               status=503)
        if not config.current_session_id:
            # No open till. Saying so plainly lets the page tell the guest to
            # ring reception instead of silently dropping the order.
            return self._reply({'ok': False, 'error': 'no_open_session'},
                               status=409)

        room = self._clean(payload.get('room'), 20)
        guest = self._clean(payload.get('name'), 60)
        dine_at = self._clean(payload.get('dine_at'), 40)
        note = self._clean(payload.get('note'), MAX_TEXT)
        lang = self._clean(payload.get('lang'), 8)

        if not room or not guest:
            return self._reply({'ok': False, 'error': 'room_and_name_required'},
                               status=400)
        known = request.env['hotel.room'].sudo().search(
            [('name', '=ilike', room)], limit=1)
        if not known:
            return self._reply({'ok': False, 'error': 'unknown_room'},
                               status=400)
        room = known.name           # canonical case, whatever they typed

        raw_lines = payload.get('lines')
        if not isinstance(raw_lines, list) or not raw_lines:
            return self._reply({'ok': False, 'error': 'empty_order'},
                               status=400)
        if len(raw_lines) > MAX_LINES:
            return self._reply({'ok': False, 'error': 'too_many_lines'},
                               status=400)

        wanted = {}
        for entry in raw_lines:
            if not isinstance(entry, dict):
                continue
            try:
                pid, qty = int(entry.get('id')), int(entry.get('qty', 0))
            except (TypeError, ValueError):
                continue
            if qty > 0:
                wanted[pid] = min(qty, MAX_QTY)
        if not wanted:
            return self._reply({'ok': False, 'error': 'empty_order'},
                               status=400)

        # Only things actually on sale, and priced. Browsing the ids straight
        # from the request would let anyone put a raw ingredient -- or the
        # 0 VND buffet -- on the till.
        products = request.env['product.product'].sudo().search([
            ('id', 'in', list(wanted)),
            ('available_in_pos', '=', True),
            ('list_price', '>', 0),
        ])
        if not products:
            return self._reply({'ok': False, 'error': 'no_valid_lines'},
                               status=400)

        company = config.company_id
        currency = config.currency_id
        fpos = config.default_fiscal_position_id

        def line_vals(product, qty):
            """One POS line, priced and taxed on the server.

            Everything about money is computed here from the product record.
            The request body carries product ids and quantities and nothing
            else -- a price sent by the page is never read.

            Written out rather than delegated to `_check_pos_order()` /
            `recompute_prices()` on purpose: those exist on the production
            build of Odoo 19 but NOT on the test server's older point release,
            and a module that can only be exercised on production is a module
            that gets debugged on production.
            """
            taxes = product.taxes_id.filtered(
                lambda t: not t.company_id or t.company_id == company)
            if fpos:
                taxes = fpos.map_tax(taxes)
            price = product.lst_price
            if config.pricelist_id:
                try:
                    price = config.pricelist_id._get_product_price(
                        product, qty) or price
                except Exception:            # noqa: BLE001
                    # Pricelist APIs move between point releases; the product's
                    # own sale price is the right fallback and is what the
                    # /api/lak/menu response quoted to the guest.
                    _logger.warning(
                        "guest order: pricelist lookup failed for %s, using "
                        "the product sale price", product.id)
            taxed = taxes.compute_all(
                price, currency, qty, product=product, partner=None)
            return {
                'product_id': product.id,
                'qty': qty,
                'price_unit': price,
                'price_subtotal': taxed['total_excluded'],
                'price_subtotal_incl': taxed['total_included'],
                'tax_ids': [(6, 0, taxes.ids)],
                'full_product_name': product.display_name,
                'uuid': str(uuid.uuid4()),
            }

        try:
            lines, total_incl, total_excl = [], 0.0, 0.0
            for product in products:
                vals = line_vals(product, wanted[product.id])
                total_incl += vals['price_subtotal_incl']
                total_excl += vals['price_subtotal']
                lines.append([0, 0, vals])

            pos_reference, tracking_number = config._get_next_order_refs()
            label = " · ".join(p for p in (room, guest, dine_at) if p)
            draft = {
                'uuid': str(uuid.uuid4()),
                'company_id': company.id,
                'session_id': config.current_session_id.id,
                'pricelist_id': config.pricelist_id.id or False,
                'fiscal_position_id': fpos.id if fpos else False,
                'pos_reference': pos_reference,
                # "S" is the prefix the built-in self-order uses for a mobile
                # order, so guest orders sort together on the cashier's list.
                'tracking_number': "S%s" % tracking_number,
                'floating_order_name': label[:64],
                'general_customer_note': note,
                'date_order': str(fields.Datetime.now()),
                'amount_total': total_incl,
                'amount_tax': total_incl - total_excl,
                'amount_paid': 0.0,
                'amount_return': 0.0,
                'state': 'draft',
                'source': 'mobile',
                'lines': lines,
            }
            if config.use_presets:
                # Odoo refuses a self-order without one when presets are on.
                draft['preset_id'] = (config.default_preset_id.id
                                      if config.default_preset_id else False)

            # Point releases differ in which of these exist -- `source` arrives
            # with pos_self_order, `preset_id` with presets. Sending a key the
            # build has never heard of makes create() raise, so drop them.
            fields_here = request.env['pos.order']._fields
            draft = {k: v for k, v in draft.items()
                     if k in fields_here or k == 'lines'}

            env = request.env['pos.order'].sudo().with_company(company.id)
            result = env.sync_from_ui([draft])
            created = env.browse(
                [row['id'] for row in result['pos.order'] if row.get('id')])
            if not created:
                raise ValueError("sync_from_ui returned no order")
            created.write({
                'guest_channel': 'lak_guest_page',
                'guest_room': room,
                'guest_name': guest,
                'guest_dine_at': dine_at,
                'guest_lang': lang,
            })
            created._notify_guest_order()
        except Exception:                    # noqa: BLE001
            _logger.exception("guest order from %s failed",
                              request.httprequest.remote_addr)
            return self._reply({'ok': False, 'error': 'server_error'},
                               status=500)

        return self._reply({
            'ok': True,
            'reference': created.tracking_number or created.pos_reference,
            'total': created.amount_total,
            'currency': created.currency_id.name,
        })
