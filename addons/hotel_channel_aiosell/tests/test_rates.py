# -*- coding: utf-8 -*-
from datetime import timedelta

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
