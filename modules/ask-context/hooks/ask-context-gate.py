#!/usr/bin/env python3
"""
PreToolUse hook that HARD-BLOCKS AskUserQuestion calls whose decision context
is invisible to the user.

Why: mid-workstream, an agent asks a multiple-choice question believing it has
already provided the supporting context — but that context lives in its
thinking blocks (never rendered) or in collapsed tool output. The user's screen
shows a bare question like "With that context: disposition for PR #2967?" and
nothing else. When the user replies "you didn't give me any context" via the
Other field, the agent re-presents the identical question, because nothing
forces the context onto a visible surface. An advisory rule cannot fix this:
the agent genuinely believes the context was shown. Only a deterministic gate
that measures the visible surfaces can.

At question time the user is guaranteed to see exactly two surfaces:
  (a) the AskUserQuestion payload itself — question text, option labels,
      option descriptions, previews; and
  (b) plain assistant text emitted since the user's last real message.
Thinking is invisible. Raw tool output is collapsed noise. This hook enforces
that at least one of those surfaces actually carries the context.

Classification: bypass-retained. Denials use exit 2 (the semantics of
hook_utils.hard_block(), inlined here so the hook is dependency-free and works
under both the symlink install and the plugin projection).

THREE GATES, in order:

  G1 — DEICTIC REFERENCE (payload-only, always on)
    Blocks when the question text or an option description references context
    that is not in the payload: "with that context", "as described above",
    "the analysis above", "see above", "given the above", etc. A question that
    points at the scrollback is not self-contained by definition.

  G2 — IDENTICAL RE-ASK (transcript-based)
    Blocks re-presenting a question set identical to a previous ask that the
    user answered in their own words (Other free text), rejected, or never
    answered. That is the observed loop: user says "no context", agent re-asks
    verbatim. A previous identical ask answered with an OFFERED option label
    stays allowed — recurring approval questions in loop workflows are
    legitimate.

  G3 — INVISIBLE CONTEXT (transcript-based)
    Blocks when the agent is mid-workstream (>= 1 tool call since the user's
    last real message) but has emitted fewer than MIN_VISIBLE_CHARS of visible
    assistant text this turn. Whatever analysis exists is in thinking or tool
    results the user cannot read; a visible context brief must be written
    first. A question asked as the first action after a user message is exempt
    — the user's own message is the context.

ALLOWS:
  - Any tool other than AskUserQuestion (defensive; the matcher already scopes)
  - CCGM_ASK_CONTEXT_OFF=1 in the environment (escape hatch / debugging)
  - Payloads that pass G1 when the transcript is missing or unparseable —
    the transcript gates FAIL OPEN; a gate that cannot read the session must
    not brick it. G1 needs only the payload, so it always runs.

The block messages are the real mechanism: each one tells the model exactly
how to recover (emit a visible context brief as plain text, then re-call with
a self-contained question), so the retry lands correctly without the user
having to prompt for context ever again.

Every content block in a Claude Code transcript is its own JSONL entry
(assistant text, thinking, and tool_use flush as separate lines, before the
tool executes), which is what makes the transcript gates possible at
PreToolUse time. The current call's own tool_use entry is usually already
flushed; both transcript gates exclude the final entry matching the current
tool_input so the hook never trips on its own call.
"""

from __future__ import annotations

import json
import os
import re
import sys

DEFAULT_MIN_VISIBLE_CHARS = 200

# Phrasings that reference context outside the payload. Deliberately narrow:
# every pattern is a pure pointer at the scrollback ("above", "that context",
# "the analysis I gave"), never a phrase with a legitimate self-contained use.
DEICTIC_PATTERNS = [
    r"\bwith\s+(?:all\s+)?(?:that|this)\s+(?:context|analysis)\b",
    r"\bwith\s+the\s+(?:above|prior|earlier)\s+(?:context|analysis)\b",
    r"\bgiven\s+(?:the\s+)?above\b",
    r"\bgiven\s+(?:that|this)\s+(?:context|analysis)\b",
    r"\b(?:as|per)\s+(?:described|shown|mentioned|discussed|noted|outlined|summarized|explained|detailed)\s+(?:above|earlier|previously)\b",
    r"\bsee\s+above\b",
    r"\bper\s+the\s+above\b",
    r"\bbased\s+on\s+(?:the|my)\s+(?:above|(?:analysis|context|findings|summary)\s+above)\b",
    r"\bthe\s+(?:context|analysis|details?|findings|summary|evidence)\s+(?:above|below)\b",
    r"\b(?:context|analysis|details?|findings|summary|evidence)\s+i\s+(?:just\s+)?(?:provided|gave|shared|showed|outlined)\b",
    r"\bin\s+light\s+of\s+the\s+above\b",
]
DEICTIC_RE = re.compile("|".join(DEICTIC_PATTERNS), re.IGNORECASE)

ANSWERED_MARKER = "Your questions have been answered"
REJECTED_MARKER = "doesn't want to proceed"


def hard_block(message: str) -> None:
    """Exit-2 denial: stderr is fed back to the model as the tool error."""
    sys.stderr.write(message)
    sys.exit(2)


# ─── Payload helpers ─────────────────────────────────────────────────────────


def iter_question_strings(tool_input):
    """Yield (where, text) for every user-visible string in the payload."""
    questions = tool_input.get("questions")
    if not isinstance(questions, list):
        return
    for q in questions:
        if not isinstance(q, dict):
            continue
        text = q.get("question")
        if isinstance(text, str):
            yield "question", text
        options = q.get("options")
        if not isinstance(options, list):
            continue
        for opt in options:
            if isinstance(opt, dict) and isinstance(opt.get("description"), str):
                yield "option description", opt["description"]


def normalized_question_set(tool_input):
    """Whitespace/case-normalized question texts, order-independent."""
    out = []
    questions = tool_input.get("questions")
    if isinstance(questions, list):
        for q in questions:
            if isinstance(q, dict) and isinstance(q.get("question"), str):
                out.append(re.sub(r"\s+", " ", q["question"]).strip().lower())
    return tuple(sorted(out))


def option_labels(tool_input):
    """All offered option labels across every question in a payload."""
    labels = []
    questions = tool_input.get("questions")
    if isinstance(questions, list):
        for q in questions:
            if not isinstance(q, dict):
                continue
            for opt in q.get("options") or []:
                if isinstance(opt, dict) and isinstance(opt.get("label"), str):
                    labels.append(opt["label"])
    return labels


# ─── Transcript parsing ──────────────────────────────────────────────────────


def load_main_chain(transcript_path):
    """Parse the transcript JSONL into main-chain user/assistant entries.

    Returns None when the transcript cannot be read at all (fail open).
    Individual malformed lines are skipped; sidechain (subagent) entries and
    non-message entry types are dropped.
    """
    if not transcript_path:
        return None
    try:
        with open(transcript_path, "r", encoding="utf-8", errors="replace") as fh:
            lines = fh.read().splitlines()
    except OSError:
        return None
    entries = []
    for line in lines:
        if not line.strip():
            continue
        try:
            entry = json.loads(line)
        except (json.JSONDecodeError, ValueError):
            continue
        if not isinstance(entry, dict):
            continue
        if entry.get("isSidechain") is True:
            continue
        if entry.get("type") not in ("user", "assistant"):
            continue
        entries.append(entry)
    return entries


def content_blocks(entry):
    content = (entry.get("message") or {}).get("content")
    if isinstance(content, list):
        return [b for b in content if isinstance(b, dict)]
    return []


def is_real_user_message(entry):
    """True for a message the USER authored — not a tool_result envelope."""
    if entry.get("type") != "user":
        return False
    content = (entry.get("message") or {}).get("content")
    if isinstance(content, str):
        return bool(content.strip())
    if isinstance(content, list):
        return any(
            isinstance(b, dict) and b.get("type") in ("text", "image")
            for b in content
        )
    return False


def collect_asks(entries):
    """All AskUserQuestion tool_use blocks, in order: (index, id, input)."""
    asks = []
    for i, entry in enumerate(entries):
        if entry.get("type") != "assistant":
            continue
        for block in content_blocks(entry):
            if block.get("type") == "tool_use" and block.get("name") == "AskUserQuestion":
                tin = block.get("input")
                if isinstance(tin, dict):
                    asks.append((i, block.get("id"), tin))
    return asks


def drop_current_call(asks, tool_input):
    """Remove the final flushed occurrence of the in-flight call, if present."""
    current = json.dumps(tool_input, sort_keys=True)
    if asks and json.dumps(asks[-1][2], sort_keys=True) == current:
        return asks[:-1]
    return asks


def find_result_text(entries, start_index, tool_use_id):
    """The tool_result string for a tool_use id, or None if never answered."""
    if not tool_use_id:
        return None
    for entry in entries[start_index + 1:]:
        if entry.get("type") != "user":
            continue
        for block in content_blocks(entry):
            if block.get("type") != "tool_result" or block.get("tool_use_id") != tool_use_id:
                continue
            content = block.get("content")
            if isinstance(content, str):
                return content
            if isinstance(content, list):
                parts = [
                    c.get("text", "")
                    for c in content
                    if isinstance(c, dict) and c.get("type") == "text"
                ]
                return "\n".join(parts)
            return ""
    return None


def answered_with_offered_option(result_text, prev_input):
    """True iff every question was answered by picking an offered label.

    The harness renders answers as: Your questions have been answered:
    "<question>"="<answer>", ... — an answer that matches an offered option
    label means the user accepted the framing; anything else (Other free text)
    means they pushed back. Unrecognized formats return True (fail open —
    never block on a format guess).
    """
    if ANSWERED_MARKER not in result_text:
        return True
    if '="' not in result_text:
        return True
    labels = option_labels(prev_input)
    if not labels:
        return True
    questions = prev_input.get("questions") or []
    for q in questions:
        if not isinstance(q, dict):
            continue
        q_labels = [
            opt["label"]
            for opt in (q.get("options") or [])
            if isinstance(opt, dict) and isinstance(opt.get("label"), str)
        ]
        if not q_labels:
            continue
        if not any('="{}"'.format(label) in result_text for label in q_labels):
            return False
    return True


def current_turn(entries):
    """Entries after the user's last real message (the whole list if none)."""
    for i in range(len(entries) - 1, -1, -1):
        if is_real_user_message(entries[i]):
            return entries[i + 1:]
    return entries


def turn_visibility(turn_entries, tool_input):
    """(visible_text_chars, prior_tool_use_count) for the current turn.

    The in-flight AskUserQuestion is usually already flushed as the turn's
    final tool_use; it is excluded from the prior-tool count.
    """
    visible_chars = 0
    tool_uses = []
    for entry in turn_entries:
        if entry.get("type") != "assistant":
            continue
        for block in content_blocks(entry):
            btype = block.get("type")
            if btype == "text":
                visible_chars += len((block.get("text") or "").strip())
            elif btype == "tool_use":
                tool_uses.append(block)
    current = json.dumps(tool_input, sort_keys=True)
    for block in reversed(tool_uses):
        if (
            block.get("name") == "AskUserQuestion"
            and json.dumps(block.get("input"), sort_keys=True) == current
        ):
            tool_uses.remove(block)
            break
    return visible_chars, len(tool_uses)


# ─── Gates ───────────────────────────────────────────────────────────────────


def gate_deictic(tool_input):
    for where, text in iter_question_strings(tool_input):
        match = DEICTIC_RE.search(text)
        if match:
            hard_block(
                "ASK-CONTEXT GATE: this {where} references context the user "
                "cannot see (matched: \"{phrase}\").\n\n"
                "The user's screen shows ONLY (a) this question payload and "
                "(b) plain text you emitted since their last message. Your "
                "thinking is invisible and raw tool output is collapsed — "
                "\"I analyzed it\" is not \"they saw it\".\n\n"
                "Fix, in order:\n"
                "1. Emit a visible context brief as normal response text: what "
                "is being decided, why it surfaced now, and the key evidence "
                "restated in 2-6 short bullets.\n"
                "2. Re-call AskUserQuestion with the question text rewritten "
                "to stand alone — name the thing (repo, PR number, symptom), "
                "no \"above\", no \"that context\" — and put each option's "
                "consequences in its description.".format(
                    where=where, phrase=match.group(0)
                )
            )


def gate_repeat(entries, tool_input):
    asks = drop_current_call(collect_asks(entries), tool_input)
    wanted = normalized_question_set(tool_input)
    if not wanted:
        return
    for index, tool_use_id, prev_input in reversed(asks):
        if normalized_question_set(prev_input) != wanted:
            continue
        result_text = find_result_text(entries, index, tool_use_id)
        if result_text is None:
            reason = "the question was interrupted before they answered"
        elif REJECTED_MARKER in result_text:
            reason = "they dismissed it"
        elif not answered_with_offered_option(result_text, prev_input):
            reason = (
                "they answered in their own words instead of picking an "
                "option — usually a request for more context"
            )
        else:
            return  # answered by picking an offered option: re-asks are fine
        hard_block(
            "ASK-CONTEXT GATE: you already asked this exact question and "
            "{reason}. Re-presenting the identical question ignores their "
            "reply.\n\n"
            "Fix: first emit a visible context brief as normal response text "
            "(what is being decided, key evidence in 2-6 bullets, what each "
            "option implies), then re-call AskUserQuestion with a REWRITTEN "
            "question that embeds that context and addresses what the user "
            "actually said. Never re-send an unchanged payload after the user "
            "pushed back on it.".format(reason=reason)
        )


def gate_invisible_context(entries, tool_input, min_visible):
    turn = current_turn(entries)
    visible_chars, prior_tools = turn_visibility(turn, tool_input)
    if prior_tools >= 1 and visible_chars < min_visible:
        hard_block(
            "ASK-CONTEXT GATE: you are mid-workstream ({tools} tool call(s) "
            "since the user's last message) but have emitted only {chars} "
            "characters of visible text this turn. The context for this "
            "question exists only in your thinking and collapsed tool output "
            "— the user cannot see any of it.\n\n"
            "Fix: emit a visible context brief as normal response text FIRST "
            "— what is being decided, why it surfaced now, the key evidence "
            "restated in 2-6 short bullets, and what each option implies — "
            "then re-call AskUserQuestion. The question text itself must also "
            "stand alone (name the thing; assume the brief may have scrolled)."
            .format(tools=prior_tools, chars=visible_chars)
        )


# ─── Entry point ─────────────────────────────────────────────────────────────


def main():
    try:
        data = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        sys.exit(0)
    if not isinstance(data, dict) or data.get("tool_name") != "AskUserQuestion":
        sys.exit(0)
    if os.environ.get("CCGM_ASK_CONTEXT_OFF") == "1":
        sys.exit(0)
    tool_input = data.get("tool_input")
    if not isinstance(tool_input, dict):
        sys.exit(0)

    # G1 needs only the payload — always runs.
    gate_deictic(tool_input)

    entries = load_main_chain(data.get("transcript_path"))
    if entries is None:
        sys.exit(0)  # fail open: no transcript, no transcript gates

    gate_repeat(entries, tool_input)

    try:
        min_visible = int(os.environ.get("ASK_CONTEXT_MIN_CHARS", DEFAULT_MIN_VISIBLE_CHARS))
    except ValueError:
        min_visible = DEFAULT_MIN_VISIBLE_CHARS
    gate_invisible_context(entries, tool_input, min_visible)

    sys.exit(0)


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception:
        # Fail open: a gate that crashes must not brick the session.
        sys.exit(0)
