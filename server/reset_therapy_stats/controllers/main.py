# -*- coding: utf-8 -*-
import json
import os

from odoo import http
from odoo.tools import config

from .. import core


def _db():
    return os.path.join(config['data_dir'], core.DB_FILE)


def _resp(result):
    status, data, headers = result
    return http.request.make_response(
        json.dumps(data), status=status,
        headers=[('Content-Type', 'application/json'),
                 ('Cache-Control', 'no-store')] + headers)


class ResetTherapyStats(http.Controller):
    """Thin Odoo wrapper; the logic (and its tests) lives in core.py."""

    @http.route('/reset-therapy/api/stats', type='http', auth='public',
                methods=['GET'], csrf=False, save_session=False)
    def rt_stats(self, **kw):
        return _resp(core.handle_stats(_db()))

    @http.route('/reset-therapy/api/heal', type='http', auth='public',
                methods=['POST'], csrf=False, save_session=False)
    def rt_heal(self, **kw):
        req = http.request.httprequest
        return _resp(core.handle_heal(
            _db(), req.content_length, req.get_data, req.headers,
            req.remote_addr))
