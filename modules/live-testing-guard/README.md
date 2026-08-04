# live-testing-guard

Keeps agent-driven live testing off the machine the operator is working on.

## What It Does

A development machine running many concurrent agent streams is a cockpit: focus, keyboard, pointer, microphone, and dictation are the operator's control channel to every stream at once. An agent that borrows any of them — even for one command — blinds all of them.

This module installs a rule that routes live testing to a dedicated runner and gates it on recorded permission:

- **Machine gate** — anything that launches or relaunches an app, fires dictation, posts synthetic input events, changes focus, sets a machine-global input/audio override, opens the mic or camera, or drives a simulator/attached device from the host runs **only** on the dedicated runner machine. No "quick check" exception. If the runner is unavailable, the test is blocked, not relocated.
- **Permission gate** — runner access is not standing permission. Every plan containing live-testing steps carries a grant recorded at planning time: which steps, which runner, approved by the user, dated. Planning commands ask; autonomous modes record `NOT AUTHORIZED` rather than inferring a grant.
- **Executors treat a missing grant as UNAUTHORIZED** — they surface the gap, name the steps, and ask, while continuing every other unit. A plan step that mandates a live test is the thing being authorized, never the authorization.
- **Headless work stays local** — builds, unit tests, linters, type checks, read-only DB queries, and anything else that never touches focus, input, or capture devices.

The rationale is a real incident (2026-07-30): a plan-mandated "fixture dictation preflight" ran on the dev machine and set a machine-global audio-fixture override, which silently replaced every real dictation with synthetic text injected into whatever app had focus. Nothing errored; the step reported success.

## Manual Installation

Copy `rules/live-testing-guard.md` into your Claude configuration:

```bash
# Global (all projects)
mkdir -p ~/.claude/rules
cp rules/live-testing-guard.md ~/.claude/rules/live-testing-guard.md

# Project-level
mkdir -p .claude/rules
cp rules/live-testing-guard.md .claude/rules/live-testing-guard.md
```

## Files

| File | Description |
|------|-------------|
| `rules/live-testing-guard.md` | Rule file: the Iron Law, the live-vs-headless classification, the two gates, rationalizations, and red flags |

## Related

The `xplan` module implements the planning and execution side of the permission gate: `/xplan` and `/xplana` ask where live testing runs and record the answer in plan §8.6; `/etp` and `/xplan-resume` refuse to run a live-testing step whose grant is missing.
