# -*- coding: utf-8 -*-
import hashlib
import hmac
import secrets
import logging

from odoo import api, fields, models

_logger = logging.getLogger(__name__)


class ChannelManagerConfig(models.Model):
    _name = 'channel.manager.config'
    _description = 'Channel Manager Configuration'
    _inherit = ['mail.thread', 'mail.activity.mixin']

    name = fields.Char(required=True, tracking=True)
    provider_code = fields.Selection(
        selection=[
            ('booking_com', 'Booking.com'),
            ('agoda', 'Agoda'),
        ],
        required=True,
        tracking=True,
    )
    active = fields.Boolean(default=True)
    company_id = fields.Many2one(
        'res.company', default=lambda self: self.env.company, required=True,
    )

    # API credentials (admin-only via view groups)
    api_url = fields.Char(string='API URL')
    api_key = fields.Char(string='API Key')
    api_secret = fields.Char(string='API Secret')
    property_id = fields.Char(string='Property ID')
    webhook_secret = fields.Char(
        string='Webhook Secret', readonly=True, copy=False,
    )

    # Sync toggles
    sync_availability = fields.Boolean(default=True, string='Sync Availability')
    sync_rates = fields.Boolean(default=True, string='Sync Rates')
    sync_restrictions = fields.Boolean(default=False, string='Sync Restrictions')
    auto_confirm_bookings = fields.Boolean(
        default=True,
        string='Auto-Confirm Inbound Bookings',
        help='Automatically confirm reservations received from this channel.',
    )

    # Links
    booking_source_id = fields.Many2one(
        'hotel.booking.source',
        string='Booking Source',
        help='Auto-set on inbound reservations from this channel.',
    )
    room_mapping_ids = fields.One2many(
        'channel.room.type.mapping', 'config_id', string='Room Type Mappings',
    )
    rate_mapping_ids = fields.One2many(
        'channel.rate.plan.mapping', 'config_id', string='Rate Plan Mappings',
    )
    sync_log_ids = fields.One2many(
        'channel.sync.log', 'config_id', string='Sync Logs',
    )
    last_sync_date = fields.Datetime(string='Last Sync', readonly=True)

    _provider_code_company_uniq = models.Constraint(
        'UNIQUE(provider_code, company_id)',
        'Only one configuration per channel per company is allowed!',
    )

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get('webhook_secret'):
                vals['webhook_secret'] = secrets.token_hex(32)
        return super().create(vals_list)

    def action_test_connection(self):
        """Test the API connection for this channel."""
        self.ensure_one()
        from ..providers.base_provider import get_provider
        provider = get_provider(self.provider_code, self)
        success, message = provider.test_connection()
        if success:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'Connection Successful',
                    'message': message,
                    'type': 'success',
                    'sticky': False,
                },
            }
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Connection Failed',
                'message': message,
                'type': 'danger',
                'sticky': True,
            },
        }

    def action_full_sync(self):
        """Open force sync wizard."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Force Full Sync',
            'res_model': 'channel.force.sync.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_config_id': self.id},
        }

    def _get_provider(self):
        """Return the provider adapter instance for this config."""
        self.ensure_one()
        from ..providers.base_provider import get_provider
        return get_provider(self.provider_code, self)

    def verify_webhook_signature(self, payload_bytes, signature):
        """Verify HMAC-SHA256 signature on inbound webhook."""
        self.ensure_one()
        if not self.webhook_secret:
            return False
        expected = hmac.new(
            self.webhook_secret.encode(),
            payload_bytes,
            hashlib.sha256,
        ).hexdigest()
        return hmac.compare_digest(expected, signature or '')
