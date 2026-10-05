# -*- coding: utf-8 -*-
"""Packages that existed before per-guest pricing keep pricing as they did.

New packages default to Per guest; the column was filled with that default
when it was created, so every package found here predates it and goes back
to Fixed: its flat accommodation rate plus the listed service prices.
"""


def migrate(cr, version):
    if not version:
        return
    cr.execute("UPDATE hotel_combo SET pricing = 'fixed'")
