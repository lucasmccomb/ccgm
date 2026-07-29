# orrery — Codebase System Map

STATUS: under construction. This is the Epic 1 scaffold: pinned toolchain, JSON contracts,
restricted scout agent, fixtures, and CI wiring. The `/orrery <repo>` build flow lands in a
later epic; the module completes in Epic 6.

orrery deep-dives any codebase with parallel read-only scout agents and generates an
interactive, zoomable, embeddable system-design map as a single self-contained HTML file:
4 zoom tiers (landscape → containers → components → key files), file-level GitHub links
pinned to an anchor SHA, connected external systems, and per-node product-context prose.
`/orrery update` refreshes the map incrementally against latest origin main.

## What Epic 1 ships

| Piece | Path |
|-------|------|
| Pinned LikeC4 toolchain (likec4@1.59.2 by lockfile, installed via `npm ci` - never npx) | `skills/orrery/scripts/toolchain/` |
| Toolchain entry point (cache by lockfile hash, prune stale caches, playwright passthrough) | `skills/orrery/scripts/likec4.sh` |
| Render step (build → rename to `{slug}.html` → cleanup → single-artifact assert) | `skills/orrery/scripts/render_map.sh` |
| Fragment / model JSON contracts | `skills/orrery/references/*.schema.json` |
| Restricted scout agent (Read/Grep/Glob only) | `agents/orrery-scout.md` |
| Deterministic fixtures (fictional acme-shop repo, golden model, broken model) | `tests/fixtures/` |
| Test suite (`ORRERY_STRICT=1` makes every layer required) | `tests/test-orrery.sh` |

## Embedding a generated map

A generated `dist/{slug}.html` is fully self-contained (no server, no external scripts).
Embed it with a sandboxed iframe:

```html
<iframe src="/maps/{slug}.html"
        sandbox="allow-scripts allow-popups allow-popups-to-escape-sandbox"
        style="width:100%;height:80vh;border:0" title="System map"></iframe>
```

Deliberately WITHOUT `allow-same-origin`: the artifact runs as an opaque origin with no access
to the host page's cookies or DOM. `allow-popups` is REQUIRED - the map's file-level GitHub
links open as `target="_blank"` and a popup-less sandbox blocks them outright.
`allow-popups-to-escape-sandbox` keeps the opened tab from inheriting the sandbox.

Publish safety: check the run report's repo-visibility line before publishing a map; for
`private`/`unknown` repos, do not publish without review.

## Manual install

Copy the module files to `~/.claude/`:

```bash
mkdir -p ~/.claude/skills/orrery ~/.claude/agents
cp -R modules/orrery/skills/orrery/* ~/.claude/skills/orrery/
cp modules/orrery/agents/orrery-scout.md ~/.claude/agents/
```

Or install via CCGM: `bash start.sh --add orrery`.

## Tests

```bash
# strict: pytest-absent / browser-absent / zero-tests-discovered are failures
ORRERY_STRICT=1 bash modules/orrery/tests/test-orrery.sh

# the browser layer needs the pinned playwright chromium once:
bash modules/orrery/skills/orrery/scripts/likec4.sh playwright install chromium
```

Requires Node >= 22.22.3 on PATH (likec4's engines floor; `likec4.sh` warns and proceeds
below it) and npm. All fixture content is fictional.
