"""Static checks for bin/ccgm-md-page. The browser checks live in md_page_e2e.js."""
import html
import json
import os
import re
import stat
import subprocess
import sys
from pathlib import Path

MODULE = Path(__file__).resolve().parent.parent
TOOL = MODULE / "bin" / "ccgm-md-page"
FIXTURES = MODULE / "tests" / "fixtures"


def render(tmp_path, fixture, *args, env=None):
    src = tmp_path / fixture
    src.write_text((FIXTURES / fixture).read_text(encoding="utf-8"), encoding="utf-8")
    out = tmp_path / "out.html"
    proc = subprocess.run(
        [sys.executable, str(TOOL), str(src), "-o", str(out), *args],
        capture_output=True, text=True, env=env,
    )
    return proc, out


def script_tags(page):
    return re.findall(r"<script\b[^>]*\bsrc=[^>]*>", page)


def test_tool_is_executable():
    assert TOOL.stat().st_mode & stat.S_IXUSR


def test_every_remote_script_has_integrity_and_crossorigin(tmp_path):
    proc, out = render(tmp_path, "mermaid.md")
    assert proc.returncode == 0, proc.stderr
    tags = script_tags(out.read_text(encoding="utf-8"))
    assert len(tags) == 3
    for tag in tags:
        assert re.search(r'integrity="sha384-[A-Za-z0-9+/=]+"', tag), tag
        assert 'crossorigin="anonymous"' in tag, tag
        # exact version in the URL, no "latest" or bare package name
        assert re.search(r"\d+\.\d+\.\d+", tag), tag


def test_scripts_come_from_pinned_cdn_hosts(tmp_path):
    _, out = render(tmp_path, "mermaid.md")
    for tag in script_tags(out.read_text(encoding="utf-8")):
        assert re.search(
            r'src="https://(cdnjs\.cloudflare\.com/ajax/libs|cdn\.jsdelivr\.net/npm)/', tag
        ), tag


def test_mermaid_script_only_with_a_mermaid_block(tmp_path):
    _, out = render(tmp_path, "basic.md")
    assert "mermaid" not in "".join(script_tags(out.read_text(encoding="utf-8")))
    _, out = render(tmp_path, "mermaid.md")
    assert "mermaid" in "".join(script_tags(out.read_text(encoding="utf-8")))


def test_plain_page_loads_marked_and_dompurify_only(tmp_path):
    _, out = render(tmp_path, "basic.md")
    assert len(script_tags(out.read_text(encoding="utf-8"))) == 2


def test_json_block_has_no_raw_script_close(tmp_path):
    proc, out = render(tmp_path, "xss.md")
    assert proc.returncode == 0, proc.stderr
    page = out.read_text(encoding="utf-8")
    m = re.search(r'<script id="md-src" type="application/json">(.*?)</script>', page, re.S)
    assert m, "markdown JSON block missing"
    body = m.group(1)
    assert "</script" not in body.lower()
    assert "<" not in body
    assert json.loads(body) == (FIXTURES / "xss.md").read_text(encoding="utf-8")


def test_noscript_copy_is_escaped(tmp_path):
    _, out = render(tmp_path, "xss.md")
    page = out.read_text(encoding="utf-8")
    m = re.search(r"<noscript><pre[^>]*>(.*?)</pre></noscript>", page, re.S)
    assert m, "noscript fallback missing"
    assert "<" not in m.group(1)
    assert html.unescape(m.group(1)) == (FIXTURES / "xss.md").read_text(encoding="utf-8")


def test_default_output_sits_next_to_input_and_path_is_printed(tmp_path):
    src = tmp_path / "report.md"
    src.write_text("# Hi\n", encoding="utf-8")
    proc = subprocess.run([sys.executable, str(TOOL), str(src)], capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip() == str(tmp_path / "report.html")
    assert (tmp_path / "report.html").exists()


def test_title_flag_and_heading_fallback(tmp_path):
    _, out = render(tmp_path, "basic.md")
    assert "<title>Release Report</title>" in out.read_text(encoding="utf-8")
    _, out = render(tmp_path, "basic.md", "--title", "A <b>title</b>")
    assert "<title>A &lt;b&gt;title&lt;/b&gt;</title>" in out.read_text(encoding="utf-8")


def test_missing_input_exits_nonzero(tmp_path):
    proc = subprocess.run(
        [sys.executable, str(TOOL), str(tmp_path / "nope.md")], capture_output=True, text=True
    )
    assert proc.returncode != 0
    assert "nope.md" in proc.stderr


def test_never_opens_the_page(tmp_path):
    fake = tmp_path / "fakebin"
    fake.mkdir()
    marker = tmp_path / "opened"
    for name in ("open", "xdg-open"):
        f = fake / name
        f.write_text(f"#!/bin/sh\ntouch {marker}\n")
        f.chmod(0o755)
    env = dict(os.environ, PATH=f"{fake}:{os.environ['PATH']}")
    proc, _ = render(tmp_path, "basic.md", env=env)
    assert proc.returncode == 0
    assert not marker.exists()


def test_narrow_screen_and_theme_hooks_present(tmp_path):
    _, out = render(tmp_path, "basic.md")
    page = out.read_text(encoding="utf-8")
    assert 'name="viewport"' in page
    assert "prefers-color-scheme" in page
    assert "overflow-x" in page
