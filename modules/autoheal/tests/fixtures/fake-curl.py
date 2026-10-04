#!/usr/bin/env python3
"""Stand-in for curl in the autoheal analyzer tests. No network, ever.

Put a copy named `curl` first on PATH and point FAKE_CURL_DIR at a scratch
directory. The analyzer calls curl with `-o <file> -w '%{http_code}'
--data-binary @<request> <url>`; this script:

  - tells the two endpoints apart by URL suffix (`/count_tokens` or not),
  - appends the endpoint name to $FAKE_CURL_DIR/calls.log (the call count),
  - saves the request body as <endpoint>-<n>.request.json (n counts from 1),
  - writes the canned body to the -o file and prints the status code.

Canned answers, first match wins:
  <endpoint>-<n>.response.json   this call only
  <endpoint>.response.json       every call of the endpoint
  count_tokens with neither      {"input_tokens": 8000}
  messages with neither          HTTP 500 (a test forgot to stage a reply)
Status code: <endpoint>-<n>.status, then <endpoint>.status, else 200.
Transport failure: a <endpoint>.curl_exit file holds the exit code to return.
"""

import os
import shutil
import sys

d = os.environ["FAKE_CURL_DIR"]
args = sys.argv[1:]
out = body = url = None
i = 0
while i < len(args):
    a = args[i]
    if a in ("-o", "-w", "-H", "--max-time"):
        if a == "-o":
            out = args[i + 1]
        i += 2
        continue
    if a == "--data-binary":
        body = args[i + 1]
        i += 2
        continue
    if a.startswith("http"):
        url = a
    i += 1

endpoint = "count_tokens" if (url or "").endswith("/count_tokens") else "messages"
calls = os.path.join(d, "calls.log")
with open(calls, "a", encoding="utf-8") as fh:
    fh.write(endpoint + "\n")
with open(calls, "r", encoding="utf-8") as fh:
    n = sum(1 for line in fh if line.strip() == endpoint)

if body and body.startswith("@"):
    shutil.copy(body[1:], os.path.join(d, f"{endpoint}-{n}.request.json"))


def pick(*names):
    for name in names:
        path = os.path.join(d, name)
        if os.path.isfile(path):
            return path
    return None


exit_file = pick(f"{endpoint}.curl_exit")
if exit_file:
    code = int(open(exit_file, encoding="utf-8").read().strip() or "1")
    print(f"curl: ({code}) simulated transport failure", file=sys.stderr)
    sys.exit(code)

status_file = pick(f"{endpoint}-{n}.status", f"{endpoint}.status")
status = open(status_file, encoding="utf-8").read().strip() if status_file else "200"
resp = pick(f"{endpoint}-{n}.response.json", f"{endpoint}.response.json")
if out:
    if resp:
        shutil.copy(resp, out)
    elif endpoint == "count_tokens":
        with open(out, "w", encoding="utf-8") as fh:
            fh.write('{"input_tokens": 8000}')
    else:
        status = "500"
        with open(out, "w", encoding="utf-8") as fh:
            fh.write('{"type": "error", "error": {"message": "no staged response"}}')
sys.stdout.write(status)
