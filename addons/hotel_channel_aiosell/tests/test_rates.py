# -*- coding: utf-8 -*-
from datetime import timedelta

from unittest.mock import patch

from odoo import fields
from odoo.tests import tagged

from .common import AiosellCase


@tagged('post_install', '-at_install')
class TestRates(AiosellCase):
    """A rate that does not apply must be absent, never zero."""

    def test_rate_uses_the_plan_price(self):
        blocks = self.config._build_rate_updates(
            self.today, self.today + timedelta(days=2))
        self.assertEqual(len(blocks), 1)
        self.assertEqual(blocks[0]['rates'], [{
            'roomCode': 'bungalow',
            'rateplanCode': 'bungalow-d-ep',
            'rate': 1500000.0,
        }])

    def test_stop_sell_removes_the_rate_instead_of_zeroing_it(self):
        """A 0 pushed to an OTA is a free room, not a closed one."""
        self.plan.stop_sell = True
        blocks = self.config._build_rate_updates(
            self.today, self.today + timedelta(days=2))
        self.assertEqual(blocks, [], 'A closed plan publishes no rate at all.')

    def test_out_of_season_dates_are_skipped(self):
        self.plan.write({
            'date_from': self.today + timedelta(days=2),
            'date_to': self.today + timedelta(days=4),
        })
        blocks = self.config._build_rate_updates(
            self.today, self.today + timedelta(days=5))
        self.assertEqual(len(blocks), 1)
        self.assertEqual(blocks[0]['startDate'], str(self.today + timedelta(days=2)))
        self.assertEqual(blocks[0]['endDate'], str(self.today + timedelta(days=4)))

    def test_excluded_weekday_is_skipped(self):
        weekday = self.today.weekday()
        field = ['day_monday', 'day_tuesday', 'day_wednesday', 'day_thursday',
                 'day_friday', 'day_saturday', 'day_sunday'][weekday]
        self.plan.write({field: False})
        blocks = self.config._build_rate_updates(
            self.today, self.today + timedelta(days=1))
        self.assertEqual(blocks, [])

    def test_plan_without_own_rate_falls_back_to_the_room_type(self):
        self.plan.write({'base_rate': 0.0, 'room_type_id': False})
        blocks = self.config._build_rate_updates(
            self.today, self.today + timedelta(days=1))
        self.assertEqual(blocks[0]['rates'][0]['rate'], 1200000.0)

    def test_unmapped_rate_plan_is_not_pushed(self):
        self.map_rate.rate_plan_id = False
        self.assertEqual(
            self.config._build_rate_updates(
                self.today, self.today + timedelta(days=1)), [])

    def test_pushing_no_rates_at_all_is_flagged(self):
        """Availability flowing while rates silently do not is worse than an
        error: the OTAs keep selling at whatever price they last heard."""
        self.map_rate.rate_plan_id = False
        self.config.write({'sync_availability': False, 'sync_rates': True})
        with patch.object(
                type(self.config), '_call', return_value={'success': True}):
            self.config._push_ari()
        log = self.env['aiosell.sync.log'].search([
            ('config_id', '=', self.config.id), ('state', '=', 'refused'),
        ], limit=1)
        self.assertTrue(log, 'The empty rate push must leave a trace.')
        self.assertIn('no rate plan mapping', log.note)

    def test_restrictions_close_the_room_when_every_plan_is_closed(self):
        self.config.sync_restrictions = True
        self.plan.stop_sell = True
        blocks = self.config._build_restriction_updates(
            self.today, self.today + timedelta(days=1))
        restrictions = blocks[0]['rooms'][0]['restrictions']
        self.assertTrue(restrictions['stopSell'])

    def test_restrictions_carry_the_minimum_stay(self):
        self.config.sync_restrictions = True
        self.plan.min_stay = 3
        blocks = self.config._build_restriction_updates(
            self.today, self.today + timedelta(days=1))
        restrictions = blocks[0]['rooms'][0]['restrictions']
        self.assertFalse(restrictions['stopSell'])
        self.assertEqual(restrictions['minimumStay'], 3)

    def _weekday_split(self):
        """Main plan Sun-Thu at the plan price, an extra Fri-Sat plan dearer."""
        days = ['day_monday', 'day_tuesday', 'day_wednesday', 'day_thursday',
                'day_friday', 'day_saturday', 'day_sunday']
        self.plan.write({'day_friday': False, 'day_saturday': False})
        weekend = self.env['hotel.rate.plan'].create({
            'name': 'AIO Weekend',
            'room_type_id': self.plan.room_type_id.id,
            'base_rate': 1800000.0,
            **{d: d in ('day_friday', 'day_saturday') for d in days},
        })
        self.map_rate.extra_rate_plan_ids = weekend
        return weekend

    def _next(self, weekday):
        return self.today + timedelta(days=(weekday - self.today.weekday()) % 7)

    def test_other_day_plan_prices_the_nights_the_main_plan_skips(self):
        self._weekday_split()
        thu, fri, sun = self._next(3), self._next(4), self._next(6)
        rates = {}
        for block in self.config._build_rate_updates(self.today, self.today + timedelta(days=7)):
            day = block['startDate']
            while day <= block['endDate']:
                rates[day] = block['rates'][0]['rate']
                day = str(fields.Date.from_string(day) + timedelta(days=1))
        self.assertEqual(rates[str(thu)], 1500000.0)
        self.assertEqual(rates[str(fri)], 1800000.0)
        self.assertEqual(rates[str(sun)], 1500000.0)

    def test_other_day_plan_keeps_the_weekend_open(self):
        """Without it the Sun-Thu plan alone would stop-sell Fri and Sat."""
        weekend = self._weekday_split()
        weekend.min_stay = 2
        self.config.sync_restrictions = True
        fri = self._next(4)
        blocks = self.config._build_restriction_updates(fri, fri + timedelta(days=1))
        restrictions = blocks[0]['rooms'][0]['restrictions']
        self.assertFalse(restrictions['stopSell'])
        self.assertEqual(restrictions['minimumStay'], 2)
