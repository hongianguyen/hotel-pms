# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from datetime import date, timedelta


class HotelDashboard(models.TransientModel):
    _name = 'hotel.dashboard'
    _description = 'Hotel Dashboard KPI Provider'

    @api.model
    def get_reception_kpis(self):
        """Return Reception Dashboard KPIs."""
        today = date.today()
        Reservation = self.env['hotel.reservation']
        Room = self.env['hotel.room']

        total_rooms = Room.search_count([('active', '=', True)])
        occupied_rooms = Room.search_count([('status', '=', 'occupied')])
        dirty_rooms = Room.search_count([('status', '=', 'dirty')])

        today_arrivals = Reservation.search_count([
            ('checkin_date', '=', today),
            ('state', 'in', ['confirmed', 'checked_in']),
        ])
        today_departures = Reservation.search_count([
            ('checkout_date', '=', today),
            ('state', 'in', ['checked_in', 'checked_out']),
        ])

        occupancy_pct = (occupied_rooms / total_rooms * 100) if total_rooms else 0

        # Revenue today from folio lines created today
        today_lines = self.env['hotel.folio.line'].search([
            ('create_date', '>=', fields.Datetime.to_string(
                fields.Datetime.now().replace(hour=0, minute=0, second=0)
            )),
        ])
        revenue_today = sum(today_lines.mapped('subtotal'))

        return {
            'today_arrivals': today_arrivals,
            'today_departures': today_departures,
            'occupancy_pct': round(occupancy_pct, 1),
            'dirty_rooms': dirty_rooms,
            'revenue_today': revenue_today,
            'total_rooms': total_rooms,
            'occupied_rooms': occupied_rooms,
        }

    @api.model
    def get_room_status_board(self):
        """Return all rooms with status for the room board."""
        rooms = self.env['hotel.room'].search([('active', '=', True)], order='floor, name')
        result = []
        for room in rooms:
            folio_id = False
            if room.status == 'occupied':
                active_res = self.env['hotel.reservation'].search([
                    ('room_id', '=', room.id),
                    ('state', '=', 'checked_in'),
                ], limit=1)
                if active_res and active_res.folio_id:
                    folio_id = active_res.folio_id.id
            result.append({
                'id': room.id,
                'name': room.name,
                'room_type': room.room_type_id.name,
                'floor': room.floor,
                'status': room.status,
                'color': room.color,
                'folio_id': folio_id,
            })
        return result

    @api.model
    def get_gantt_data(self, start_date=None, days=15):
        """Return reservation data for the Gantt calendar."""
        if not start_date:
            start_date = date.today()
        elif isinstance(start_date, str):
            start_date = fields.Date.from_string(start_date)

        end_date = start_date + timedelta(days=days)

        rooms = self.env['hotel.room'].search([('active', '=', True)], order='floor, name')
        reservations = self.env['hotel.reservation'].search([
            ('state', 'in', ['confirmed', 'checked_in', 'checked_out']),
            ('checkin_date', '<', end_date),
            ('checkout_date', '>', start_date),
        ])

        room_list = []
        for room in rooms:
            room_list.append({
                'id': room.id,
                'name': room.name,
                'room_type': room.room_type_id.name,
                'floor': room.floor,
                'status': room.status,
            })

        reservation_list = []
        for res in reservations:
            reservation_list.append({
                'id': res.id,
                'reservation_number': res.reservation_number,
                'guest_name': res.guest_id.name,
                'room_id': res.room_id.id,
                'checkin_date': str(res.checkin_date),
                'checkout_date': str(res.checkout_date),
                'state': res.state,
                'total_amount': res.total_amount,
            })

        # Generate date headers
        dates = []
        current = start_date
        while current < end_date:
            dates.append({
                'date': str(current),
                'day': current.day,
                'weekday': current.strftime('%a'),
                'is_today': current == date.today(),
                'is_past': current < date.today(),
                'is_weekend': current.weekday() >= 5,
            })
            current += timedelta(days=1)

        return {
            'rooms': room_list,
            'reservations': reservation_list,
            'dates': dates,
            'start_date': str(start_date),
            'end_date': str(end_date),
        }

    @api.model
    def get_admin_kpis(self):
        """Return Admin Dashboard KPIs (monthly)."""
        today = date.today()
        first_of_month = today.replace(day=1)

        Room = self.env['hotel.room']
        Reservation = self.env['hotel.reservation']
        FolioLine = self.env['hotel.folio.line']

        total_rooms = Room.search_count([('active', '=', True)])
        days_in_month = today.day

        # Monthly reservations
        monthly_reservations = Reservation.search([
            ('state', 'in', ['checked_in', 'checked_out']),
            ('checkin_date', '>=', first_of_month),
            ('checkin_date', '<=', today),
        ])

        total_room_nights = sum(monthly_reservations.mapped('nights'))
        available_room_nights = total_rooms * days_in_month

        occupancy_pct = (total_room_nights / available_room_nights * 100) if available_room_nights else 0

        # Revenue by category this month
        monthly_lines = FolioLine.search([
            ('create_date', '>=', fields.Datetime.to_string(
                fields.Datetime.now().replace(day=1, hour=0, minute=0, second=0)
            )),
        ])

        room_revenue = sum(monthly_lines.filtered(lambda l: l.charge_type == 'room').mapped('subtotal'))
        fnb_revenue = sum(monthly_lines.filtered(lambda l: l.charge_type == 'fnb').mapped('subtotal'))
        service_revenue = sum(monthly_lines.filtered(lambda l: l.charge_type in ('service', 'manual')).mapped('subtotal'))
        total_revenue = room_revenue + fnb_revenue + service_revenue

        occupied_rooms_count = len(monthly_reservations)
        adr = (room_revenue / occupied_rooms_count) if occupied_rooms_count else 0
        revpar = (room_revenue / total_rooms) if total_rooms else 0

        return {
            'monthly_occupancy': round(occupancy_pct, 1),
            'adr': round(adr, 0),
            'revpar': round(revpar, 0),
            'room_revenue': room_revenue,
            'fnb_revenue': fnb_revenue,
            'service_revenue': service_revenue,
            'total_revenue': total_revenue,
        }

    @api.model
    def get_revenue_chart_data(self, days=30):
        """Return daily revenue for the last N days."""
        today = date.today()
        start_date = today - timedelta(days=days - 1)

        FolioLine = self.env['hotel.folio.line']
        data = []
        current = start_date
        while current <= today:
            next_day = current + timedelta(days=1)
            day_lines = FolioLine.search([
                ('create_date', '>=', fields.Datetime.to_string(
                    fields.Datetime.now().replace(
                        year=current.year, month=current.month, day=current.day,
                        hour=0, minute=0, second=0
                    )
                )),
                ('create_date', '<', fields.Datetime.to_string(
                    fields.Datetime.now().replace(
                        year=next_day.year, month=next_day.month, day=next_day.day,
                        hour=0, minute=0, second=0
                    )
                )),
            ])
            data.append({
                'date': str(current),
                'label': current.strftime('%d/%m'),
                'room': sum(day_lines.filtered(lambda l: l.charge_type == 'room').mapped('subtotal')),
                'fnb': sum(day_lines.filtered(lambda l: l.charge_type == 'fnb').mapped('subtotal')),
                'service': sum(day_lines.filtered(lambda l: l.charge_type in ('service', 'manual')).mapped('subtotal')),
            })
            current += timedelta(days=1)

        return data

    @api.model
    def get_occupancy_trend(self, days=30):
        """Return daily occupancy % for the last N days."""
        today = date.today()
        start_date = today - timedelta(days=days - 1)
        Room = self.env['hotel.room']
        Reservation = self.env['hotel.reservation']
        total_rooms = Room.search_count([('active', '=', True)])

        data = []
        current = start_date
        while current <= today:
            occupied = Reservation.search_count([
                ('state', 'in', ['checked_in', 'checked_out']),
                ('checkin_date', '<=', current),
                ('checkout_date', '>', current),
            ])
            pct = (occupied / total_rooms * 100) if total_rooms else 0
            data.append({
                'date': str(current),
                'label': current.strftime('%d/%m'),
                'occupancy': round(pct, 1),
            })
            current += timedelta(days=1)

        return data
