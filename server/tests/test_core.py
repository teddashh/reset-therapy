# -*- coding: utf-8 -*-
"""Unit tests for reset_therapy_stats/core.py: heal-body parsing, the client
key, the per-client heal limit and the UTC+8 weeks. Plain Python, no Odoo:

    python3 -m unittest discover -s server/tests -v
"""
import contextlib
import datetime
import importlib.util
import json
import os
import random
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import unittest

CORE_PY = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                       os.pardir, 'reset_therapy_stats', 'core.py')


def load_core(path=CORE_PY):
    # load the file by path: importing the package would run its __init__,
    # which imports Odoo
    spec = importlib.util.spec_from_file_location('rt_core', path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


core = load_core()

MONDAY = 1791129600.0   # 2026-10-05 00:00 in UTC+8, a Monday
T0 = MONDAY + 3 * 86400 + 12 * 3600   # Thursday noon of that week
TZ8 = datetime.timezone(datetime.timedelta(hours=8))
EPOCH_MONDAY = datetime.date(1970, 1, 5)


def body(obj):
    return json.dumps(obj).encode('utf-8')


class ParseHealTest(unittest.TestCase):

    def test_valid_body(self):
        self.assertEqual(core.parse_heal(body({'providers': ['claude', 'gemini']})),
                         {'claude', 'gemini'})

    def test_one_request_adds_at_most_one_per_provider(self):
        many = ['claude', 'codex', 'gemini', 'grok', 'nope'] * 50
        self.assertEqual(core.parse_heal(body({'providers': many})),
                         set(core.PROVIDERS))
        self.assertEqual(core.parse_heal(body({'providers': ['claude'] * 300})),
                         {'claude'})

    def test_extra_keys_are_ignored(self):
        self.assertEqual(core.parse_heal(body({'providers': ['grok'], 'n': 999})),
                         {'grok'})

    def test_malformed_bodies_are_bad_requests(self):
        cases = [
            (None, 'bad json'),
            (b'', 'bad json'),
            (b'   ', 'bad json'),
            (b'not json', 'bad json'),
            (b'{"providers": ["claude"]', 'bad json'),
            (b"{'providers': ['claude']}", 'bad json'),
            (b'\xff\xfe{}', 'bad json'),
            (b'\xef\xbb\xbf{"providers": ["claude"]}', 'bad json'),
            (b'[' * 4000, 'bad json'),
            (b'{"a":' * 800, 'bad json'),
            (b'null', 'body must be a JSON object'),
            (b'42', 'body must be a JSON object'),
            (b'"claude"', 'body must be a JSON object'),
            (b'["claude"]', 'body must be a JSON object'),
            (b'{}', 'providers must be a list of strings'),
            (b'{"providers": null}', 'providers must be a list of strings'),
            (b'{"providers": "claude"}', 'providers must be a list of strings'),
            (b'{"providers": {"claude": 1}}', 'providers must be a list of strings'),
            (b'{"providers": ["claude", 1]}', 'providers must be a list of strings'),
            (b'{"providers": [["claude"]]}', 'providers must be a list of strings'),
            (b'{"providers": []}', 'no known providers'),
            (b'{"providers": ["Claude", "gpt"]}', 'no known providers'),
        ]
        for raw, message in cases:
            with self.subTest(raw=raw if raw is None else raw[:40]):
                with self.assertRaises(core.BadRequest) as ctx:
                    core.parse_heal(raw)
                self.assertEqual(str(ctx.exception), message)

    def test_body_limit_is_4_kb(self):
        def padded(size):
            raw = body({'providers': ['codex'], 'pad': ''})
            return raw[:-2] + b'x' * (size - len(raw)) + b'"}'
        self.assertEqual(len(padded(core.MAX_BODY)), 4096)
        self.assertEqual(core.parse_heal(padded(4096)), {'codex'})
        with self.assertRaises(core.BadRequest) as ctx:
            core.parse_heal(padded(4097))
        self.assertEqual(str(ctx.exception), 'too big')

    def test_random_input_only_ever_raises_bad_request(self):
        rnd = random.Random(20261001)
        atoms = ['claude', 'grok', 'x', '', 0, -1, 1.5, True, None, [], {}]

        def junk(depth=0):
            pick = rnd.random()
            if depth > 3 or pick < 0.4:
                return rnd.choice(atoms)
            if pick < 0.7:
                return [junk(depth + 1) for _ in range(rnd.randint(0, 4))]
            keys = ['providers', 'x', '']
            return {rnd.choice(keys): junk(depth + 1) for _ in range(rnd.randint(0, 3))}

        for _ in range(3000):
            if rnd.random() < 0.5:
                raw = bytes(rnd.getrandbits(8) for _ in range(rnd.randint(0, 64)))
            else:
                raw = json.dumps(junk()).encode('utf-8')
                if rnd.random() < 0.3:
                    cut = rnd.randint(0, len(raw))
                    raw = raw[:cut] + bytes([rnd.getrandbits(8)]) + raw[cut + 1:]
            try:
                got = core.parse_heal(raw)
            except core.BadRequest:
                continue
            self.assertTrue(got and got <= set(core.PROVIDERS), raw)


class ClientAddrTest(unittest.TestCase):

    def test_cf_connecting_ip_comes_first(self):
        headers = {'CF-Connecting-IP': '203.0.113.7',
                   'X-Forwarded-For': '198.51.100.1, 192.0.2.9'}
        self.assertEqual(core.client_addr(headers, '192.0.2.1'), '203.0.113.7')

    def test_then_the_first_x_forwarded_for_entry(self):
        headers = {'X-Forwarded-For': ' 198.51.100.1 , 192.0.2.9'}
        self.assertEqual(core.client_addr(headers, '192.0.2.1'), '198.51.100.1')

    def test_then_remote_addr(self):
        self.assertEqual(core.client_addr({}, '192.0.2.1'), '192.0.2.1')
        self.assertEqual(core.client_addr(None, '192.0.2.1'), '192.0.2.1')

    def test_empty_headers_fall_through(self):
        headers = {'CF-Connecting-IP': ' ', 'X-Forwarded-For': ''}
        self.assertEqual(core.client_addr(headers, '192.0.2.1'), '192.0.2.1')

    def test_header_names_are_case_insensitive(self):
        self.assertEqual(core.client_addr({'cf-connecting-ip': '203.0.113.7'}, None),
                         '203.0.113.7')
        self.assertEqual(core.client_addr({'X-FORWARDED-FOR': '198.51.100.1'}, None),
                         '198.51.100.1')

    def test_ipv6_is_grouped_per_64(self):
        one = core.client_addr({'CF-Connecting-IP': '2001:db8:1:2:aaaa::1'}, None)
        two = core.client_addr({'CF-Connecting-IP': '2001:db8:1:2:bbbb::2'}, None)
        other = core.client_addr({'CF-Connecting-IP': '2001:db8:1:3::1'}, None)
        self.assertEqual(one, '2001:db8:1:2::/64')
        self.assertEqual(one, two)
        self.assertNotEqual(one, other)

    def test_ipv4_mapped_ipv6_is_ipv4(self):
        self.assertEqual(core.client_addr({'CF-Connecting-IP': '::ffff:203.0.113.7'}, None),
                         '203.0.113.7')

    def test_unparseable_values_are_kept_short(self):
        self.assertEqual(core.client_addr({'CF-Connecting-IP': 'x' * 500}, None), 'x' * 64)
        self.assertEqual(core.client_addr({}, None), 'unknown')


class WeekIndexTest(unittest.TestCase):

    def test_week_starts_monday_midnight_utc8(self):
        week = core.week_index(MONDAY)
        self.assertEqual(core.week_index(MONDAY - 1), week - 1)
        self.assertEqual(core.week_index(MONDAY + 7 * 86400 - 1), week)
        self.assertEqual(core.week_index(MONDAY + 7 * 86400), week + 1)

    def test_matches_calendar_weeks_in_utc8(self):
        for ts in range(int(MONDAY) - 9 * 86400, int(MONDAY) + 9 * 86400, 1789):
            local = datetime.datetime.fromtimestamp(ts, TZ8).date()
            monday = local - datetime.timedelta(days=local.weekday())
            self.assertEqual(core.week_index(ts),
                             (monday - EPOCH_MONDAY).days // 7 + 1, ts)


class LedgerTestCase(unittest.TestCase):

    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix='rt-test-')
        self.path = os.path.join(self.dir, core.DB_FILE)
        self.con = core.connect(self.path)

    def tearDown(self):
        self.con.close()
        shutil.rmtree(self.dir, ignore_errors=True)

    def hit_rows(self):
        return self.con.execute('SELECT client, ts FROM heal_hits').fetchall()


class HealLimitTest(LedgerTestCase):

    def fill(self, client='203.0.113.7', start=T0):
        for i in range(core.RATE_LIMIT):
            core.heal(self.con, client, {'claude'}, now=start + i)

    def test_thirty_per_minute_then_refused(self):
        self.fill()
        self.assertEqual(core.RATE_LIMIT, 30)
        with self.assertRaises(core.RateLimited) as ctx:
            core.heal(self.con, '203.0.113.7', {'claude'}, now=T0 + 30)
        # the oldest of the 30 (at T0) leaves the 60 s window at T0 + 60
        self.assertEqual(ctx.exception.retry_after, 30)
        self.assertEqual(core.stats(self.con, T0)['week']['claude'], 30)

    def test_refused_requests_change_nothing(self):
        self.fill()
        before = (core.stats(self.con, T0), len(self.hit_rows()))
        for i in range(10):
            with self.assertRaises(core.RateLimited):
                core.heal(self.con, '203.0.113.7', set(core.PROVIDERS), now=T0 + 30 + i)
        self.assertEqual((core.stats(self.con, T0), len(self.hit_rows())), before)

    def test_window_slides(self):
        self.fill()
        with self.assertRaises(core.RateLimited):
            core.heal(self.con, '203.0.113.7', {'claude'}, now=T0 + 59.5)
        core.heal(self.con, '203.0.113.7', {'claude'}, now=T0 + 60)
        with self.assertRaises(core.RateLimited):
            core.heal(self.con, '203.0.113.7', {'claude'}, now=T0 + 60.5)
        core.heal(self.con, '203.0.113.7', {'claude'}, now=T0 + 61)
        self.assertEqual(core.stats(self.con, T0)['week']['claude'], 32)

    def test_retry_after_is_at_least_one_second(self):
        for _ in range(core.RATE_LIMIT):
            core.heal(self.con, '203.0.113.7', {'claude'}, now=T0)
        with self.assertRaises(core.RateLimited) as ctx:
            core.heal(self.con, '203.0.113.7', {'claude'}, now=T0 + 59.99)
        self.assertEqual(ctx.exception.retry_after, 1)

    def test_limit_is_per_client(self):
        self.fill('203.0.113.7')
        core.heal(self.con, '198.51.100.1', {'grok'}, now=T0 + 30)
        self.assertEqual(core.stats(self.con, T0)['week']['grok'], 1)

    def test_a_request_adds_at_most_one_per_provider(self):
        core.heal(self.con, '203.0.113.7', ['claude', 'claude', 'nope'], now=T0)
        core.heal(self.con, '203.0.113.7', set(core.PROVIDERS), now=T0 + 1)
        week = core.stats(self.con, T0)['week']
        self.assertEqual(week, {'claude': 2, 'codex': 1, 'gemini': 1, 'grok': 1})

    def test_old_rows_are_cleaned_up(self):
        for i in range(50):
            core.heal(self.con, '192.0.2.%d' % i, {'codex'}, now=T0)
        self.assertEqual(len(self.hit_rows()), 50)
        core.heal(self.con, '203.0.113.7', {'codex'}, now=T0 + core.RATE_WINDOW)
        self.assertEqual([ts for _, ts in self.hit_rows()], [T0 + core.RATE_WINDOW])

    def test_no_raw_addresses_are_stored(self):
        core.heal(self.con, '203.0.113.7', {'codex'}, now=T0)
        (client, _), = self.hit_rows()
        self.assertNotIn('203.0.113', client)

    def test_a_failed_heal_leaves_no_trace(self):
        self.con.execute('DROP TABLE heals')  # make the counter write fail midway
        with self.assertRaises(sqlite3.OperationalError):
            core.heal(self.con, '203.0.113.7', {'claude'}, now=T0)
        self.assertFalse(self.con.in_transaction)
        self.assertEqual(self.hit_rows(), [])

    def test_counts_land_in_the_utc8_week(self):
        core.heal(self.con, '203.0.113.7', {'gemini'}, now=MONDAY - 1)
        core.heal(self.con, '203.0.113.7', {'gemini'}, now=MONDAY)
        stats = core.stats(self.con, MONDAY)
        self.assertEqual(stats['weekIdx'], core.week_index(MONDAY))
        self.assertEqual(stats['week']['gemini'], 1)
        self.assertEqual(stats['all']['gemini'], 2)

    def test_limit_holds_across_processes(self):
        # Odoo runs several worker processes: they must share one budget
        script = (
            'import importlib.util, sys\n'
            'spec = importlib.util.spec_from_file_location("rt_core", sys.argv[1])\n'
            'core = importlib.util.module_from_spec(spec)\n'
            'spec.loader.exec_module(core)\n'
            'ok = 0\n'
            'for _ in range(20):\n'
            '    con = core.connect(sys.argv[2])\n'
            '    try:\n'
            '        core.heal(con, "203.0.113.7", {"claude"}, now=float(sys.argv[3]))\n'
            '        ok += 1\n'
            '    except core.RateLimited:\n'
            '        pass\n'
            '    finally:\n'
            '        con.close()\n'
            'print(ok)\n')
        with contextlib.ExitStack() as stack:
            procs = [stack.enter_context(subprocess.Popen(
                [sys.executable, '-c', script, CORE_PY, self.path, str(T0)],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True))
                for _ in range(4)]
            results = [(proc.communicate(timeout=120), proc.returncode) for proc in procs]
        accepted = 0
        for (out, err), returncode in results:
            self.assertEqual(returncode, 0, err)
            accepted += int(out)
        self.assertEqual(accepted, core.RATE_LIMIT)
        self.assertEqual(core.stats(self.con, T0)['week']['claude'], core.RATE_LIMIT)


class HandlerTest(LedgerTestCase):
    """What the two endpoints answer, minus the Odoo wrapping."""

    HEADERS = {'CF-Connecting-IP': '203.0.113.7'}

    def post(self, raw, headers=None, now=T0, content_length=None):
        if content_length is None and raw is not None:
            content_length = len(raw)
        return core.handle_heal(self.path, content_length, lambda: raw,
                                self.HEADERS if headers is None else headers,
                                '192.0.2.1', now=now)

    def test_valid_heal_returns_fresh_stats(self):
        status, data, headers = self.post(body({'providers': ['claude', 'grok']}))
        self.assertEqual((status, headers), (200, []))
        self.assertEqual(data['weekIdx'], core.week_index(T0))
        self.assertEqual(data['week'], {'claude': 1, 'codex': 0, 'gemini': 0, 'grok': 1})
        self.assertEqual(data['all'], data['week'])
        self.assertEqual(core.handle_stats(self.path, T0), (200, data, []))

    def test_malformed_input_is_400_with_a_json_error(self):
        for raw in (b'not json', b'', b'[]', b'null', b'{"providers": "claude"}',
                    b'{"providers": ["nope"]}', b'\xff', b'[' * 4000):
            with self.subTest(raw=raw[:40]):
                status, data, headers = self.post(raw)
                self.assertEqual(status, 400)
                self.assertEqual(list(data), ['error'])
                json.dumps(data)
        self.assertEqual(core.handle_stats(self.path, T0)[1]['all'],
                         dict.fromkeys(core.PROVIDERS, 0))

    def test_oversized_upload_is_refused_unread(self):
        def boom():
            raise AssertionError('body should not be read')
        status, data, _ = core.handle_heal(self.path, 5000, boom, self.HEADERS,
                                           '192.0.2.1', now=T0)
        self.assertEqual((status, data), (400, {'error': 'too big'}))

    def test_over_the_limit_is_429_with_retry_after(self):
        ok = body({'providers': ['codex']})
        for i in range(30):
            self.assertEqual(self.post(ok, now=T0 + i)[0], 200)
        status, data, headers = self.post(ok, now=T0 + 30)
        self.assertEqual((status, data), (429, {'error': 'rate limited'}))
        self.assertEqual(headers, [('Retry-After', '30')])
        # malformed input is still 400, and other clients still get through
        self.assertEqual(self.post(b'oops', now=T0 + 30)[0], 400)
        other = {'X-Forwarded-For': '198.51.100.1, 192.0.2.9'}
        self.assertEqual(self.post(ok, headers=other, now=T0 + 30)[0], 200)

    def test_existing_ledger_keeps_its_counts(self):
        # a file written by the previous version (heals table only) still works
        self.con.close()
        os.remove(self.path)
        old = sqlite3.connect(self.path)
        old.execute('CREATE TABLE heals (provider TEXT NOT NULL, week INTEGER NOT NULL,'
                    ' n INTEGER NOT NULL DEFAULT 0, PRIMARY KEY (provider, week))')
        old.execute('INSERT INTO heals VALUES (?, ?, ?)', ('claude', core.week_index(T0), 7))
        old.commit()
        old.close()
        self.con = core.connect(self.path)
        status, data, _ = self.post(body({'providers': ['claude']}))
        self.assertEqual((status, data['week']['claude'], data['all']['claude']), (200, 8, 8))


if __name__ == '__main__':
    unittest.main()
