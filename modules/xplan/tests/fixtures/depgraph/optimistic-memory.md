## 5. Agent-Epics

Epic headings, Wave and Dependencies bullets transcribed from a real plan.


### Epic 1: Dwell-window store lifecycle
- **Wave:** 1
- **Dependencies:** None

### Epic 2: Per-op-kind posture policy + config + proposal fields
- **Wave:** 1
- **Dependencies:** None (parallel-safe with Epic 1 — different files)

### Epic 3: Optimistic auto-integration engine + blast caps + batch anomaly + circuit breaker
- **Wave:** 2
- **Dependencies:** Epic 1 (dwell field/stamp), Epic 2 (posture/config)

### Epic 4: Eval-gate extension + poisoning negative-control fixtures
- **Wave:** 2
- **Dependencies:** Epic 2 (posture) — parallel-safe with Epic 3 (different files: `eval/`)

### Epic 5: Daily integrated-memories report + delivery
- **Wave:** 3
- **Dependencies:** Epic 3 (produces `auto_applied` rows + `batch_id` + `dwell_until`)

### Epic 6: Post-hoc review + rollback command surface
- **Wave:** 3
- **Dependencies:** Epic 3 (state to review), Epic 1 (dwelling rows to list)
- **Dependencies note:** parallel-safe with Epic 5/7 (distinct files: command md + sync bin).

### Epic 7: Weekly scorecard extension
- **Wave:** 3
- **Dependencies:** Epic 3 (state), Epic 1 (dwelling rows)
- **Dependencies note:** parallel-safe with Epic 5/6 (distinct file: `scorecard.py`).

### Epic 8: Migration, config flip, rule + docs updates
- **Wave:** 4
- **Dependencies:** Epics 1–7 (documents/migrates the finished behavior)
