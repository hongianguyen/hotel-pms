# -*- coding: utf-8 -*-
import logging
from datetime import timedelta

from odoo import api, fields, models

_logger = logging.getLogger(__name__)


class ChannelSyncLog(models.Model):
    _name = 'channel.sync.log'
    _description = 'Channel Sync Log'
    _order = 'create_date desc'

    config_id = fields.Many2one(
        'channel.manager.config', required=True, ondelete='cascade',
        string='Channel',
    )
    provider_code = fields.Selection(
        related='config_id.provider_code', store=True, readonly=True,
    )
    direction = fields.Selection(
        [('inbound', 'Inbound'), ('outbound', 'Outbound')],
        required=True,
    )
    sync_type = fields.Selection(
        [
            ('availability', 'Availability'),
            ('rate', 'Rate'),
            ('restriction', 'Restriction'),
            ('booking', 'Booking'),
            ('cancellation', 'Cancellation'),
        ],
        required=True,
    )
    state = fields.Selection(
        [
            ('pending', 'Pending'),
            ('processing', 'Processing'),
            ('success', 'Success'),
            ('error', 'Error'),
            ('retrying', 'Retrying'),
        ],
        default='pending',
        required=True,
        index=True,
    )

    request_payload = fields.Text()
    response_payload = fields.Text()
    error_message = fields.Text()

    reservation_id = fields.Many2one('hotel.reservation', ondelete='set null')
    room_type_id = fields.Many2one('hotel.room.type', ondelete='set null')

    retry_count = fields.Integer(default=0)
    max_retries = fields.Integer(default=3)
    next_retry = fields.Datetime()

    @api.model_create_multi
    def create(self, vals_list):
        return super().create(vals_list)

    def action_retry_now(self):
        """Manually retry a failed sync log entry."""
        for log in self.filtered(lambda l: l.state in ('error', 'retrying')):
            log.write({
                'state': 'pending',
                'retry_count': 0,
                'next_retry': False,
                'error_message': False,
            })

    # -------------------------------------------------------------------------
    # Cron: Process pending outbound sync queue
    # -------------------------------------------------------------------------
    @api.model
    def _cron_process_sync_queue(self):
        """Process pending outbound sync log entries."""
        pending = self.search([
            ('state', '=', 'pending'),
            ('direction', '=', 'outbound'),
        ], order='create_date asc', limit=100)

        for log in pending:
            try:
                log.state = 'processing'
                self.env.cr.commit()
                self._process_outbound_log(log)
                log.write({'state': 'success'})
                log.config_id.last_sync_date = fields.Datetime.now()
            except Exception as e:
                _logger.exception(
                    'Channel sync failed for log %s: %s', log.id, e,
                )
                log.write({
                    'state': 'error',
                    'error_message': str(e)[:2000],
                })
            finally:
                self.env.cr.commit()

    def _process_outbound_log(self, log):
        """Dispatch a single outbound log to its provider."""
        provider = log.config_id._get_provider()
        if log.sync_type == 'availability':
            data = self._build_availability_data(log)
            result = provider.push_availability(data)
        elif log.sync_type == 'rate':
            data = self._build_rate_data(log)
            result = provider.push_rates(data)
        elif log.sync_type == 'restriction':
            data = self._build_restriction_data(log)
            result = provider.push_restrictions(data)
        elif log.sync_type == 'cancellation':
            result = provider.push_cancellation(
                log.reservation_id.channel_booking_id,
            )
        else:
            return
        log.response_payload = str(result)[:5000] if result else ''

    def _build_availability_data(self, log):
        """Build availability payload for a room type."""
        room_type = log.room_type_id
        config = log.config_id
        if not room_type:
            return {}
        mapping = self.env['channel.room.type.mapping'].search([
            ('config_id', '=', config.id),
            ('room_type_id', '=', room_type.id),
        ], limit=1)
        if not mapping:
            return {}

        today = fields.Date.today()
        date_to = today + timedelta(days=365)
        result = {}
        current = today
        Room = self.env['hotel.room']
        while current <= date_to:
            next_day = current + timedelta(days=1)
            available = Room.get_available_rooms(current, next_day, room_type.id)
            count = len(available)
            if mapping.max_allotment and count > mapping.max_allotment:
                count = mapping.max_allotment
            result[str(current)] = count
            current = next_day

        return {mapping.channel_room_type_id: result}

    def _build_rate_data(self, log):
        """Build rate payload for a room type."""
        config = log.config_id
        rate_mappings = self.env['channel.rate.plan.mapping'].search([
            ('config_id', '=', config.id),
        ])
        if not rate_mappings:
            return {}

        today = fields.Date.today()
        date_to = today + timedelta(days=365)
        result = {}
        for rm in rate_mappings:
            rate_plan = rm.rate_plan_id
            room_type = rate_plan.room_type_id
            if not room_type:
                continue
            room_mapping = self.env['channel.room.type.mapping'].search([
                ('config_id', '=', config.id),
                ('room_type_id', '=', room_type.id),
            ], limit=1)
            if not room_mapping:
                continue

            rates = {}
            current = today
            while current <= date_to:
                rate = rate_plan.get_rate_for_date(current)
                if rate:
                    rates[str(current)] = rate
                current += timedelta(days=1)

            result.setdefault(rm.channel_rate_plan_id, {})[
                room_mapping.channel_room_type_id
            ] = rates

        return result

    def _build_restriction_data(self, log):
        """Build restriction payload."""
        config = log.config_id
        rate_mappings = self.env['channel.rate.plan.mapping'].search([
            ('config_id', '=', config.id),
        ])
        if not rate_mappings:
            return {}

        today = fields.Date.today()
        date_to = today + timedelta(days=365)
        result = {}
        for rm in rate_mappings:
            rate_plan = rm.rate_plan_id
            restrictions = {}
            current = today
            while current <= date_to:
                restrictions[str(current)] = {
                    'min_stay': rate_plan.min_stay,
                    'stop_sell': rate_plan.stop_sell,
                }
                current += timedelta(days=1)
            result[rm.channel_rate_plan_id] = restrictions

        return result

    # -------------------------------------------------------------------------
    # Cron: Full reconciliation sync
    # -------------------------------------------------------------------------
    @api.model
    def _cron_full_sync(self):
        """Push complete availability and rates to all active channels."""
        configs = self.env['channel.manager.config'].search([
            ('active', '=', True),
        ])
        for config in configs:
            if config.sync_availability:
                for mapping in config.room_mapping_ids:
                    self.create({
                        'config_id': config.id,
                        'direction': 'outbound',
                        'sync_type': 'availability',
                        'room_type_id': mapping.room_type_id.id,
                        'state': 'pending',
                    })
            if config.sync_rates:
                for mapping in config.rate_mapping_ids:
                    self.create({
                        'config_id': config.id,
                        'direction': 'outbound',
                        'sync_type': 'rate',
                        'room_type_id': mapping.rate_plan_id.room_type_id.id
                        if mapping.rate_plan_id.room_type_id else False,
                        'state': 'pending',
                    })
            if config.sync_restrictions:
                self.create({
                    'config_id': config.id,
                    'direction': 'outbound',
                    'sync_type': 'restriction',
                    'state': 'pending',
                })

    # -------------------------------------------------------------------------
    # Cron: Retry failed syncs with exponential backoff
    # -------------------------------------------------------------------------
    @api.model
    def _cron_retry_failed(self):
        """Retry failed outbound syncs with exponential backoff."""
        now = fields.Datetime.now()
        retryable = self.search([
            ('state', 'in', ('error', 'retrying')),
            ('direction', '=', 'outbound'),
            ('retry_count', '<', 3),
            '|',
            ('next_retry', '=', False),
            ('next_retry', '<=', now),
        ], limit=50)

        for log in retryable:
            # Exponential backoff: 5^(retry_count+1) minutes
            backoff_minutes = 5 ** (log.retry_count + 1)
            try:
                log.write({
                    'state': 'processing',
                    'retry_count': log.retry_count + 1,
                })
                self.env.cr.commit()
                self._process_outbound_log(log)
                log.write({'state': 'success', 'error_message': False})
                log.config_id.last_sync_date = fields.Datetime.now()
            except Exception as e:
                _logger.exception(
                    'Retry failed for sync log %s (attempt %s): %s',
                    log.id, log.retry_count, e,
                )
                new_state = 'error' if log.retry_count >= 3 else 'retrying'
                log.write({
                    'state': new_state,
                    'error_message': str(e)[:2000],
                    'next_retry': now + timedelta(minutes=backoff_minutes),
                })
            finally:
                self.env.cr.commit()
