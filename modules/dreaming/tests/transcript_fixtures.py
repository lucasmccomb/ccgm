#!/usr/bin/env python3
"""Synthetic Claude Code transcript JSONL builders for the dreaming tests.

Every later composite-eligibility epic (E2 miner origin-fix, E3 session
verification / tier re-mining) needs synthetic transcripts whose *shape*
``transcript_miner.mine()`` actually parses. This module builds those shapes
programmatically instead of hand-authoring brittle JSONL blobs.

Everything here is 100% synthetic: default cwd is a fake
``/Users/testuser/code/example`` -- never a real username, path, or captured
transcript (public-repo rule, plan.md §1.4).

The line shapes match what ``transcript_miner.mine()`` reads at anchor
(``transcript_miner.py`` line-by-line ``obj`` handling):
  * top-level keys ``type``, ``sessionId``, ``uuid``, ``parentUuid``,
    ``timestamp``, ``cwd``, ``gitBranch``, ``version``;
  * ``message.role`` / ``message.content`` (a list of typed blocks);
  * assistant ``tool_use`` blocks (with ``message.usage`` token counts);
  * user ``tool_result`` blocks with ``is_error`` (+ optional
    ``toolUseResult.exit_code``) -> the miner's friction events;
  * a human "typed" user turn carries the origin markers Epic 2 filters on
    (``origin.kind == "human"`` and/or ``promptSource == "typed"``) that the
    miner does not read today; a ``tool_result`` turn deliberately omits them
    so the origin filter can distinguish real human corrections from synthetic
    tool-result echoes.

Turn builders return partial dicts (no session/cwd/uuid/timestamp);
:func:`build_transcript` wires those in and returns the full line-object list,
and :func:`write_transcript` serializes it to a ``.jsonl`` path.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

DEFAULT_CWD = "/Users/testuser/code/example"
DEFAULT_SESSION_ID = "fixture-session-0001"
DEFAULT_GIT_BRANCH = "main"
DEFAULT_VERSION = "2.1.198"
DEFAULT_BASE_TS = "2026-01-03T14:00:00.000Z"
DEFAULT_TS_STEP_SECONDS = 2


def iso(dt: datetime) -> str:
    """Render a datetime as the millisecond-precision UTC ISO string the
    transcript format uses (``...Z`` suffix)."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S") + f".{dt.microsecond // 1000:03d}Z"


def _parse_iso(ts: str) -> datetime:
    # Accept the "...Z" and millisecond forms this module emits.
    cleaned = ts.replace("Z", "+00:00")
    return datetime.fromisoformat(cleaned)


# ---------------------------------------------------------------------------
# Turn builders (partial dicts; assembled by build_transcript)
# ---------------------------------------------------------------------------


def user_turn(
    text: str,
    *,
    human: bool = True,
    prompt_source: str | None = None,
    origin_kind: str | None = None,
    ts: str | None = None,
) -> dict:
    """A ``type: "user"`` prose turn.

    ``human=True`` (default) marks the turn as operator-typed by attaching
    BOTH origin markers Epic 2 filters on: ``promptSource == "typed"`` and
    ``origin.kind == "human"``. Override ``prompt_source`` / ``origin_kind``
    explicitly to build the single-marker or missing-marker (fail-closed)
    variants Epic 2's tests need; passing ``human=False`` with neither
    override yields a user turn carrying NO origin markers.
    """
    if human:
        ps = "typed" if prompt_source is None else prompt_source
        ok = "human" if origin_kind is None else origin_kind
    else:
        ps = prompt_source
        ok = origin_kind
    turn: dict = {
        "type": "user",
        "text": text,
        "message": {"role": "user", "content": [{"type": "text", "text": text}]},
    }
    if ps is not None:
        turn["promptSource"] = ps
    if ok is not None:
        turn["origin"] = {"kind": ok}
    if ts is not None:
        turn["timestamp"] = ts
    return turn


def assistant_turn(
    text: str = "",
    *,
    tool_uses: list | None = None,
    usage: dict | None = None,
    ts: str | None = None,
) -> dict:
    """A ``type: "assistant"`` turn, optionally emitting ``tool_use`` blocks.

    ``tool_uses`` is a list of dicts ``{"id", "name", "input"}`` (``id`` and
    ``name`` default to ``tool_1`` / ``Bash``); each becomes a ``tool_use``
    content block a later ``tool_result`` turn can reference by id. ``usage``
    overrides the default token-count block the miner reads.
    """
    content: list = []
    if text:
        content.append({"type": "text", "text": text})
    for i, tu in enumerate(tool_uses or [], start=1):
        content.append(
            {
                "type": "tool_use",
                "id": tu.get("id", f"tool_{i}"),
                "name": tu.get("name", "Bash"),
                "input": tu.get("input", {}),
            }
        )
    if usage is None:
        usage = {
            "input_tokens": 300,
            "output_tokens": 40,
            "cache_creation_input_tokens": 0,
            "cache_read_input_tokens": 250,
        }
    turn: dict = {
        "type": "assistant",
        "text": text,
        "message": {"role": "assistant", "model": "claude-fixture-1", "content": content, "usage": usage},
    }
    if ts is not None:
        turn["timestamp"] = ts
    return turn


def tool_result_turn(
    *,
    tool_use_id: str = "tool_1",
    content: str = "",
    is_error: bool = False,
    exit_code: int | None = None,
    ts: str | None = None,
) -> dict:
    """A ``type: "user"`` turn carrying a ``tool_result`` block.

    This is NOT a human-typed turn: it deliberately omits origin markers, so
    Epic 2's origin filter treats a negation phrase appearing here (e.g. in
    echoed command output) as a non-correction. Set ``is_error=True`` and/or a
    non-zero ``exit_code`` to make the miner record a friction event for it.
    """
    block: dict = {"type": "tool_result", "tool_use_id": tool_use_id, "content": content}
    if is_error:
        block["is_error"] = True
    turn: dict = {
        "type": "user",
        "text": content,
        "message": {"role": "user", "content": [block]},
    }
    if exit_code is not None:
        turn["toolUseResult"] = {"exit_code": exit_code}
    if ts is not None:
        turn["timestamp"] = ts
    return turn


def friction_turn(
    *,
    tool_use_id: str = "tool_1",
    content: str = "command failed",
    exit_code: int = 1,
    ts: str | None = None,
) -> dict:
    """Convenience: a ``tool_result`` turn that the miner records as a
    ``tool_error`` friction event (``is_error`` + non-zero ``exit_code``)."""
    return tool_result_turn(
        tool_use_id=tool_use_id,
        content=content,
        is_error=True,
        exit_code=exit_code,
        ts=ts,
    )


def correction_sequence(
    *,
    request: str = "Reformat the config file to use tabs.",
    correction: str = "No, that's wrong, please revert that change entirely.",
    command: str = "sed -i 's/    /\\t/g' config.yaml",
    error: str = "sed: -i may not be used with stdin",
    tool_use_id: str = "tool_1",
    human_correction: bool = True,
) -> list:
    """A four-turn friction-then-correction sequence the miner mines into a
    ``user_correction``.

    Order: human request -> assistant tool_use -> tool_result error (friction)
    -> human correction (carrying a NEGATION_PHRASES match). ``correction``
    must contain a miner negation phrase (e.g. "that's wrong", "revert that")
    to be extracted. ``human_correction=False`` builds the sec-C1 regression
    shape: the negation phrase lands in a NON-human turn so the origin filter
    (Epic 2) drops it.
    """
    return [
        user_turn(request, human=True),
        assistant_turn(
            "Working on it.",
            tool_uses=[{"id": tool_use_id, "name": "Bash", "input": {"command": command}}],
        ),
        friction_turn(tool_use_id=tool_use_id, content=error, exit_code=1),
        user_turn(correction, human=human_correction),
    ]


# ---------------------------------------------------------------------------
# Assembly + serialization
# ---------------------------------------------------------------------------


def build_transcript(
    turns: list,
    *,
    session_id: str = DEFAULT_SESSION_ID,
    cwd: str = DEFAULT_CWD,
    git_branch: str = DEFAULT_GIT_BRANCH,
    version: str = DEFAULT_VERSION,
    base_ts: str = DEFAULT_BASE_TS,
    ts_step_seconds: int = DEFAULT_TS_STEP_SECONDS,
) -> list:
    """Wire per-line identity/metadata onto a list of turn dicts.

    Fills ``sessionId``, ``cwd``, ``gitBranch``, ``version``, a sequential
    ``uuid``/``parentUuid`` chain, and a ``timestamp`` for any turn that did
    not set one (``base_ts`` + ``ts_step_seconds`` per turn). Turn-level
    ``timestamp`` and ``cwd`` overrides are preserved, so a test can embed
    arbitrary per-line timestamps (recency) or a per-turn cwd (slug mismatch).
    The internal ``text`` helper key is stripped from the emitted objects.
    """
    base = _parse_iso(base_ts)
    lines: list = []
    prev_uuid: str | None = None
    for i, turn in enumerate(turns):
        obj = {k: v for k, v in turn.items() if k != "text"}
        obj.setdefault("sessionId", session_id)
        obj.setdefault("cwd", cwd)
        obj.setdefault("gitBranch", git_branch)
        obj.setdefault("version", version)
        obj.setdefault("uuid", f"u{i}")
        obj["parentUuid"] = prev_uuid
        if "timestamp" not in obj:
            obj["timestamp"] = iso(base + timedelta(seconds=ts_step_seconds * i))
        # Move type/sessionId/uuid to a stable leading order for readability;
        # JSON object key order does not affect the miner, but stable output
        # keeps fixtures diff-friendly.
        lines.append(obj)
        prev_uuid = obj["uuid"]
    return lines


def to_jsonl(lines: list) -> str:
    """Serialize built line objects to newline-delimited JSON text."""
    return "\n".join(json.dumps(obj, ensure_ascii=False) for obj in lines) + "\n"


def write_transcript(path: str | Path, turns: list, **kwargs) -> Path:
    """Build (via :func:`build_transcript`) and write a transcript to ``path``.

    Extra keyword args are forwarded to :func:`build_transcript` (session_id,
    cwd, base_ts, ...). Returns the ``Path`` written.
    """
    lines = build_transcript(turns, **kwargs)
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(to_jsonl(lines), encoding="utf-8")
    return p
