---
name: orrery
description: >
  Deep-dives a codebase with parallel read-only scout agents and generates an interactive,
  zoomable, embeddable system-design map as a single self-contained HTML file - file-level
  GitHub links pinned to an anchor SHA, external systems, and per-node product-context prose.
  UNDER CONSTRUCTION: Epic 1 ships the scaffold (pinned LikeC4 toolchain, schemas, fixtures,
  CI); the full /orrery build flow lands in Epic 4 and the update flow in Epic 5.
disable-model-invocation: true
---

# /orrery — under construction

The orrery module scaffold is in place (Epic 1): the pinned LikeC4 render/validate toolchain
(`scripts/likec4.sh`, `scripts/render_map.sh`), the fragment/model JSON contracts under
`references/`, the restricted `orrery-scout` agent definition, and the deterministic test
fixtures.

The orchestration flow this skill will run - anchor, enumerate, scout fan-out, merge, emit,
validate, render, teardown - is implemented in Epic 4 (`/orrery <repo>`) and Epic 5
(`/orrery update`). Until then this command only reports its own status.

If you invoked `/orrery` now, reply with:

> orrery is not built yet - the Epic 1 scaffold is installed, but the build flow lands in a
> later epic. Nothing was run against your repository.
