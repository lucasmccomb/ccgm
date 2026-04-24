#!/usr/bin/env python3
"""xplan-web-review.py - Local web UI for reviewing an xplan plan directory.

Renders plan.md (and sibling artifacts research.md / decisions.md / naming.md /
reviews/*.md) in the browser with section-level comment support. On Submit,
writes comments to {plan_dir}/comments.json and shuts down. The xplan
orchestrator then reads comments.json and runs a targeted Deepen Mode pass.

Usage:
  xplan-web-review.py <plan_dir> [--port PORT] [--no-open]

Exit codes:
  0  - User submitted comments or accepted the plan as-is
  1  - Server failed to launch (caller should fall back to text walkthrough)
  2  - Invalid plan directory

Fallback signals (caller should use text walkthrough):
  - Env var XPLAN_NO_WEB=1
  - Python exit code 1
  - $DISPLAY unset on Linux (approximate headless check)

Trust model:
  Server binds to 127.0.0.1 only. The rendered markdown (plan.md and siblings)
  is content this same user wrote or that xplan wrote into their own plan dir.
  It is NOT user-submitted content from an untrusted third party. The review
  UI uses marked.parse on this trusted content; inline HTML in markdown will
  render as HTML, same as any local markdown viewer. If a plan contains raw
  HTML, that is by the plan author's intent (diagrams, tables, etc.). We do
  escape text-derived values (section titles, toast messages) into DOM text
  nodes / attributes rather than interpolating them into innerHTML templates.

No runtime dependencies beyond stdlib. HTML uses marked.js via CDN.
"""

from __future__ import annotations

import argparse
import json
import os
import socket
import sys
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse


def is_headless() -> bool:
    """Approximate headless check. Returns True if the web UI should not launch."""
    if os.environ.get("XPLAN_NO_WEB") == "1":
        return True
    if sys.platform.startswith("linux") and not os.environ.get("DISPLAY"):
        return True
    return False


def find_free_port(preferred: int | None = None) -> int:
    if preferred:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("127.0.0.1", preferred))
                return preferred
            except OSError:
                pass
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def list_plan_files(plan_dir: Path) -> list[dict]:
    """Return a list of {name, path, kind} for every markdown file in the plan dir."""
    files: list[dict] = []
    top_level = ["plan.md", "research.md", "decisions.md", "naming.md", "progress.md"]
    for name in top_level:
        p = plan_dir / name
        if p.is_file():
            files.append({"name": name, "path": name, "kind": "main"})
    reviews_dir = plan_dir / "reviews"
    if reviews_dir.is_dir():
        for p in sorted(reviews_dir.glob("*.md")):
            files.append({"name": f"reviews/{p.name}", "path": f"reviews/{p.name}", "kind": "review"})
    return files


INDEX_HTML = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>xplan review</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<script src="https://cdn.jsdelivr.net/npm/marked/marked.min.js"></script>
<style>
  :root {
    --bg: #0e1116;
    --panel: #151a21;
    --border: #2a3038;
    --text: #e6edf3;
    --muted: #8b949e;
    --accent: #58a6ff;
    --accent-2: #3fb950;
    --danger: #f85149;
  }
  * { box-sizing: border-box; }
  body {
    margin: 0;
    font: 15px/1.55 ui-sans-serif, system-ui, -apple-system, "Segoe UI", sans-serif;
    background: var(--bg);
    color: var(--text);
    display: grid;
    grid-template-columns: 260px 1fr;
    grid-template-rows: auto 1fr auto;
    grid-template-areas:
      "header header"
      "sidebar main"
      "footer footer";
    min-height: 100vh;
  }
  header {
    grid-area: header;
    padding: 12px 20px;
    border-bottom: 1px solid var(--border);
    display: flex;
    align-items: center;
    gap: 16px;
  }
  header h1 { font-size: 16px; margin: 0; font-weight: 600; }
  header .meta { color: var(--muted); font-size: 13px; }
  nav {
    grid-area: sidebar;
    border-right: 1px solid var(--border);
    padding: 16px 10px;
    overflow-y: auto;
  }
  nav .file-list { display: flex; flex-direction: column; gap: 2px; margin-bottom: 20px; }
  nav .file-list button {
    text-align: left;
    background: transparent;
    color: var(--text);
    border: 1px solid transparent;
    border-radius: 6px;
    padding: 6px 10px;
    cursor: pointer;
    font: inherit;
  }
  nav .file-list button:hover { background: var(--panel); }
  nav .file-list button.active { background: var(--panel); border-color: var(--border); }
  nav .toc { font-size: 13px; color: var(--muted); }
  nav .toc a {
    display: block;
    color: var(--muted);
    text-decoration: none;
    padding: 3px 10px;
    border-radius: 4px;
  }
  nav .toc a:hover { color: var(--text); background: var(--panel); }
  nav .toc a.h3 { padding-left: 20px; font-size: 12px; }
  main {
    grid-area: main;
    padding: 24px 40px 80px 40px;
    overflow-y: auto;
    max-width: 960px;
  }
  main h1, main h2, main h3 { scroll-margin-top: 16px; }
  main h2, main h3 { position: relative; }
  main h2 .comment-btn, main h3 .comment-btn {
    position: absolute;
    left: -32px;
    top: 50%;
    transform: translateY(-50%);
    width: 24px;
    height: 24px;
    padding: 0;
    border-radius: 50%;
    border: 1px solid var(--border);
    background: var(--panel);
    color: var(--muted);
    cursor: pointer;
    font: inherit;
    font-size: 13px;
    display: inline-flex;
    align-items: center;
    justify-content: center;
  }
  main h2 .comment-btn:hover, main h3 .comment-btn:hover {
    color: var(--accent);
    border-color: var(--accent);
  }
  main h2 .comment-btn.has-comment, main h3 .comment-btn.has-comment {
    color: var(--accent-2);
    border-color: var(--accent-2);
  }
  .comment-box {
    margin: 8px 0 16px;
    padding: 10px 12px;
    background: var(--panel);
    border: 1px solid var(--border);
    border-left: 3px solid var(--accent);
    border-radius: 6px;
    display: none;
  }
  .comment-box.open { display: block; }
  .comment-box textarea {
    width: 100%;
    min-height: 70px;
    background: var(--bg);
    color: var(--text);
    border: 1px solid var(--border);
    border-radius: 4px;
    padding: 8px;
    font: inherit;
    resize: vertical;
  }
  .comment-box .row { display: flex; gap: 8px; margin-top: 8px; }
  .comment-box button {
    background: var(--bg);
    color: var(--text);
    border: 1px solid var(--border);
    border-radius: 4px;
    padding: 4px 10px;
    cursor: pointer;
    font: inherit;
    font-size: 13px;
  }
  .comment-box button.save { border-color: var(--accent-2); color: var(--accent-2); }
  .comment-box button.discard { border-color: var(--danger); color: var(--danger); }
  pre, code {
    font: 13px ui-monospace, "SF Mono", Consolas, monospace;
  }
  main pre {
    background: var(--panel);
    border: 1px solid var(--border);
    border-radius: 6px;
    padding: 12px;
    overflow-x: auto;
  }
  main code { background: var(--panel); padding: 1px 5px; border-radius: 3px; }
  main pre code { background: transparent; padding: 0; }
  main a { color: var(--accent); }
  main table {
    border-collapse: collapse;
    width: 100%;
    margin: 12px 0;
  }
  main th, main td {
    border: 1px solid var(--border);
    padding: 6px 10px;
    text-align: left;
  }
  main th { background: var(--panel); }
  main blockquote {
    border-left: 3px solid var(--border);
    padding-left: 12px;
    color: var(--muted);
    margin-left: 0;
  }
  footer {
    grid-area: footer;
    border-top: 1px solid var(--border);
    padding: 12px 20px;
    display: flex;
    justify-content: space-between;
    align-items: center;
    background: var(--panel);
  }
  footer .status { color: var(--muted); font-size: 13px; }
  footer .actions { display: flex; gap: 10px; }
  footer button {
    font: inherit;
    font-size: 14px;
    padding: 8px 18px;
    border-radius: 6px;
    cursor: pointer;
    border: 1px solid var(--border);
    background: var(--bg);
    color: var(--text);
  }
  footer button.primary {
    background: var(--accent);
    color: #001428;
    border-color: var(--accent);
    font-weight: 600;
  }
  footer button.secondary { border-color: var(--accent-2); color: var(--accent-2); }
  .toast {
    position: fixed;
    bottom: 80px;
    left: 50%;
    transform: translateX(-50%);
    background: var(--panel);
    border: 1px solid var(--accent-2);
    color: var(--text);
    padding: 10px 20px;
    border-radius: 8px;
    display: none;
  }
  .toast.show { display: block; }
</style>
</head>
<body>
<header>
  <h1 id="concept-title">xplan review</h1>
  <span class="meta" id="comment-count">0 comments</span>
</header>
<nav>
  <div class="file-list" id="file-list"></div>
  <div class="toc" id="toc"></div>
</nav>
<main id="content">Loading…</main>
<footer>
  <span class="status" id="status">Ready</span>
  <div class="actions">
    <button class="secondary" id="accept-btn">Accept as-is</button>
    <button class="primary" id="submit-btn">Submit for deepening</button>
  </div>
</footer>
<div class="toast" id="toast"></div>
<script>
  const FILES = __FILES_JSON__;
  const CONCEPT = __CONCEPT_JSON__;
  document.getElementById("concept-title").textContent = "xplan review: " + CONCEPT;

  const state = {
    currentFile: FILES[0]?.path || "plan.md",
    comments: {},
  };

  const fileListEl = document.getElementById("file-list");
  const tocEl = document.getElementById("toc");
  const contentEl = document.getElementById("content");
  const countEl = document.getElementById("comment-count");
  const statusEl = document.getElementById("status");
  const toastEl = document.getElementById("toast");

  FILES.forEach(f => {
    const btn = document.createElement("button");
    btn.textContent = f.name;
    btn.dataset.path = f.path;
    btn.onclick = () => loadFile(f.path);
    fileListEl.appendChild(btn);
  });

  function updateFileListActive() {
    fileListEl.querySelectorAll("button").forEach(b => {
      b.classList.toggle("active", b.dataset.path === state.currentFile);
    });
  }

  function toast(msg, ms = 2000) {
    toastEl.textContent = msg;
    toastEl.classList.add("show");
    setTimeout(() => toastEl.classList.remove("show"), ms);
  }

  function updateCount() {
    const total = Object.values(state.comments)
      .flat()
      .filter(c => c && c.text && c.text.trim()).length;
    countEl.textContent = total === 1 ? "1 comment" : `${total} comments`;
  }

  function anchorFor(file, title) {
    return `${file}::${title}`;
  }

  function attachCommentButtons(file) {
    const headings = contentEl.querySelectorAll("h2, h3");
    const tocItems = [];
    headings.forEach(h => {
      const title = h.textContent.trim();
      const level = h.tagName.toLowerCase();
      const anchor = anchorFor(file, title);
      const id = "section-" + anchor.replace(/[^a-zA-Z0-9-]/g, "-");
      h.id = id;
      tocItems.push({ id, title, level });

      const btn = document.createElement("button");
      btn.className = "comment-btn";
      btn.textContent = "+";
      btn.title = `Comment on: ${title}`;
      btn.onclick = (e) => {
        e.preventDefault();
        const box = h.nextElementSibling?.classList?.contains("comment-box")
          ? h.nextElementSibling
          : createCommentBox(h, file, title, anchor);
        box.classList.toggle("open");
        if (box.classList.contains("open")) {
          box.querySelector("textarea").focus();
        }
      };

      const existing = (state.comments[anchor] || [])[0];
      if (existing && existing.text?.trim()) {
        btn.classList.add("has-comment");
        const box = createCommentBox(h, file, title, anchor);
        box.querySelector("textarea").value = existing.text;
      }

      h.prepend(btn);
    });

    tocEl.innerHTML = "";
    tocItems.forEach(item => {
      const a = document.createElement("a");
      a.href = `#${item.id}`;
      a.textContent = item.title;
      if (item.level === "h3") a.className = "h3";
      tocEl.appendChild(a);
    });
  }

  function createCommentBox(heading, file, title, anchor) {
    const box = document.createElement("div");
    box.className = "comment-box";

    const ta = document.createElement("textarea");
    ta.placeholder = `What would you like to change about: ${title}`;

    const row = document.createElement("div");
    row.className = "row";

    const saveBtn = document.createElement("button");
    saveBtn.className = "save";
    saveBtn.textContent = "Save";

    const discardBtn = document.createElement("button");
    discardBtn.className = "discard";
    discardBtn.textContent = "Discard";

    row.appendChild(saveBtn);
    row.appendChild(discardBtn);
    box.appendChild(ta);
    box.appendChild(row);
    heading.insertAdjacentElement("afterend", box);

    saveBtn.onclick = () => {
      const text = ta.value.trim();
      if (!text) {
        delete state.comments[anchor];
      } else {
        state.comments[anchor] = [{
          anchor,
          file,
          section_title: title,
          text,
          ts: new Date().toISOString(),
          status: "pending",
        }];
      }
      const btn = heading.querySelector(".comment-btn");
      btn.classList.toggle("has-comment", !!text);
      box.classList.remove("open");
      updateCount();
      toast(text ? "Comment saved" : "Comment cleared");
    };
    discardBtn.onclick = () => {
      ta.value = "";
      delete state.comments[anchor];
      heading.querySelector(".comment-btn").classList.remove("has-comment");
      box.classList.remove("open");
      updateCount();
    };
    return box;
  }

  async function loadFile(path) {
    state.currentFile = path;
    updateFileListActive();
    statusEl.textContent = `Loading ${path}...`;
    try {
      const resp = await fetch(`/raw/${path}`);
      if (!resp.ok) throw new Error(`${resp.status}`);
      const md = await resp.text();
      // Trust model note: plan.md and siblings are local trusted content this user
      // (or xplan running as this user) wrote into ~/code/plans/{concept}/. Rendering
      // inline HTML in markdown is expected behavior for a local markdown viewer.
      contentEl.innerHTML = marked.parse(md);
      attachCommentButtons(path);
      statusEl.textContent = `Viewing ${path}`;
    } catch (e) {
      contentEl.textContent = `Failed to load ${path}: ${e.message}`;
      statusEl.textContent = "Load error";
    }
  }

  async function submitReview(endpoint, payload) {
    statusEl.textContent = "Submitting...";
    try {
      const resp = await fetch(endpoint, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      if (!resp.ok) throw new Error(`${resp.status}`);
      statusEl.textContent = "Submitted. You can close this tab.";
      document.getElementById("submit-btn").disabled = true;
      document.getElementById("accept-btn").disabled = true;
      toast("Submitted. Return to your terminal.", 5000);
    } catch (e) {
      statusEl.textContent = `Submit failed: ${e.message}`;
      toast(`Submit failed: ${e.message}`, 5000);
    }
  }

  document.getElementById("submit-btn").onclick = () => {
    const flat = Object.values(state.comments).flat().filter(c => c && c.text?.trim());
    if (flat.length === 0) {
      toast("No comments. Use 'Accept as-is' instead.", 3000);
      return;
    }
    submitReview("/submit", { action: "deepen", comments: flat });
  };

  document.getElementById("accept-btn").onclick = () => {
    submitReview("/accept", { action: "accept", comments: [] });
  };

  loadFile(state.currentFile);
</script>
</body>
</html>
"""


class PlanHandler(BaseHTTPRequestHandler):
    plan_dir: Path = Path()
    concept: str = ""
    result_holder: dict = {}

    def log_message(self, format, *args):
        pass

    def _send(self, status: int, body: bytes, content_type: str = "text/plain; charset=utf-8"):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _safe_path(self, rel: str) -> Path | None:
        """Resolve rel within plan_dir; return None if escape is attempted."""
        candidate = (self.plan_dir / rel).resolve()
        try:
            candidate.relative_to(self.plan_dir.resolve())
        except ValueError:
            return None
        return candidate

    def do_GET(self):
        parsed = urlparse(self.path)
        path = unquote(parsed.path)

        if path == "/":
            files = list_plan_files(self.plan_dir)
            html = (
                INDEX_HTML
                .replace("__FILES_JSON__", json.dumps(files))
                .replace("__CONCEPT_JSON__", json.dumps(self.concept))
            )
            self._send(200, html.encode("utf-8"), "text/html; charset=utf-8")
            return

        if path.startswith("/raw/"):
            rel = path[len("/raw/"):]
            target = self._safe_path(rel)
            if not target or not target.is_file() or target.suffix != ".md":
                self._send(404, b"not found")
                return
            self._send(200, target.read_bytes(), "text/markdown; charset=utf-8")
            return

        if path == "/health":
            self._send(200, b"ok")
            return

        self._send(404, b"not found")

    def do_POST(self):
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length) if length else b""
        try:
            payload = json.loads(body.decode("utf-8"))
        except Exception:
            self._send(400, b"invalid json")
            return

        parsed = urlparse(self.path)
        path = parsed.path

        if path == "/submit":
            comments = payload.get("comments", [])
            self._write_comments(comments, action="deepen")
            self._send(200, b'{"ok":true}', "application/json")
            self.result_holder["action"] = "deepen"
            self.result_holder["comment_count"] = len(comments)
            self.result_holder["done"] = True
            return

        if path == "/accept":
            self._write_comments([], action="accept")
            self._send(200, b'{"ok":true}', "application/json")
            self.result_holder["action"] = "accept"
            self.result_holder["comment_count"] = 0
            self.result_holder["done"] = True
            return

        self._send(404, b"not found")

    def _write_comments(self, comments: list, action: str):
        out = {
            "action": action,
            "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "concept": self.concept,
            "comments": comments,
        }
        (self.plan_dir / "comments.json").write_text(json.dumps(out, indent=2))


def serve(plan_dir: Path, port: int, open_browser: bool) -> dict:
    PlanHandler.plan_dir = plan_dir
    PlanHandler.concept = plan_dir.name
    PlanHandler.result_holder = {"done": False}

    httpd = ThreadingHTTPServer(("127.0.0.1", port), PlanHandler)
    url = f"http://127.0.0.1:{port}/"

    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    print(f"xplan-web-review: serving {plan_dir} at {url}", file=sys.stderr)

    if open_browser:
        try:
            webbrowser.open(url)
        except Exception as e:
            print(f"xplan-web-review: could not open browser ({e}); open {url} manually", file=sys.stderr)

    try:
        while not PlanHandler.result_holder.get("done"):
            time.sleep(0.2)
    except KeyboardInterrupt:
        PlanHandler.result_holder["action"] = "interrupted"
    finally:
        time.sleep(0.3)
        httpd.shutdown()
        httpd.server_close()

    return PlanHandler.result_holder


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("plan_dir", type=str, help="Path to the plan directory (contains plan.md)")
    parser.add_argument("--port", type=int, default=None, help="Port to bind (default: auto-detect free port)")
    parser.add_argument("--no-open", action="store_true", help="Do not auto-open the browser")
    args = parser.parse_args()

    if is_headless():
        print("xplan-web-review: headless environment (XPLAN_NO_WEB or no $DISPLAY); skipping", file=sys.stderr)
        return 1

    plan_dir = Path(args.plan_dir).expanduser().resolve()
    if not plan_dir.is_dir():
        print(f"xplan-web-review: not a directory: {plan_dir}", file=sys.stderr)
        return 2
    if not (plan_dir / "plan.md").is_file():
        print(f"xplan-web-review: no plan.md in {plan_dir}", file=sys.stderr)
        return 2

    try:
        port = find_free_port(args.port)
    except OSError as e:
        print(f"xplan-web-review: could not bind a port ({e})", file=sys.stderr)
        return 1

    try:
        result = serve(plan_dir, port, open_browser=not args.no_open)
    except Exception as e:
        print(f"xplan-web-review: server error ({e})", file=sys.stderr)
        return 1

    action = result.get("action", "interrupted")
    count = result.get("comment_count", 0)
    print(json.dumps({"action": action, "comment_count": count}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
