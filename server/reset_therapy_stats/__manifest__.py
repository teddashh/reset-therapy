# -*- coding: utf-8 -*-
{
    "name": "Reset Therapy Stats",
    "summary": "Public JSON API backing the /reset-therapy page "
               "(global heal counters in a tiny sqlite ledger).",
    "description": """
Two public endpoints for the Reset Therapy page so every visitor sees the same
global numbers (the fake-but-alive baseline stays client-side; this only adds
the real heal counts on top):

  GET  /reset-therapy/api/stats  -> {"weekIdx": N, "week": {...}, "all": {...}}
  POST /reset-therapy/api/heal   {"providers": ["claude", ...]} -> fresh stats

Storage is a sqlite file in the Odoo data_dir volume (reset_therapy.sqlite3),
one row per (provider, week). Week = Monday-start, Asia/Taipei fixed offset.
No ORM models, no stored Odoo state; uninstalling leaves only the sqlite file.
""",
    "version": "19.0.1.0.0",
    "author": "Ted Huang",
    "website": "https://ted-h.com",
    "license": "LGPL-3",
    "category": "Website",
    "depends": ["web"],
    "data": [],
    "installable": True,
    "application": False,
}
