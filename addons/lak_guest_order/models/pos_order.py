# -*- coding: utf-8 -*-
"""Guest-page fields on the POS order, and the manager alert."""
import logging
from html import escape

from odoo import _, api, fields, models

_logger = logging.getLogger(__name__)

GUEST_SOURCE = 'lak_guest_page'


class PosOrder(models.Model):
    _inherit = 'pos.order'

    # Structured copies of what the guest typed. The same three values also go
    # into `floating_order_name`, which is the string the cashier actually
    # sees in the POS order list -- these exist so reception can filter and
    # report on them, and so the room survives a rename of that label.
    guest_channel = fields.Char(
        string="Guest channel", readonly=True, copy=False,
        index='btree_not_null',
        help="'lak_guest_page' on orders placed from the public guest page.")
    guest_room = fields.Char(
        string="Room (unverified)", readonly=True, copy=False,
        help="Room code the guest typed on the page. The page cannot prove "
             "who is typing, so this is a claim. Check it against who is "
             "actually in that room before charging the folio.")
    guest_name = fields.Char(string="Guest name", readonly=True, copy=False)
    guest_dine_at = fields.Char(
        string="Dine in at", readonly=True, copy=False,
        help="When the guest asked to eat, as they entered it.")
    guest_lang = fields.Char(
        string="Guest language", readonly=True, copy=False,
        help="Language the page was in -- useful when calling the room back.")

    def _guest_alert_body(self):
        self.ensure_one()
        lines = "\n".join(
            "  %-3d x %s" % (line.qty, line.full_product_name
                             or line.product_id.display_name)
            for line in self.lines
        )
        return _(
            "New guest order %(ref)s\n\n"
            "Room:     %(room)s   (typed by the guest, NOT verified)\n"
            "Name:     %(name)s\n"
            "Dine in:  %(when)s\n"
            "Total:    %(total)s\n\n"
            "%(lines)s\n"
            "%(note)s\n\n"
            "It is sitting unpaid on the till. Open the POS, pick it from the "
            "order list, fire the kitchen and take payment.",
            ref=self.tracking_number or self.pos_reference or self.name,
            room=self.guest_room or '-', name=self.guest_name or '-',
            when=self.guest_dine_at or '-',
            total="{:,.0f} {}".format(self.amount_total, self.currency_id.name),
            lines=lines,
            note=("\nNote: %s" % self.general_customer_note)
                 if self.general_customer_note else "",
        )

    def _notify_guest_order(self):
        """Tell the manager. Never raises.

        A notification that fails must not roll back the order -- the guest
        has already been told it was received, and the order is on the till.
        """
        icp = self.env['ir.config_parameter'].sudo()
        recipients = (icp.get_param('lak_guest_order.manager_email') or '').strip()
        # Every outgoing server on this database is Outlook SMTP with a
        # from_filter (giang@ / sales@ / res@laktentedcamp.com). Outlook
        # refuses to send as an address the account does not own, and Odoo
        # picks the server by matching this From against those filters -- so
        # sending with the wrong From is a silent 550, not a bounce anyone
        # reads. Set the parameter to one of those three addresses.
        sender = (icp.get_param('lak_guest_order.from_email') or '').strip()
        # ...and pin the server that owns that address. Odoo groups the
        # outgoing queue by mail_server_id and opens ONE session per group;
        # for mails that name no server it uses the default (lowest sequence,
        # then lowest id) and never consults from_filter. On this database
        # that is the giang@ account, so a mail merely saying From: res@ is
        # sent over giang@'s session and Outlook answers
        #   554 5.2.252 SendAsDenied; giang@... not allowed to send as res@...
        # Verified on production 04 Sep 2026, mail_mail 134.
        server = self.env['ir.mail_server'].sudo().search(
            [('from_filter', '=ilike', sender)], limit=1) if sender else False
        for order in self:
            body = order._guest_alert_body()
            if recipients:
                try:
                    self.env['mail.mail'].sudo().create({
                        'subject': _("Guest order - room %s",
                                     order.guest_room or '?'),
                        'body_html': '<pre>%s</pre>' % escape(body),
                        'email_to': recipients,
                        'auto_delete': False,
                        **({'email_from': sender} if sender else {}),
                        **({'mail_server_id': server.id} if server else {}),
                    }).send()
                except Exception:            # noqa: BLE001 -- see docstring
                    _logger.exception(
                        "guest order %s: manager email failed", order.id)
            order._notify_guest_order_telegram(body)

    def _notify_guest_order_telegram(self, body):
        """Optional second channel. No-op unless both parameters are set."""
        icp = self.env['ir.config_parameter'].sudo()
        token = (icp.get_param('lak_guest_order.telegram_bot_token') or '').strip()
        chat_id = (icp.get_param('lak_guest_order.telegram_chat_id') or '').strip()
        if not (token and chat_id):
            return
        try:
            import requests
            requests.post(
                'https://api.telegram.org/bot%s/sendMessage' % token,
                json={'chat_id': chat_id, 'text': body},
                # Short: this runs inside the guest's request, and a hanging
                # Telegram must not hold the page's spinner open.
                timeout=8,
            )
        except Exception:                    # noqa: BLE001
            _logger.exception("guest order: Telegram alert failed")
