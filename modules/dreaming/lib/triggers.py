#!/usr/bin/env python3
"""Deterministic trigger matcher for dreaming proposals (#1098 Phase 3.4).

Every `learning_add` / `learning_supersede` proposal carries a `trigger`: a
small matcher that fires on the situation the learning is about. The
finalizer checks it against the proposal's own cited evidence; the Phase 4
recurrence metric will import `matches()` to scan later transcripts.

Schema:  {"kind": <kind>, "value": <value>}

    kind             value           fires when the text...
    ---------------  --------------  ----------------------------------------
    regex            string          matches the regex (re.search, ignoring
                                     case, multiline)
    command_prefix   string          contains the command at a word boundary
                                     (whitespace-normalised, so "git branch
                                     -D" fires on "cd r && git  branch -D x")
    path_glob        string          contains a path token that fnmatch-es the
                                     glob, as a whole token or by basename
    phrase_set       list of string  contains any phrase, ignoring case

`matches(trigger, text)` is pure and never raises: an invalid trigger or a
non-string text never matches. Callers feed it whatever text they scan (an
evidence excerpt, a Bash command, a tool error).

A trigger that would fire on nearly anything ("*", ".*", a one-letter regex)
is invalid, so "matches its own evidence" says something.
"""
from __future__ import annotations

import fnmatch
import re
from typing import Any, Iterable

TRIGGER_KINDS = ("regex", "command_prefix", "path_glob", "phrase_set")

MAX_REGEX_CHARS = 200
MIN_LITERAL_CHARS = 3  # regex source, phrase, and command_prefix floor
MIN_GLOB_LITERAL_CHARS = 2
# Scan at most this much of one text, so a model-written regex cannot be
# handed a transcript-sized string.
MAX_TEXT_CHARS = 20_000

# A group holding a quantifier, itself quantified: (a+)+, (.*)*, (a|b+){2,}
_NESTED_QUANTIFIER_RE = re.compile(r"\((?:[^()\\]|\\.)*[+*](?:[^()\\]|\\.)*\)[+*{]")
_PATH_TOKEN_SPLIT_RE = re.compile(r"[\s\"'`<>(),;=]+")


def _compile_regex(value: Any) -> tuple[re.Pattern[str] | None, str | None]:
    if not isinstance(value, str):
        return None, "regex value must be a string"
    if len(value) < MIN_LITERAL_CHARS:
        return None, f"regex must be at least {MIN_LITERAL_CHARS} characters"
    if len(value) > MAX_REGEX_CHARS:
        return None, f"regex must be at most {MAX_REGEX_CHARS} characters"
    if _NESTED_QUANTIFIER_RE.search(value):
        return None, "regex has a nested quantifier"
    try:
        compiled = re.compile(value, re.IGNORECASE | re.MULTILINE)
    except re.error as exc:
        return None, f"regex does not compile: {exc}"
    if compiled.search(""):
        return None, "regex matches the empty string"
    return compiled, None


def validate_trigger(trigger: Any) -> str | None:
    """None when `trigger` is a usable matcher, else a one-line reason."""
    if not isinstance(trigger, dict):
        return "trigger must be an object with kind and value"
    kind = trigger.get("kind")
    if kind not in TRIGGER_KINDS:
        return f"trigger kind must be one of {list(TRIGGER_KINDS)}, got {kind!r}"
    if "value" not in trigger:
        return "trigger is missing value"
    value = trigger["value"]
    if kind == "regex":
        return _compile_regex(value)[1]
    if kind == "phrase_set":
        if not isinstance(value, list) or not value:
            return "phrase_set value must be a non-empty list of strings"
        for phrase in value:
            if not isinstance(phrase, str) or len(phrase.strip()) < MIN_LITERAL_CHARS:
                return f"every phrase must be a string of at least {MIN_LITERAL_CHARS} characters"
        return None
    if not isinstance(value, str):
        return f"{kind} value must be a string"
    if kind == "command_prefix":
        if len(" ".join(value.split())) < 2:
            return "command_prefix must be at least 2 characters"
        return None
    # path_glob
    if len(re.sub(r"[*?\[\]]", "", value).strip()) < MIN_GLOB_LITERAL_CHARS:
        return "path_glob needs at least 2 non-wildcard characters"
    return None


def _normalize_space(text: str) -> str:
    return " ".join(text.split())


def matches(trigger: Any, text: Any) -> bool:
    """True iff `trigger` is valid and fires on `text`. Never raises."""
    if not isinstance(text, str) or validate_trigger(trigger) is not None:
        return False
    text = text[:MAX_TEXT_CHARS]
    kind, value = trigger["kind"], trigger["value"]
    if kind == "regex":
        compiled, _ = _compile_regex(value)
        return bool(compiled and compiled.search(text))
    if kind == "phrase_set":
        lowered = text.lower()
        return any(phrase.strip().lower() in lowered for phrase in value)
    if kind == "command_prefix":
        pattern = r"(?<![\w-])" + re.escape(_normalize_space(value))
        return re.search(pattern, _normalize_space(text)) is not None
    # path_glob
    for token in _PATH_TOKEN_SPLIT_RE.split(text):
        token = token.rstrip(".:!?")
        if token and (fnmatch.fnmatchcase(token, value) or fnmatch.fnmatchcase(token.rsplit("/", 1)[-1], value)):
            return True
    return False


def matches_any(trigger: Any, texts: Iterable[Any]) -> bool:
    """True iff `trigger` fires on at least one of `texts`."""
    return any(matches(trigger, t) for t in texts)
