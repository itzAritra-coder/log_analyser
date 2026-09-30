"""Tests. No external files needed; logs of any size are generated in memory."""
import json
import threading
import unittest
import urllib.error
import urllib.request
from collections import Counter

from analyzer import LEVELS, MAX_LINE_CHARS, analyze, iter_lines, parse_line
from server import make_server

SERVICES = ["auth-service", "payment-service", "billing-service", "inventory-service"]

SAMPLE = """2026-09-18 10:23:45 ERROR payment-service Connection timeout after 30s
2026-09-18 10:23:46 INFO auth-service User login successful
2026-09-18 10:23:47 ERROR payment-service Connection refused
2026-09-18 10:24:01 WARN auth-service Response time degraded
2026-09-18 10:24:15 ERROR billing-service Invalid account state
2026-09-18 10:24:30 INFO payment-service Retry succeeded
error billing-service No Auth token
"""


def gen_lines(n):
    """Yield n lines: every 50th is garbage, the rest cycle through services/levels."""
    for i in range(n):
        if i % 50 == 0:
            yield f"garbage line {i}\n"
        else:
            yield f"2026-09-18 10:00:00 {LEVELS[i % 5]} {SERVICES[i % 4]} msg {i}\n"


def expected_for(n):
    errors, seen, bad = Counter(), set(), 0
    for i in range(n):
        if i % 50 == 0:
            bad += 1
            continue
        seen.add(SERVICES[i % 4])
        if LEVELS[i % 5] == "ERROR":
            errors[SERVICES[i % 4]] += 1
    return n, bad, {s: errors.get(s, 0) for s in seen}


class AnalyzerTests(unittest.TestCase):
    def test_sample(self):
        r = analyze(SAMPLE.splitlines())
        self.assertEqual(r["lines_processed"], 7)
        self.assertEqual(r["unparseable_lines"], 1)
        self.assertEqual(r["errors_by_service"],
                         {"payment-service": 2, "billing-service": 1, "auth-service": 0})
        self.assertEqual(r["top_offender"], "payment-service")

    def test_any_size(self):
        for n in (0, 1, 2, 49, 50, 51, 1000, 200_000):
            with self.subTest(n=n):
                r = analyze(gen_lines(n))
                total, bad, errs = expected_for(n)
                self.assertEqual(r["lines_processed"], total)
                self.assertEqual(r["unparseable_lines"], bad)
                self.assertEqual(dict(r["errors_by_service"]), errs)

    def test_empty_and_blank(self):
        self.assertEqual(analyze([]), {"lines_processed": 0, "unparseable_lines": 0,
                                       "errors_by_service": {}, "top_offender": None})
        self.assertEqual(analyze(["", "  ", "\n"])["lines_processed"], 0)

    def test_no_errors_means_no_offender(self):
        r = analyze(["2026-09-18 10:00:00 INFO a ok"])
        self.assertIsNone(r["top_offender"])
        self.assertEqual(r["errors_by_service"], {"a": 0})

    def test_bad_lines(self):
        for bad in ["2026-13-45 10:00:00 ERROR a x", "2026-09-18 25:00:00 ERROR a x",
                    "2026-09-18 10:00:00 error a x", "2026-09-18 10:00:00 TRACE a x",
                    "2026-09-18 10:00:00 ERROR a"]:
            self.assertIsNone(parse_line(bad), bad)

    def test_crlf_and_bom(self):
        r = analyze(["\ufeff2026-09-18 10:00:00 ERROR a x\r\n", "2026-09-18 10:00:01 ERROR a y\r\n"])
        self.assertEqual(r["errors_by_service"], {"a": 2})


class StreamingTests(unittest.TestCase):
    def test_chunk_size_never_changes_result(self):
        text = SAMPLE + "2026-09-18 10:30:00 ERROR café-service ünïcode ✓ 🚀\n" + "no trailing newline"
        data = text.encode()
        baseline = analyze(text.splitlines())
        for size in (1, 2, 3, 7, 64, 1024, len(data)):
            with self.subTest(chunk=size):
                chunks = (data[i:i + size] for i in range(0, len(data), size))
                self.assertEqual(analyze(iter_lines(chunks)), baseline)

    def test_overlong_line_counted_once_even_across_chunks(self):
        huge = b"x" * (MAX_LINE_CHARS * 3)
        data = b"2026-09-18 10:00:00 ERROR a ok\n" + huge + b"\n2026-09-18 10:00:01 ERROR a ok\n"
        for size in (1000, 70_000, len(data)):
            chunks = (data[i:i + size] for i in range(0, len(data), size))
            r = analyze(iter_lines(chunks))
            self.assertEqual((r["lines_processed"], r["unparseable_lines"]), (3, 1), size)
            self.assertEqual(r["errors_by_service"], {"a": 2})

    def test_invalid_utf8_does_not_crash(self):
        r = analyze(iter_lines([b"2026-09-18 10:00:00 ERROR a \xff\xfe bad bytes\n"]))
        self.assertEqual(r["errors_by_service"], {"a": 1})


class ServerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.srv = make_server("127.0.0.1", 0, max_body=50 * 1024 * 1024)
        cls.base = f"http://127.0.0.1:{cls.srv.server_address[1]}"
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.srv.server_close()

    def post(self, data):
        req = urllib.request.Request(self.base + "/analyses", data=data, method="POST")
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.status, json.load(r)

    def test_health(self):
        with urllib.request.urlopen(self.base + "/health") as r:
            self.assertEqual(json.load(r), {"status": "ok"})

    def test_small_and_large_uploads(self):
        for n in (0, 7, 300_000):
            with self.subTest(n=n):
                status, body = self.post("".join(gen_lines(n)).encode())
                total, bad, errs = expected_for(n)
                self.assertEqual(status, 200)
                self.assertEqual(body["lines_processed"], total)
                self.assertEqual(body["unparseable_lines"], bad)
                self.assertEqual(body["errors_by_service"], errs)

    def test_unknown_path_404(self):
        with self.assertRaises(urllib.error.HTTPError) as cm:
            urllib.request.urlopen(self.base + "/nope")
        self.assertEqual(cm.exception.code, 404)

    def test_payload_too_large_413(self):
        big = b"x" * (51 * 1024 * 1024)
        with self.assertRaises((urllib.error.HTTPError, OSError)):
            self.post(big)


if __name__ == "__main__":
    unittest.main()