# orrery — Codebase System Map

orrery deep-dives any codebase with parallel read-only scout agents and generates an
interactive, zoomable, embeddable system-design map as a single self-contained HTML file:
4 zoom tiers (landscape → containers → components → key files), file-level GitHub links
pinned to an anchor SHA, connected external systems, and per-node prose that explains why
each piece exists for the product. `/orrery update` refreshes an existing map against the
latest default branch.

Every deterministic step (anchoring, census, merge, emit, validation, secret screening,
render) is a tested script; the scouts only investigate. The map is generated, never
hand-drawn, so it cannot rot.

## Install

Part of the `full` preset. Standalone:

```bash
bash start.sh --add orrery
```

Or copy the module files to `~/.claude/`:

```bash
mkdir -p ~/.claude/skills/orrery ~/.claude/agents
cp -R modules/orrery/skills/orrery/* ~/.claude/skills/orrery/
cp modules/orrery/agents/orrery-scout.md ~/.claude/agents/
```

Requirements: Node >= 22.22.3 with npm (the LikeC4 toolchain installs itself from the
checked-in lockfile — never npx), `python3`, `git`, network access to the target repo's
origin, and `gh` (optional — without it repo visibility reports `unknown`).

## Usage

```
/orrery                          # map the repo you are currently in (the primary form)
/orrery <repo>                   # a path, or a bare name tried at ~/code/{name}
/orrery update [<repo>]          # refresh an existing map incrementally
/orrery --vision <file>          # local file with product context for the scouts
/orrery --out <dir>              # output directory (default: $ORRERY_HOME/{slug})
```

- **`/orrery` with no argument** maps the repo containing the current working directory.
- **`/orrery update`** re-anchors, diffs the recorded anchor SHA against the new one
  (ancestry-checked, rename-aware), re-investigates only the affected areas, and re-runs
  the same merge → validate → render chain. A pure rename preserves element continuity
  and can complete with no re-investigation at all; an unchanged repo reports "up to
  date" and stops. If `state.json` is missing at the resolved output root, the update
  STOPS and names the path it searched — a map built with a custom `--out` needs that
  same `--out` passed to update; it never rebuilds at a root it merely guessed.
  Rewritten history, an unparseable `state.json`, or a schema/toolchain version mismatch
  falls back to a full rebuild with a clear message.
- **`--vision`** takes a LOCAL file only; a URL is rejected, never fetched. Without it,
  the product-vision scout reads the repo's own README/docs.
- **`$ORRERY_HOME`** overrides the output root (default `~/code/orrery`) without editing
  the module.

## Output layout

```
$ORRERY_HOME/{slug}/
  state.json        # build baseline: anchor SHA, areas, element→file index (drives update)
  fragments/        # one JSON fragment per scout pack from this build
  model/            # emitted LikeC4 model (.c4 files + likec4.config.json)
  dist/{slug}.html  # the artifact — one self-contained file
```

The directory is created `chmod 700`. The run report also names `merge-report.json`
(quarantined/withheld items) and, on a failed validation, `errors.json`.

## Embedding a generated map

`dist/{slug}.html` is fully self-contained — no server, no external scripts. Copy it into
your site's public assets (e.g. `public/maps/`) and embed it with a sandboxed iframe:

```html
<iframe src="/maps/{slug}.html"
        sandbox="allow-scripts allow-popups allow-popups-to-escape-sandbox"
        style="width:100%;height:80vh;border:0" title="System map"></iframe>
```

Deliberately WITHOUT `allow-same-origin`: the artifact runs as an opaque origin with no
access to the host page's cookies or DOM. `allow-popups` is REQUIRED — the map renders
every file-level GitHub link as `target="_blank"`, and a popup-less sandbox blocks those
navigations outright, killing the map's headline feature.
`allow-popups-to-escape-sandbox` keeps the opened GitHub tab from inheriting the sandbox.

**Landing link**: the artifact opens at `#/`, an overview grid of all views. Link
`{slug}.html#/view/index/` instead to land on the L1 landscape view.

**Webcomponent alternative**: LikeC4 can also build the map as a webcomponent for
embedding without an iframe. The sandboxed iframe is the recommended path — the sandbox
is the publish-safety boundary between repo-derived content and your site.

## Scope & limits

- **v1 boundary: ~2,000 investigable files / 24 area buckets.** Sibling directories are
  bin-packed into at most 24 investigation areas; repos whose candidate count defies
  useful bucketing at 24 (giant monorepos) are outside the v1 boundary.
- **Navigation model**: drill-down across the 4 zoom tiers plus pan/zoom within each
  view. Zoom is view-to-view navigation, not one infinite canvas.
- **Source links are GitHub-only, by design.** A GitLab, Bitbucket, self-hosted, or
  no-remote repo gets a complete map with no file links — never fabricated ones.
- **Private-repo links 404 for public viewers.** The map's GitHub links point at the
  source repo; viewers without access to it get 404s even when the map itself is public.
- **Cross-area edges are element-level in v1** — relations connect components and files,
  not aggregated area-to-area rollups.
- **`/orrery` mutates the target repo**: it runs `git fetch origin` and creates a
  temporary worktree pinned to the anchor SHA. The worktree is always removed — on
  success, on BLOCKED, and on every early exit; a run that leaves one behind is a failed
  run. Because the freshness guard is a real fetch, the run needs network access and
  read credentials for origin — there is no offline mode in v1.
- **Typical artifact size is ~3-11 MB** depending on element count. The run report states
  the exact byte size.

## Publish safety

- **Visibility warning**: the run report states the source repo's visibility (`public`,
  `private`, or `unknown`). For `private` or `unknown` it warns "do not publish this
  artifact without review" directly beside the embed snippet. Treat `unknown` as private.
- **Secret quarantine**: content matching secret patterns is withheld at merge time and
  never reaches the artifact. The report's withheld count (from `merge-report.json`)
  tells you something secret-shaped was found in the repo — review the named items
  before publishing anything.
- **If a secret was in a previously generated map**: delete `~/code/orrery/{slug}/`
  (or your `--out` directory) and rebuild after fixing the source. The old artifact,
  fragments, and state all carry the leaked value; purge the directory, do not patch it.
- All repo-derived prose is HTML-entity-escaped at emit, and the sandboxed iframe keeps
  the artifact in an opaque origin. Both apply unconditionally.

## Troubleshooting

- **`errors.json`**: a failed validation (exit 1) writes `errors.json` beside
  `model.json` with per-error message/file/line. The run applies a bounded fix loop (at
  most 3 iterations); if errors remain, it reports BLOCKED with the `errors.json` path.
  A green validation removes any stale `errors.json`.
- **BLOCKED**: the run stopped without rendering — an invalid model is never rendered.
  The report names the failing stage and the evidence file. The worktree teardown still
  ran; re-run `/orrery` after addressing the cause.
- **Node below 22.22.3**: `likec4.sh` warns and proceeds (likec4's declared engines
  floor; validate and build measured working on 22.17.0). Remediation:
  `nvm install 22 && nvm use 22`, or `brew install node@22`.
- **`gh` absent or the remote is not GitHub**: visibility reports `unknown`. The build
  still works; the report carries the do-not-publish-without-review warning.

## Tests

```bash
# strict: pytest-absent / browser-absent / zero-tests-discovered are failures
ORRERY_STRICT=1 bash modules/orrery/tests/test-orrery.sh

# the browser layer needs the pinned playwright chromium once:
bash modules/orrery/skills/orrery/scripts/likec4.sh playwright install chromium
```

CI runs this suite (unit tests plus the E2E chains: validate gate, golden render,
embed-in-browser, joined ingest, pipeline, and the snippet-string assertion) on every PR.
One residual is out of CI's reach by design: latent investigation quality — what the
scouts write about an arbitrary repo. CI cannot run live subagents, so that surface is
gated per-run by `validate_map.py` (structure, anchoring, links, screening) and was
proven once end-to-end by the live acceptance demo on a real repo. No surface is left to
manual testing.

All fixture content is fictional (the `acme-shop` repo).
