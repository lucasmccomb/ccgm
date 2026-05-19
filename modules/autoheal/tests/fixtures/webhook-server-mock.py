#!/usr/bin/env python3
"""Tiny mock HTTP server for the autoheal webhook publisher.

Used by `test-webhook-publisher.sh` so we never reach a real
`dev.lem.work`-style endpoint from the test suite.

Behavior:
    POST /v1/ingest
        - Records the envelope: full headers (especially Authorization),
          body JSON, timestamp.
        - Returns 200 with `{"ok": true}` by default.
        - If the server was started with --fail-with <code>, returns
          that HTTP code with `{"error": "mock failure"}`.
        - If started with --fail-once <code>, returns that code for the
          FIRST request, then 200 for all subsequent requests. Used to
          simulate the retry path: first attempt fails, cursor stays put,
          second daily run succeeds and cursor advances.
    GET /requests
        - Returns the recorded envelope list as JSON. The test driver
          polls this to assert on what was sent.
    POST /reset
        - Clears the recorded envelope list AND resets the fail-once
          counter so a fresh fail-once flow can be exercised after the
          first one completes.

Usage (from a test):

    python3 modules/autoheal/tests/fixtures/webhook-server-mock.py \\
        --port 0 --pidfile /tmp/foo.pid --port-file /tmp/foo.port

The server writes its actual listening port to --port-file and its pid
to --pidfile. The test reads the port, runs autoheal-publish.sh with
CCGM webhook env pointing at the mock, then GETs /requests.

Modeled on tests/fixtures/resend-mock-server.py to keep the two test
fixtures consistent in shape.
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
FAIL_ONCE: int | None = None
FAIL_ONCE_FIRED = False


class Handler(BaseHTTPRequestHandler):
    server_version = "WebhookMock/0.1"

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
        self._send_json(404, {"error": "not_found", "path": self.path})

    def do_POST(self):  # noqa: N802 - http.server contract
        global FAIL_ONCE_FIRED

        if self.path == "/reset":
            with REQ_LOCK:
                REQUESTS.clear()
            FAIL_ONCE_FIRED = False
            self._send_json(200, {"reset": True})
            return

        if self.path == "/v1/ingest":
            raw_body = self._read_body()
            try:
                body_json = json.loads(raw_body.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                body_json = None

            record = {
                "method": "POST",
                "path": self.path,
                "headers": {k: v for k, v in self.headers.items()},
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
                    {"error": "mock_failure", "code": FAIL_WITH},
                )
                return

            if FAIL_ONCE is not None and not FAIL_ONCE_FIRED:
                FAIL_ONCE_FIRED = True
                self._send_json(
                    FAIL_ONCE,
                    {"error": "mock_fail_once", "code": FAIL_ONCE},
                )
                return

            self._send_json(200, {"ok": True})
            return

        self._send_json(404, {"error": "not_found", "path": self.path})


def main(argv: list[str]) -> int:
    global FAIL_WITH, FAIL_ONCE

    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=0)
    parser.add_argument("--pidfile", default=None)
    parser.add_argument("--port-file", default=None)
    parser.add_argument("--fail-with", type=int, default=None,
                        help="Return this HTTP code for EVERY POST /v1/ingest.")
    parser.add_argument("--fail-once", type=int, default=None,
                        help="Return this HTTP code for the FIRST POST, then 200 for all subsequent POSTs (resets on /reset).")
    args = parser.parse_args(argv)

    FAIL_WITH = args.fail_with
    FAIL_ONCE = args.fail_once

    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    actual_port = server.server_address[1]

    if args.pidfile:
        with open(args.pidfile, "w", encoding="utf-8") as fh:
            fh.write(str(os.getpid()))
    if args.port_file:
        with open(args.port_file, "w", encoding="utf-8") as fh:
            fh.write(str(actual_port))

    sys.stderr.write(f"webhook-mock listening on 127.0.0.1:{actual_port}\n")
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
