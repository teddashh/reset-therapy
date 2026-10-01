# -*- coding: utf-8 -*-
"""The stats API without Odoo: week math, heal-body parsing, the per-client
heal limit and the SQLite ledger.

controllers/main.py only adapts Odoo requests to handle_stats() and
handle_heal(). Nothing here imports Odoo, so server/tests/ can test it with
plain Python.
"""
import hashlib
import ipaddress
import json
import math
import sqlite3
import time

PROVIDERS = ('claude', 'codex', 'gemini', 'grok')
TZ_OFF = 8 * 3600          # fixed Asia/Taipei week boundary
DB_FILE = 'reset_therapy.sqlite3'
MAX_BODY = 4096            # bytes per heal request body
RATE_LIMIT = 30            # accepted heal requests per client ...
RATE_WINDOW = 60           # ... in any window of this many seconds

SCHEMA = '''
CREATE TABLE IF NOT EXISTS heals (
    provider TEXT NOT NULL,
    week INTEGER NOT NULL,
    n INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (provider, week));
CREATE TABLE IF NOT EXISTS heal_hits (
    client TEXT NOT NULL,
    ts REAL NOT NULL);
CREATE INDEX IF NOT EXISTS heal_hits_client ON heal_hits (client, ts);
CREATE INDEX IF NOT EXISTS heal_hits_ts ON heal_hits (ts);
'''


class BadRequest(ValueError):
    """A heal body we refuse with 400; str() is the message sent back."""


class RateLimited(Exception):
    """Over the heal limit; retry_after is whole seconds until a slot frees."""

    def __init__(self, retry_after):
        super().__init__(retry_after)
        self.retry_after = retry_after


def week_index(ts=None):
    """Monday-start week number at a fixed UTC+8 (epoch day 0 was a Thursday)."""
    day = int(((time.time() if ts is None else ts) + TZ_OFF) // 86400)
    return (day + 3) // 7


def connect(path):
    """Open the ledger in autocommit mode (heal() runs its own transaction)."""
    con = sqlite3.connect(path, timeout=5, isolation_level=None)
    try:
        con.executescript(SCHEMA)
    except Exception:
        con.close()
        raise
    return con


def parse_heal(raw):
    """Turn a heal request body (bytes) into the set of providers to count.

    Raises BadRequest unless the body is at most MAX_BODY bytes of UTF-8 JSON:
    an object whose "providers" is a list of strings naming at least one known
    provider. Unknown names are ignored and duplicates count once, so a single
    request adds at most 1 per provider (4 in total).
    """
    raw = raw or b''
    if len(raw) > MAX_BODY:
        raise BadRequest('too big')
    try:
        body = json.loads(raw.decode('utf-8'))
    except (ValueError, RecursionError):  # bad UTF-8, bad JSON, absurd nesting
        raise BadRequest('bad json') from None
    if not isinstance(body, dict):
        raise BadRequest('body must be a JSON object')
    provs = body.get('providers')
    if not isinstance(provs, list) or not all(isinstance(p, str) for p in provs):
        raise BadRequest('providers must be a list of strings')
    known = set(provs).intersection(PROVIDERS)
    if not known:
        raise BadRequest('no known providers')
    return known


def client_addr(headers, remote_addr=None):
    """The address the heal limit is keyed on.

    Cloudflare's CF-Connecting-IP if present, else the first X-Forwarded-For
    entry, else the connection's own address. IPv6 addresses are grouped per
    /64, the block one client usually holds. The headers are trusted as sent,
    so the server must only be reachable through the proxy.
    """
    h = {str(k).lower(): v for k, v in (headers or {}).items()}
    addr = (h.get('cf-connecting-ip') or '').strip()
    if not addr:
        addr = (h.get('x-forwarded-for') or '').split(',')[0].strip()
    if not addr:
        addr = (remote_addr or '').strip()
    try:
        ip = ipaddress.ip_address(addr)
    except ValueError:
        return addr[:64] or 'unknown'
    if ip.version == 6:
        if ip.ipv4_mapped:
            return str(ip.ipv4_mapped)
        return str(ipaddress.IPv6Network((int(ip), 64), strict=False))
    return str(ip)


def heal(con, client, provs, now=None, limit=RATE_LIMIT, window=RATE_WINDOW):
    """Add 1 this week to each known provider in provs, unless client is over
    the limit (then raise RateLimited and change no counter).

    Sliding window: at most `limit` accepted requests per client in any
    `window` seconds. Refused requests are not stored, rows older than the
    window are deleted on every call, and the file stores a hash of the client
    address rather than the address. It all runs in one BEGIN IMMEDIATE
    transaction, so Odoo workers in separate processes cannot both slip under
    the limit.
    """
    now = time.time() if now is None else now
    key = hashlib.sha256(client.encode('utf-8', 'replace')).hexdigest()[:32]
    con.execute('BEGIN IMMEDIATE')
    try:
        con.execute('DELETE FROM heal_hits WHERE ts <= ?', (now - window,))
        hits = [ts for (ts,) in con.execute(
            'SELECT ts FROM heal_hits WHERE client = ? ORDER BY ts', (key,))]
        wait = 0
        if len(hits) >= limit:
            wait = max(1, math.ceil(hits[len(hits) - limit] + window - now))
        else:
            con.execute('INSERT INTO heal_hits (client, ts) VALUES (?, ?)',
                        (key, now))
            week = week_index(now)
            for prov in sorted(set(provs).intersection(PROVIDERS)):
                con.execute(
                    'INSERT INTO heals (provider, week, n) VALUES (?, ?, 1)'
                    ' ON CONFLICT(provider, week) DO UPDATE SET n = n + 1',
                    (prov, week))
        con.execute('COMMIT')
    except BaseException:
        if con.in_transaction:
            con.execute('ROLLBACK')
        raise
    if wait:
        raise RateLimited(wait)


def stats(con, now=None):
    """The JSON payload both endpoints return."""
    wk = week_index(now)
    week = dict.fromkeys(PROVIDERS, 0)
    total = dict.fromkeys(PROVIDERS, 0)
    for prov, w, n in con.execute('SELECT provider, week, n FROM heals'):
        if prov in total:
            total[prov] += n
            if w == wk:
                week[prov] += n
    return {'weekIdx': wk, 'week': week, 'all': total}


def handle_stats(path, now=None):
    """GET /reset-therapy/api/stats -> (status, payload, extra headers)."""
    con = connect(path)
    try:
        return 200, stats(con, now), []
    finally:
        con.close()


def handle_heal(path, content_length, read_body, headers, remote_addr,
                now=None):
    """POST /reset-therapy/api/heal -> (status, payload, extra headers).

    read_body() is only called once the declared Content-Length fits, so an
    oversized upload is refused without reading it.
    """
    try:
        if (content_length or 0) > MAX_BODY:
            raise BadRequest('too big')
        provs = parse_heal(read_body())
    except BadRequest as exc:
        return 400, {'error': str(exc)}, []
    now = time.time() if now is None else now
    con = connect(path)
    try:
        heal(con, client_addr(headers, remote_addr), provs, now)
        return 200, stats(con, now), []
    except RateLimited as exc:
        return (429, {'error': 'rate limited'},
                [('Retry-After', str(exc.retry_after))])
    finally:
        con.close()
