# Ask Context: Every Question Carries Its Own Context

**Iron Law:** NEVER ASK THE USER A QUESTION WHOSE CONTEXT THEY CANNOT SEE ON SCREEN. MID-WORKSTREAM, THE QUESTION PAYLOAD IS THE ONLY SURFACE THAT REACHES THEM VERBATIM.

A deterministic PreToolUse hook (`ask-context-gate.py`) hard-blocks (exit 2) AskUserQuestion calls that violate this. This rule explains the mental model so you get it right the first time instead of being bounced by the gate.

## The Visibility Model (Why This Keeps Going Wrong)

When you call AskUserQuestion, the user's screen shows:

| Surface | Visible? |
|---------|----------|
| The question payload — question text, option labels, option descriptions, previews | ✅ Always, verbatim |
| Plain response text that opens the turn (before your first tool call) or ends it | ✅ Yes (may require a brief scroll) |
| Plain response text you write between tool calls | ⚠️ Not reliably. On Claude Fable 5.1 the API delivers it as a progress update: Claude Code shows a one-line summary and records it as `thinking`; under the default API display it is empty |
| Your thinking blocks | ❌ Never |
| Raw tool output (git log, file reads, test runs) | ❌ Collapsed noise — not readable context |
| Anything from earlier turns or a subagent's context | ❌ Gone |

Two failures follow from this table. The classic one: you spend a long workstream reading files and running commands, form a clear picture *in thinking*, then ask "With that context: disposition for PR #2967?" — and the user sees a bare question pointing at context that exists only in your head. The newer one: you write a multi-paragraph brief right before the call, and the user gets one summarized sentence while the transcript gets a `thinking` block. In both cases **"I wrote it" is not "they saw it."** When the user answers "you didn't give me any context," re-sending the same payload repeats the failure.

## The Required Pattern

Before every AskUserQuestion call that follows tool work, put the context in the payload:

1. **Make the question text stand alone.** Name the thing (repo, PR number, file, symptom), say why the decision surfaced now, and restate the key evidence as 2-6 short facts — facts from tool output, never references to it ("PR #2967 fixes device rebinding; its picker bugs ship in every current build"). Assume nothing before the payload is on screen.
2. **Put each option's consequences in its `description`.** The description is guaranteed-visible real estate — use it for stakes, not adjectives.
3. **Use `preview` for bulky evidence** (code, diffs, mockups) that a description can't hold.
4. **Count response text only where it is delivered verbatim.** A brief that opens the turn (before any tool call) or ends it reaches the user; a brief written between tool calls may not. Do not rely on one to carry the context for a mid-workstream question.

The gate measures the payload as question text plus option descriptions plus previews. Labels and headers name a choice; they do not explain it.

## Banned Phrasings (the Gate Blocks These)

Question text and option descriptions must not point at the scrollback:

- "With that context…" / "Given the above…" / "Given this analysis…"
- "As described/shown/mentioned above" / "see above" / "per the above"
- "The analysis/findings/summary above" / "the context I provided"
- "In light of the above" / "based on my analysis above"

If you catch yourself writing one, the question is not self-contained. Inline the fact instead.

## Re-Ask Protocol (After the User Pushes Back)

If the user answers via Other with free text — especially anything like "what context?", "explain", "I don't have enough to decide" — or dismisses the question:

- **Never re-send the same payload.** The gate blocks identical re-asks after a free-text or dismissed response.
- Re-call with a **rewritten** payload that embeds the context and answers what they actually said.
- A previous identical question the user answered by **picking an offered option** may be asked again later (recurring approval loops are fine).

## Gate Mechanics

| Gate | Trigger | Fires when |
|------|---------|-----------|
| G1 Deictic | Payload only | Question/description references invisible context ("with that context", "see above", …) |
| G2 Repeat | Transcript | Identical question set re-asked after a free-text/dismissed/interrupted response |
| G3 Invisible context | Payload + transcript | ≥1 tool call since the user's last message AND the payload carries <200 chars of context (question + descriptions + previews) AND <200 chars of your text reached the transcript this turn (`ASK_CONTEXT_MIN_CHARS` overrides both) |

The transcript gates fail OPEN (unreadable transcript → allow); G1 always runs. A turn starts at the human's message: entries the harness appends as user messages — skill expansions, image companions, `<system-reminder>` wrappers, local-command output — do not start one. Escape hatch: `CCGM_ASK_CONTEXT_OFF=1` — for debugging the hook, never for skipping the context.

When the gate blocks you, do not fight it and do not rephrase cosmetically: move the context into the payload and re-call. The block message contains the exact recipe. Writing a brief between tool calls and re-calling does not pass, because that brief never reaches the transcript as text.

## Why the Transcript Is Not the Surface

Verified 2026-09-09 on Claude Code 2.1.267 with Claude Fable 5.1, against the raw Messages API and in live sessions. Between a tool result and the next tool call, text the model writes comes back from the API as a progress-update `thinking` block, not a `text` block: empty under the default display, a one- or two-sentence summary under `display: "summarized"` or `"updates"`. Claude Code requests `"updates"` for first-party sessions, renders the summary as a status line, and persists it as `thinking`. Only text that opens the turn or ends it is stored verbatim as `text`. A 1,100-character brief written before a question therefore reached the user as roughly 280 characters and the transcript as a thinking block, and a gate that counted `text` blocks blocked the well-behaved pattern twice in one run. Older models return between-tool-call text as `text` blocks, which is why the transcript count remains a second way to pass.

## Red Flags

Stop and move the context into the payload if you catch yourself:

- Calling AskUserQuestion straight out of a long tool-calling run with a short question and one-word descriptions
- Writing "with that context" or "as described above" in a question
- Writing a brief between tool calls and expecting the user, or the gate, to see it verbatim
- Re-sending an unchanged question after the user said they lack context
- Treating your thinking or collapsed tool output as "context I already gave"
- Padding the question with narration ("Let me ask you something…") instead of decision-relevant facts
