# -*- coding: utf-8 -*-
import json
import os
import sqlite3
import time

from odoo import http
from odoo.tools import config

PROVIDERS = ('claude', 'codex', 'gemini', 'grok')
TZ_OFF = 8 * 3600          # fixed Asia/Taipei week boundary
DB_FILE = 'reset_therapy.sqlite3'


def _week(ts=None):
    # Monday-start week index in UTC+8 (epoch day 0 = Thursday, so +3)
    day = int(((ts if ts is not None else time.time()) + TZ_OFF) // 86400)
    return (day + 3) // 7


def _con():
    con = sqlite3.connect(os.path.join(config['data_dir'], DB_FILE), timeout=5)
    con.execute(
        'CREATE TABLE IF NOT EXISTS heals ('
        ' provider TEXT NOT NULL,'
        ' week INTEGER NOT NULL,'
        ' n INTEGER NOT NULL DEFAULT 0,'
        ' PRIMARY KEY (provider, week))')
    return con


def _payload(con):
    wk = _week()
    week = dict.fromkeys(PROVIDERS, 0)
    total = dict.fromkeys(PROVIDERS, 0)
    for prov, w, n in con.execute('SELECT provider, week, n FROM heals'):
        if prov in total:
            total[prov] += n
            if w == wk:
                week[prov] += n
    return {'weekIdx': wk, 'week': week, 'all': total}


def _resp(data, status=200):
    return http.request.make_response(
        json.dumps(data), status=status,
        headers=[('Content-Type', 'application/json'),
                 ('Cache-Control', 'no-store')])


class ResetTherapyStats(http.Controller):

    @http.route('/reset-therapy/api/stats', type='http', auth='public',
                methods=['GET'], csrf=False, save_session=False)
    def rt_stats(self, **kw):
        con = _con()
        try:
            return _resp(_payload(con))
        finally:
            con.close()

    @http.route('/reset-therapy/api/heal', type='http', auth='public',
                methods=['POST'], csrf=False, save_session=False)
    def rt_heal(self, **kw):
        raw = http.request.httprequest.get_data(as_text=True) or '{}'
        if len(raw) > 4096:
            return _resp({'error': 'too big'}, 400)
        try:
            body = json.loads(raw)
        except ValueError:
            return _resp({'error': 'bad json'}, 400)
        provs = body.get('providers')
        if not isinstance(provs, list):
            return _resp({'error': 'providers must be a list'}, 400)
        provs = {p for p in provs if p in PROVIDERS}
        if not provs:
            return _resp({'error': 'no known providers'}, 400)
        wk = _week()
        con = _con()
        try:
            with con:
                for p in provs:
                    con.execute(
                        'INSERT INTO heals (provider, week, n) VALUES (?, ?, 1)'
                        ' ON CONFLICT(provider, week) DO UPDATE SET n = n + 1',
                        (p, wk))
            return _resp(_payload(con))
        finally:
            con.close()
