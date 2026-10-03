# -*- coding: utf-8 -*-
from odoo import fields, models


class HotelRoomType(models.Model):
    _inherit = 'hotel.room.type'

    # Opt-out rather than opt-in: every physical type the camp has today is
    # sold to the public, and the engine is behind its own enabled flag. ROH
    # types are never sold online regardless (see booking_quote).
    website_bookable = fields.Boolean(
        'Bookable on Website', default=True,
        help='Offer this room type on the camp website\'s booking engine. '
             'Run-of-House types are never offered.',
    )

    # What the booking page shows. Kept apart from `description`, which is
    # reception's own short note and appears on internal screens.
    web_summary = fields.Char(
        'Website Summary', translate=True,
        help='One line under the room name on the booking page.')
    web_description = fields.Html(
        'Website Description', translate=True, sanitize=True,
        help='The full description guests read on the booking page.')
    web_facilities = fields.Text(
        'Facilities', translate=True,
        help='One facility per line, shown as a list on the booking page.')
    web_beds = fields.Char('Beds', translate=True)
    web_size = fields.Char('Size', translate=True, help='e.g. 32 m² incl. balcony')
    web_view = fields.Char('View', translate=True)
    web_image_ids = fields.One2many(
        'lak.room.type.image', 'room_type_id', string='Website Photos')

    def web_content(self):
        """The booking page's view of this room type."""
        self.ensure_one()
        facilities = [line.strip(' -•\t') for line in (self.web_facilities or '').splitlines()]
        return {
            'summary': self.web_summary or self.description or '',
            'description_html': str(self.web_description or ''),
            'facilities': [f for f in facilities if f],
            'beds': self.web_beds or '',
            'size': self.web_size or '',
            'view': self.web_view or '',
            'photos': [image.public_urls() for image in self.web_image_ids],
        }


class LakRoomTypeImage(models.Model):
    _name = 'lak.room.type.image'
    _description = 'Room Type Website Photo'
    _inherit = ['image.mixin']
    _order = 'sequence, id'

    name = fields.Char('Caption', translate=True)
    sequence = fields.Integer(default=10)
    room_type_id = fields.Many2one(
        'hotel.room.type', required=True, ondelete='cascade', index=True)

    def public_urls(self):
        self.ensure_one()
        # The write date busts browser and Cloudflare caches when a photo is
        # replaced, so the image route can be cached for a long time.
        unique = int(self.write_date.timestamp()) if self.write_date else 0
        base = '/api/book/photo/%d' % self.id
        return {
            'url': '%s/1920?u=%d' % (base, unique),
            'medium': '%s/1024?u=%d' % (base, unique),
            'thumb': '%s/512?u=%d' % (base, unique),
            'caption': self.name or '',
        }
