# Ask Context: Every Question Carries Its Own Context

Never ask the user a question whose context they cannot see on screen. Mid-workstream, the question payload is the only surface that reaches them verbatim. A PreToolUse hook (`ask-context-gate.py`) blocks (exit 2) AskUserQuestion calls that violate this.

## What the User Sees

| Surface | Visible? |
|---------|----------|
| The question payload: question text, option labels, option descriptions, previews | Always, verbatim |
| Plain response text that opens the turn (before the first tool call) or ends it | Yes |
| Response text written between tool calls | Not reliably. On Fable 5.1 it arrives as a one-line progress summary and is stored as `thinking` |
| Thinking blocks | Never |
| Raw tool output | Collapsed, not readable context |
| Earlier turns or a subagent's context | Gone |

Two failures follow. The classic one: a long workstream forms a clear picture in thinking, then asks "disposition for PR #2967?" and the user sees a bare question. The newer one: a multi-paragraph brief written right before the call reaches the user as one summarized sentence. In both cases "I wrote it" is not "they saw it."

## The Required Pattern

Before any AskUserQuestion that follows tool work, put the context in the payload:

1. **Make the question text stand alone.** Name the thing (repo, PR number, file, symptom), say why the decision surfaced now, and restate the key evidence as 2 to 6 short facts from tool output, never references to it.
2. **Put each option's consequences in its `description`.** That field is guaranteed-visible; use it for stakes, not adjectives.
3. **Use `preview` for bulky evidence** (code, diffs, mockups).
4. **Count response text only where it is delivered verbatim**: turn-opening or turn-ending text. A brief written between tool calls may not reach the user.

The gate measures the payload as question text plus option descriptions plus previews. Labels and headers name a choice; they do not explain it.

## Banned Phrasings

Question text and option descriptions must not point at the scrollback: "with that context", "given the above", "given this analysis", "as described/shown/mentioned above", "see above", "per the above", "the analysis/findings/summary above", "the context I provided", "in light of the above", "based on my analysis above". Inline the fact instead.

## Re-Ask Protocol

If the user answers via Other with free text (especially "what context?", "explain", "I don't have enough to decide") or dismisses the question, never re-send the same payload; the gate blocks identical re-asks after a free-text or dismissed response. Re-call with a rewritten payload that embeds the context and answers what they said. A question the user answered by picking an offered option may be asked again later.

## Gate Mechanics

| Gate | Trigger | Fires when |
|------|---------|-----------|
| G1 Deictic | Payload only | Question or description references invisible context |
| G2 Repeat | Transcript | Identical question set re-asked after a free-text, dismissed, or interrupted response |
| G3 Invisible context | Payload + transcript | At least one tool call since the user's last message, the payload carries under 200 chars of context, and under 200 chars of your text reached the transcript this turn (`ASK_CONTEXT_MIN_CHARS` overrides both) |

The transcript gates fail open (unreadable transcript allows); G1 always runs. A turn starts at the human's message; harness-appended user messages (skill expansions, image companions, system-reminder wrappers, local-command output) do not start one. `CCGM_ASK_CONTEXT_OFF=1` disables the hook for debugging it, never for skipping the context.

When the gate blocks, move the context into the payload and re-call; the block message contains the recipe. Writing a brief between tool calls and re-calling does not pass, because that brief never reaches the transcript as text.
