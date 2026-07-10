# -*- coding: utf-8 -*-
"""Backfill hotel.folio.line.date for pre-existing rows.

The new required `date` field defaults to the upgrade day on existing
rows; overwrite it with the line's create_date (as a date) so historical
revenue reports stay truthful. Room-charge lines whose description embeds
the night (dd/mm/YYYY) are parsed for the exact night instead.
"""
import re

DATE_RE = re.compile(r'(\d{2})/(\d{2})/(\d{4})')


def migrate(cr, version):
    if not version:
        return
    # Default pass: business date = creation date
    cr.execute("""
        UPDATE hotel_folio_line
        SET date = create_date::date
        WHERE date IS NOT NULL
    """)
    # Refinement: room charges carry the night in the label 'Room X — dd/mm/YYYY'
    cr.execute("""
        SELECT id, name FROM hotel_folio_line
        WHERE charge_type = 'room' AND name IS NOT NULL
    """)
    for line_id, name in cr.fetchall():
        m = DATE_RE.search(name or '')
        if m:
            dd, mm, yyyy = m.groups()
            cr.execute(
                "UPDATE hotel_folio_line SET date = %s WHERE id = %s",
                (f"{yyyy}-{mm}-{dd}", line_id),
            )
