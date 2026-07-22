# Ask Context: Every Question Carries Its Own Context

**Iron Law:** NEVER ASK THE USER A QUESTION WHOSE CONTEXT THEY CANNOT SEE ON SCREEN. THE QUESTION PAYLOAD AND YOUR VISIBLE TEXT ARE THE ONLY SURFACES THAT EXIST.

A deterministic PreToolUse hook (`ask-context-gate.py`) hard-blocks (exit 2) AskUserQuestion calls that violate this. This rule explains the mental model so you get it right the first time instead of being bounced by the gate.

## The Visibility Model (Why This Keeps Going Wrong)

When you call AskUserQuestion, the user's screen shows exactly two things:

| Surface | Visible? |
|---------|----------|
| The question payload — question text, option labels, option descriptions, previews | ✅ Always |
| Plain response text you emitted since the user's last message | ✅ Yes (may require a brief scroll) |
| Your thinking blocks | ❌ Never |
| Raw tool output (git log, file reads, test runs) | ❌ Collapsed noise — not readable context |
| Anything from earlier turns or a subagent's context | ❌ Gone |

The recurring failure: you spend a long workstream reading files and running commands, form a clear picture *in thinking*, then ask "With that context: disposition for PR #2967?" — and the user sees a bare question pointing at context that exists only in your head. When they answer "you didn't give me any context," re-sending the same payload repeats the failure. **"I analyzed it" is not "they saw it."**

## The Required Pattern

Before every AskUserQuestion call that follows tool work:

1. **Emit a visible context brief** as normal response text (not thinking):
   - What is being decided, in one sentence
   - Why it surfaced now (what you found)
   - Key evidence restated in 2-6 short bullets — restate facts from tool output, never reference it ("PR #2967 fixes device rebinding; its picker bugs ship in every current build")
   - What each choice implies
2. **Make the question text stand alone.** Name the thing: repo, PR number, file, symptom. Assume the brief may scroll away.
3. **Put per-option consequences in each option's `description`.** The description is guaranteed-visible real estate — use it for stakes, not adjectives.
4. **Use `preview` for bulky evidence** (code, diffs, mockups) that a description can't hold.

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
- Write the visible context brief first, then a **rewritten** question that embeds the context and responds to what they actually said.
- A previous identical question the user answered by **picking an offered option** may be asked again later (recurring approval loops are fine).

## Gate Mechanics

| Gate | Trigger | Fires when |
|------|---------|-----------|
| G1 Deictic | Payload only | Question/description references invisible context ("with that context", "see above", …) |
| G2 Repeat | Transcript | Identical question set re-asked after a free-text/dismissed/interrupted response |
| G3 Invisible context | Transcript | ≥1 tool call since the user's last message AND <200 chars of visible text this turn (`ASK_CONTEXT_MIN_CHARS` overrides) |

The transcript gates fail OPEN (unreadable transcript → allow); G1 always runs. Escape hatch: `CCGM_ASK_CONTEXT_OFF=1` — for debugging the hook, never for skipping the brief.

When the gate blocks you, do not fight it and do not rephrase cosmetically: write the brief, rewrite the question, re-call. The block message contains the exact recipe.

## Red Flags

Stop and write the brief if you catch yourself:

- Calling AskUserQuestion straight out of a long tool-calling run with no visible text this turn
- Writing "with that context" or "as described above" in a question
- Re-sending an unchanged question after the user said they lack context
- Treating your thinking or collapsed tool output as "context I already gave"
- Padding the question with narration ("Let me ask you something…") instead of decision-relevant facts
