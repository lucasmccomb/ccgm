# ask-context

Hard enforcement that every AskUserQuestion the agent asks carries visible decision context. A deterministic PreToolUse hook blocks the question **before it renders** whenever the supporting context exists only in the agent's thinking blocks or collapsed tool output — the two surfaces the user can never read.

## The Failure This Prevents

Mid-workstream, an agent runs a long chain of tool calls, forms a clear picture *in its thinking*, then asks: **"With that context: disposition for PR #2967?"** — and the user's screen shows a bare question pointing at context that was never displayed. When the user answers (via Other) "you didn't give me any context," the agent — which genuinely believes it provided context — re-presents the identical question. Advisory rules cannot fix a false belief; only a gate that measures the visible surfaces can.

At question time the user sees exactly two things: the question payload itself (question text, option labels/descriptions, previews) and plain assistant text emitted since their last message. Thinking is invisible. Raw tool output is collapsed noise.

## What This Module Does

Installs `ask-context-gate.py`, a PreToolUse hook wired (via settings.json merge) to AskUserQuestion. Three gates, each an exit-2 hard block whose message contains the exact recovery recipe (emit a visible context brief, then re-ask self-contained):

| Gate | Basis | Blocks |
|------|-------|--------|
| **G1 Deictic** | Payload only — always runs | Question text or option descriptions referencing invisible context: "with that context", "given the above", "as described above", "see above", "the analysis above", … |
| **G2 Repeat** | Transcript | Re-presenting a question set identical to a prior ask the user answered in free text (Other), dismissed, or never answered. Prior asks answered by picking an offered option label stay allowed — recurring approval questions in loop workflows are legitimate. |
| **G3 Invisible context** | Transcript | Asking mid-workstream (≥1 tool call since the user's last real message) with fewer than 200 visible characters of assistant text this turn (`ASK_CONTEXT_MIN_CHARS` overrides). First-action questions right after a user message are exempt — the user's own message is the context. |

Transcript parsing details: every content block in a Claude Code transcript flushes as its own JSONL line before the tool executes, so the gates can see the current turn at PreToolUse time. Sidechain (subagent) entries are ignored; the in-flight call's own flushed `tool_use` entry is excluded so the hook never trips on itself.

### Fail-Open Contract

- Missing/unreadable transcript → transcript gates (G2/G3) stand down; G1 still runs (payload-only)
- Malformed transcript lines → skipped individually
- Any unexpected exception → allow (a UX gate must never brick a session)
- Escape hatch: `CCGM_ASK_CONTEXT_OFF=1` — for debugging the hook, not for skipping the brief

## Files

| File | Type | Description |
|------|------|-------------|
| `hooks/ask-context-gate.py` | hook | The PreToolUse gate (dependency-free, stdlib only) |
| `rules/ask-context.md` | rule | The visibility model, required ask pattern, banned phrasings, re-ask protocol |
| `settings.partial.json` | config (merge) | PreToolUse wiring for AskUserQuestion |

## Manual Installation

```bash
cp modules/ask-context/hooks/ask-context-gate.py ~/.claude/hooks/
cp modules/ask-context/rules/ask-context.md ~/.claude/rules/
# Merge modules/ask-context/settings.partial.json into ~/.claude/settings.json
# (adds a PreToolUse matcher for AskUserQuestion)
```

Or via the installer: `bash start.sh --add ask-context`

## Testing

```bash
bash modules/ask-context/tests/test-ask-context-gate.sh
```

20 cases: deictic blocks (question + option description), first-action exemption, in-flight self-exclusion, mid-workstream dark blocks, visible-brief passes, sidechain text exclusion, repeat-after-free-text / rejection / interruption blocks, offered-option re-ask allowance, escape hatch, fail-open on missing/malformed transcripts, threshold override.
