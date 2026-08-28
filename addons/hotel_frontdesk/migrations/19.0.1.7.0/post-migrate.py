# -*- coding: utf-8 -*-
"""Repair the pre-arrival reminder template and backfill folio line owners.

Two one-time data fixes for already-installed databases.

1. `mail_template_prearrival_reminder` was missing `use_default_to=False`,
   so Odoo 19 ignored its `email_to` and looked for a partner field that
   hotel.reservation does not have — the daily cron rendered empty
   recipients and delivered nothing while still counting each guest as
   sent. The XML now sets the flag, but every mail template in this module
   lives in a `noupdate="1"` block (deliberately: the owner edits email
   wording in the UI and upgrades must not revert it), so the corrected
   XML never reaches an existing record. Fix it here instead.

2. Room-charge lines predate `hotel.folio.line.reservation_id`. The
   check-in amendment resync uses that field to know which lines are its
   own on a shared group folio, so backfill it where the folio has exactly
   one reservation and the attribution is therefore unambiguous.
"""


def migrate(cr, version):
    if not version:
        return

    # 1. Pre-arrival template: honour email_to again.
    cr.execute("""
        UPDATE mail_template mt
        SET use_default_to = false
        FROM ir_model_data d
        WHERE d.model = 'mail.template'
          AND d.module = 'hotel_frontdesk'
          AND d.name = 'mail_template_prearrival_reminder'
          AND mt.id = d.res_id
          AND mt.use_default_to IS DISTINCT FROM false
    """)

    # 2. Attribute existing room charges to their reservation, but only
    #    where the folio has a single reservation — on a group master
    #    folio the line could belong to any of its children, and guessing
    #    is worse than leaving it null (the resync falls back to matching
    #    on the room name for those).
    cr.execute("""
        UPDATE hotel_folio_line l
        SET reservation_id = f.reservation_id
        FROM hotel_folio f
        WHERE l.folio_id = f.id
          AND l.reservation_id IS NULL
          AND l.charge_type = 'room'
          AND f.reservation_id IS NOT NULL
          AND (SELECT count(*) FROM hotel_reservation r
               WHERE r.folio_id = f.id) = 1
    """)
