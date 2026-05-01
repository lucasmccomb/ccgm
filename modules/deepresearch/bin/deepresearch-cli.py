#!/usr/bin/env python3
"""
deepresearch-cli.py - Exa-backed research fan-out

Takes a list of search queries, runs them in parallel against Exa's neural
search API (https://api.exa.ai/search), and emits a structured JSON envelope
containing per-query results with full page contents. Synthesis into
research.md is handled by the calling skill (Claude Code).

Usage:
  deepresearch-cli.py --topic "TOPIC" --output PATH \
    --query "q1" --query "q2" --query "q3"

  deepresearch-cli.py --topic "TOPIC" --output PATH --queries-file queries.txt

  deepresearch-cli.py --topic "TOPIC" --output PATH --plan-dir DIR \
    --query "q1" --query "q2" --depth full
"""

import argparse
import asyncio
import ipaddress
import json
import os
import pathlib
import socket
import sys
import time

import httpx


EXA_API_URL = "https://api.exa.ai/search"
EXA_TIMEOUT_S = 30.0
DEFAULT_RESULTS_PER_QUERY = 5
MAX_TEXT_CHARS_PER_RESULT = 6000


_BLOCKED_NETWORKS = [
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fc00::/7"),
]


def is_safe_url(url: str) -> bool:
    """Reject URLs that resolve to private / loopback / link-local addresses.

    Exa returns public web URLs, but defense-in-depth: refuse anything that
    points at the local network in case a result URL is malformed or hostile.
    """
    try:
        host = url.split("//", 1)[-1].split("/", 1)[0].split(":", 1)[0]
        if not host:
            return False
        addr = ipaddress.ip_address(socket.gethostbyname(host))
        return not any(addr in net for net in _BLOCKED_NETWORKS)
    except Exception:
        return False


def require_api_key() -> str:
    key = os.environ.get("EXA_API_KEY", "").strip()
    if not key:
        print(
            "ERROR: EXA_API_KEY not set.\n"
            "  Sign up at https://exa.ai (free tier: 1000 searches/mo).\n"
            "  Then add to your shell rc:\n"
            "    export EXA_API_KEY=your_key_here\n"
            "  And reload your shell.",
            file=sys.stderr,
        )
        sys.exit(2)
    return key


async def search_exa(
    query: str,
    client: httpx.AsyncClient,
    api_key: str,
    n_results: int,
) -> dict:
    """Run a single Exa search. Returns a dict with query, results, error."""
    payload = {
        "query": query,
        "numResults": n_results,
        "type": "auto",
        "contents": {
            "text": {"maxCharacters": MAX_TEXT_CHARS_PER_RESULT},
        },
    }
    headers = {
        "x-api-key": api_key,
        "Content-Type": "application/json",
        "User-Agent": "ccgm-deepresearch/1.0",
    }
    try:
        resp = await client.post(
            EXA_API_URL, json=payload, headers=headers, timeout=EXA_TIMEOUT_S
        )
        if resp.status_code == 401:
            return {"query": query, "results": [], "error": "exa_unauthorized"}
        if resp.status_code == 429:
            return {"query": query, "results": [], "error": "exa_rate_limited"}
        resp.raise_for_status()
        data = resp.json()
    except httpx.TimeoutException:
        print(f"WARN: Exa timed out for query '{query[:60]}'", file=sys.stderr)
        return {"query": query, "results": [], "error": "timeout"}
    except httpx.HTTPStatusError as e:
        print(
            f"WARN: Exa HTTP {e.response.status_code} for query '{query[:60]}'",
            file=sys.stderr,
        )
        return {
            "query": query,
            "results": [],
            "error": f"http_{e.response.status_code}",
        }
    except Exception as e:
        print(
            f"WARN: Exa error for query '{query[:60]}': {type(e).__name__}: {e}",
            file=sys.stderr,
        )
        return {"query": query, "results": [], "error": type(e).__name__}

    results = []
    for r in data.get("results", []):
        url = r.get("url", "")
        if not url or not is_safe_url(url):
            continue
        text = r.get("text", "") or ""
        if len(text) > MAX_TEXT_CHARS_PER_RESULT:
            text = text[:MAX_TEXT_CHARS_PER_RESULT]
        results.append(
            {
                "url": url,
                "title": r.get("title", "") or "",
                "published_date": r.get("publishedDate"),
                "author": r.get("author"),
                "score": r.get("score"),
                "text": text,
            }
        )
    return {"query": query, "results": results, "error": None}


async def run_parallel(
    queries: list[str], api_key: str, n_results: int
) -> list[dict]:
    print(
        f"[search] Running {len(queries)} parallel Exa queries...",
        file=sys.stderr,
    )
    async with httpx.AsyncClient() as client:
        tasks = [search_exa(q, client, api_key, n_results) for q in queries]
        batches = await asyncio.gather(*tasks)
    total = sum(len(b["results"]) for b in batches)
    errored = [b["query"][:40] for b in batches if b.get("error")]
    print(
        f"[search] Retrieved {total} results across {len(queries)} queries.",
        file=sys.stderr,
    )
    if errored:
        print(f"[search] {len(errored)} queries errored: {errored}", file=sys.stderr)
    return batches


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run a list of queries against Exa and emit JSON.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--topic", required=True, help="Research topic (passed through to JSON output)")
    parser.add_argument("--output", required=True, help="Intended output path for research.md (passed through; not written by this script)")
    parser.add_argument("--query", action="append", default=[], help="A search query (repeatable)")
    parser.add_argument("--queries-file", help="Path to a file with one query per line (alternative to --query)")
    parser.add_argument(
        "--n-results",
        type=int,
        default=DEFAULT_RESULTS_PER_QUERY,
        help=f"Results per query (default: {DEFAULT_RESULTS_PER_QUERY})",
    )
    parser.add_argument(
        "--depth",
        choices=["lite", "standard", "full"],
        default="standard",
        help="Depth label, included in JSON output (does not affect query count - the caller decides how many --query flags to pass)",
    )
    parser.add_argument("--plan-dir", default=None, help="xplan plan directory (passed through to JSON)")
    parser.add_argument("--extend", default=None, help="Prior research.md to extend (accepted for compat, not used)")
    return parser.parse_args()


def collect_queries(args: argparse.Namespace) -> list[str]:
    queries: list[str] = list(args.query)
    if args.queries_file:
        path = pathlib.Path(args.queries_file).expanduser()
        if not path.is_file():
            print(f"ERROR: --queries-file not found: {path}", file=sys.stderr)
            sys.exit(2)
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                queries.append(line)
    queries = [q for q in (q.strip() for q in queries) if q]
    if not queries:
        print(
            "ERROR: No queries provided. Pass --query 'q' (repeatable) or "
            "--queries-file PATH.",
            file=sys.stderr,
        )
        sys.exit(2)
    return queries


async def main() -> None:
    t_start = time.time()
    args = parse_args()
    api_key = require_api_key()
    queries = collect_queries(args)

    if args.plan_dir:
        output_path = str(pathlib.Path(args.plan_dir).resolve() / "research.md")
    else:
        output_path = str(pathlib.Path(args.output).resolve())

    print(f"[start] deepresearch-cli.py (Exa)", file=sys.stderr)
    print(f"[start] Topic:  {args.topic}", file=sys.stderr)
    print(f"[start] Depth:  {args.depth} ({len(queries)} queries)", file=sys.stderr)
    print(f"[start] Output: {output_path}", file=sys.stderr)

    if args.extend:
        print(
            "[compat] --extend accepted but not yet implemented; proceeding fresh.",
            file=sys.stderr,
        )

    batches = await run_parallel(queries, api_key, args.n_results)

    # Bail loudly if Exa rejected the key for any query
    if any(b.get("error") == "exa_unauthorized" for b in batches):
        print(
            "ERROR: Exa rejected the API key (401). Generate a new one at "
            "https://exa.ai/dashboard and update EXA_API_KEY.",
            file=sys.stderr,
        )
        sys.exit(3)

    sources: list[str] = []
    seen_urls: set[str] = set()
    for batch in batches:
        for r in batch["results"]:
            url = r["url"]
            if url not in seen_urls:
                seen_urls.add(url)
                sources.append(f"- {r['title'] or url} - {url}")

    elapsed = time.time() - t_start
    total_results = sum(len(b["results"]) for b in batches)
    print(
        f"[done] Pipeline complete in {elapsed:.1f}s "
        f"({len(queries)} queries, {total_results} results, {len(sources)} sources)",
        file=sys.stderr,
    )

    output = {
        "topic": args.topic,
        "queries": queries,
        "batches": batches,
        "sources": sources,
        "depth": args.depth,
        "total_results": total_results,
        "output_path": output_path,
        "plan_dir": str(pathlib.Path(args.plan_dir).resolve()) if args.plan_dir else None,
        "elapsed_seconds": round(elapsed, 1),
        "engine": "exa",
    }
    print(json.dumps(output, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
