"""error_classes.py - the one error classifier for autoheal (#1137).

failure-logger.py classifies each failure at capture; autoheal-aggregate.py
classifies stored rows again from their error text, so an improved
error_classes.json applies to old rows. Both call this module.

Config: $CCGM_ERROR_CLASSES, else error_classes.json next to this file.
Each class has a name and a regex (re.search, case-sensitive, first match
wins). "group_by_cmd_head": false marks a class whose cause does not depend on
the command (hook denials, harness refusals, shell quirks): the aggregator
then keys its signature on (tool, "", class) instead of splitting by command.
A missing or malformed file gives no classes and the default "other".
"""

from __future__ import annotations

import functools
import json
import os
import re

DEFAULT_CLASS = "other"


def _path() -> str:
    return os.environ.get("CCGM_ERROR_CLASSES") or os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "error_classes.json")


def load() -> tuple[list[tuple[str, "re.Pattern[str]", bool]], str]:
    """Return ([(name, compiled, group_by_cmd_head)], default_name)."""
    return _load(_path())


@functools.lru_cache(maxsize=8)
def _load(path: str) -> tuple[list[tuple[str, "re.Pattern[str]", bool]], str]:
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return [], DEFAULT_CLASS
    default = data.get("default") if isinstance(data, dict) else None
    entries = data.get("classes") if isinstance(data, dict) else None
    out = []
    for entry in entries if isinstance(entries, list) else []:
        if not isinstance(entry, dict):
            continue
        name, src = entry.get("name"), entry.get("regex")
        if not isinstance(name, str) or not isinstance(src, str):
            continue
        try:
            out.append((name, re.compile(src), entry.get("group_by_cmd_head") is not False))
        except re.error:
            continue
    return out, default if isinstance(default, str) else DEFAULT_CLASS


def classify(error: str) -> str:
    classes, default = load()
    for name, regex, _ in classes:
        if regex.search(error):
            return name
    return default


def groups_by_cmd_head(error_class: str) -> bool:
    """False when the class's signature should drop cmd_head. Unlisted classes split."""
    for name, _, split in load()[0]:
        if name == error_class:
            return split
    return True
