#!/usr/bin/env python3
"""Tiny mock HTTP server that mimics the Resend /emails endpoint.

Used by autoheal email tests so we never reach api.resend.com from the
test suite.

Behavior:
    POST /emails
        - Records the request: full headers (especially Idempotency-Key),
          body JSON, and the timestamp.
        - Returns 200 with a small JSON envelope `{"id": "mock_..."}` by
          default.
        - If the server was started with --fail-with <code>, returns
          that HTTP code with `{"name":"error","message":"mock failure"}`.
    GET /requests
        - Returns the recorded request list as JSON. The test driver
          polls this to assert on what was sent.
    POST /reset
        - Clears the recorded request list.

Usage (from a test):

    python3 modules/autoheal/tests/fixtures/resend-mock-server.py \\
        --port 0 --pidfile /tmp/foo.pid --port-file /tmp/foo.port

The server writes its actual listening port to --port-file and its pid to
--pidfile. The test reads the port, runs the email script with
CCGM_AUTOHEAL_RESEND_URL pointing at the mock, then GETs /requests.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


REQUESTS: list[dict] = []
REQ_LOCK = threading.Lock()
FAIL_WITH: int | None = None


class Handler(BaseHTTPRequestHandler):
    server_version = "ResendMock/0.1"

    def log_message(self, format, *args):  # noqa: D401 - quiet test output
        # Suppress default request logging so the test output stays clean.
        return

    def _read_body(self) -> bytes:
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0:
            return b""
        return self.rfile.read(length)

    def _send_json(self, code: int, payload: dict) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):  # noqa: N802 - http.server contract
        if self.path == "/requests":
            with REQ_LOCK:
                snapshot = list(REQUESTS)
            self._send_json(200, {"requests": snapshot})
            return
        if self.path == "/health":
            self._send_json(200, {"ok": True})
            return
        self._send_json(404, {"name": "not_found", "message": self.path})

    def do_POST(self):  # noqa: N802 - http.server contract
        if self.path == "/reset":
            with REQ_LOCK:
                REQUESTS.clear()
            self._send_json(200, {"reset": True})
            return

        if self.path == "/emails":
            raw_body = self._read_body()
            try:
                body_json = json.loads(raw_body.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                body_json = None

            record = {
                "method": "POST",
                "path": self.path,
                "headers": {k: v for k, v in self.headers.items()},
                "idempotency_key": self.headers.get("Idempotency-Key"),
                "authorization": self.headers.get("Authorization"),
                "content_type": self.headers.get("Content-Type"),
                "body_json": body_json,
                "body_raw": raw_body.decode("utf-8", errors="replace"),
            }
            with REQ_LOCK:
                REQUESTS.append(record)

            if FAIL_WITH is not None:
                self._send_json(
                    FAIL_WITH,
                    {"name": "mock_failure", "message": f"forced {FAIL_WITH}"},
                )
                return

            # Mock id derived from the idempotency key for traceability.
            idem = record["idempotency_key"] or "no-idem"
            self._send_json(200, {"id": f"mock_{idem}"})
            return

        self._send_json(404, {"name": "not_found", "message": self.path})


def main(argv: list[str]) -> int:
    global FAIL_WITH

    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=0)
    parser.add_argument("--pidfile", default=None)
    parser.add_argument("--port-file", default=None)
    parser.add_argument("--fail-with", type=int, default=None)
    args = parser.parse_args(argv)

    FAIL_WITH = args.fail_with

    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    actual_port = server.server_address[1]

    if args.pidfile:
        with open(args.pidfile, "w", encoding="utf-8") as fh:
            fh.write(str(os.getpid()))
    if args.port_file:
        with open(args.port_file, "w", encoding="utf-8") as fh:
            fh.write(str(actual_port))

    sys.stderr.write(f"resend-mock listening on 127.0.0.1:{actual_port}\n")
    sys.stderr.flush()

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()

    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
