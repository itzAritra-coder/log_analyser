"""HTTP server exposing the analyzer.

POST /analyses   body = raw log text (text/plain)  ->  200 + JSON summary
GET  /health                                       ->  200 {"status": "ok"}

The request body is streamed in 64 KB chunks and analysed on the fly, so a
multi-gigabyte log uses the same small amount of memory as a tiny one.
"""
import argparse
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from analyzer import analyze, iter_lines

CHUNK = 64 * 1024
DEFAULT_MAX_BODY = 4 * 1024 ** 3   # 4 GB; configurable with --max-bytes


class IncompleteBody(Exception):
    pass


class Handler(BaseHTTPRequestHandler):
    timeout = 60                    # drop stalled connections
    max_body = DEFAULT_MAX_BODY

    def _send(self, status, payload):
        body = json.dumps(payload).encode()
        try:
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        except OSError:             # client already went away
            pass

    def _chunks(self, length):
        remaining = length
        while remaining:
            chunk = self.rfile.read(min(CHUNK, remaining))
            if not chunk:
                raise IncompleteBody()
            remaining -= len(chunk)
            yield chunk

    def do_GET(self):
        if self.path == "/health":
            self._send(200, {"status": "ok"})
        else:
            self._send(404, {"error": "not found"})

    def do_POST(self):
        if self.path != "/analyses":
            return self._send(404, {"error": "not found"})
        header = self.headers.get("Content-Length")
        if header is None:
            return self._send(411, {"error": "Content-Length required"})
        try:
            length = int(header)
            if length < 0:
                raise ValueError
        except ValueError:
            return self._send(400, {"error": "invalid Content-Length"})
        if length > self.max_body:
            self.close_connection = True
            return self._send(413, {"error": f"payload exceeds {self.max_body} bytes"})
        try:
            result = analyze(iter_lines(self._chunks(length)))
        except (IncompleteBody, OSError):
            self.close_connection = True
            return self._send(400, {"error": "request body incomplete"})
        self._send(200, result)

    def log_message(self, fmt, *args):
        print("%s - %s" % (self.address_string(), fmt % args))


def make_server(host="127.0.0.1", port=8080, max_body=DEFAULT_MAX_BODY):
    handler = type("ConfiguredHandler", (Handler,), {"max_body": max_body})
    server = ThreadingHTTPServer((host, port), handler)
    server.daemon_threads = True
    return server


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8080)
    p.add_argument("--max-bytes", type=int, default=DEFAULT_MAX_BODY,
                   help="reject uploads larger than this many bytes")
    a = p.parse_args()
    print(f"Listening on http://{a.host}:{a.port}")
    make_server(a.host, a.port, a.max_bytes).serve_forever()


if __name__ == "__main__":
    main()