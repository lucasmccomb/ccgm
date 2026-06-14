#!/usr/bin/env python3
"""Validate the CCGM marketplace + plugin manifests (issue #703).

CI runs `claude plugin validate` when the Claude Code CLI is available. When it
is not (the common CI case), this script provides an equivalent structural
check against the documented marketplace.json / plugin.json schemas:

  https://docs.claude.com/en/docs/claude-code/plugin-marketplaces  (marketplace)
  https://docs.claude.com/en/docs/claude-code/plugins-reference    (plugin)

It is intentionally dependency-free (stdlib only) and portable (macOS BSD +
Linux). It validates the SHAPE of the manifests, not the runtime behavior of the
plugins, so it stays meaningful even where `claude` cannot run.

Checks:
  marketplace.json
    - required: name (kebab-case string), owner.name (string), plugins (array)
    - name not in the reserved-Anthropic set
    - metadata.pluginRoot, when present, is a string
    - each plugin entry: name (kebab-case) + source; relative-path sources start
      with "./"; the resolved plugin directory exists and has plugin.json
  each plugin.json
    - required: name (kebab-case string)
    - keywords, when present, is an array (a string would fail at load)
    - hooks, when present, is an object
    - declared component paths (commands/agents/skills/...) are relative + ./
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]

KEBAB = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")

# From the official marketplace schema "Reserved names" note.
RESERVED_MARKETPLACE_NAMES = {
    "claude-code-marketplace",
    "claude-code-plugins",
    "claude-plugins-official",
    "claude-plugins-community",
    "claude-community",
    "anthropic-marketplace",
    "anthropic-plugins",
    "agent-skills",
    "anthropic-agent-skills",
    "knowledge-work-plugins",
    "life-sciences",
    "claude-for-legal",
    "claude-for-financial-services",
    "financial-services-plugins",
}

# Plugin manifest fields that hold component paths; each must be relative + ./.
PATH_FIELDS = (
    "skills",
    "commands",
    "agents",
    "outputStyles",
)


class Result:
    def __init__(self) -> None:
        self.errors: "list[str]" = []
        self.checks = 0

    def check(self, cond: bool, msg: str) -> None:
        self.checks += 1
        if not cond:
            self.errors.append(msg)


def _load(path: Path) -> "dict | None":
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        return None  # caller reports; keep exc out of signature for simplicity


def _is_kebab(val) -> bool:
    return isinstance(val, str) and bool(KEBAB.match(val))


def _check_path_field(r: Result, where: str, field: str, value) -> None:
    vals = value if isinstance(value, list) else [value]
    for v in vals:
        if not isinstance(v, str):
            r.check(False, f"{where}: {field} entry must be a string, got {type(v).__name__}")
            continue
        r.check(v.startswith("./"), f"{where}: {field} path '{v}' must start with './'")
        r.check(".." not in v, f"{where}: {field} path '{v}' must not traverse outside plugin root")


def validate_plugin(r: Result, plugin_path: Path) -> None:
    where = str(plugin_path.relative_to(REPO_ROOT))
    data = _load(plugin_path)
    if data is None:
        r.check(False, f"{where}: not valid JSON")
        return
    r.check(isinstance(data, dict), f"{where}: top level must be an object")
    if not isinstance(data, dict):
        return

    r.check(_is_kebab(data.get("name")), f"{where}: 'name' must be kebab-case string")

    if "keywords" in data:
        r.check(isinstance(data["keywords"], list), f"{where}: 'keywords' must be an array")
    if "hooks" in data:
        r.check(isinstance(data["hooks"], (dict, str, list)),
                f"{where}: 'hooks' must be object, array, or path string")

    for field in PATH_FIELDS:
        if field in data:
            _check_path_field(r, where, field, data[field])


def validate_marketplace(r: Result, market_path: Path) -> "list[str]":
    """Validate marketplace.json. Returns list of plugin-source dirs to recurse."""
    where = str(market_path.relative_to(REPO_ROOT))
    data = _load(market_path)
    if data is None:
        r.check(False, f"{where}: not valid JSON")
        return []
    r.check(isinstance(data, dict), f"{where}: top level must be an object")
    if not isinstance(data, dict):
        return []

    name = data.get("name")
    r.check(_is_kebab(name), f"{where}: 'name' must be kebab-case string")
    r.check(name not in RESERVED_MARKETPLACE_NAMES,
            f"{where}: 'name' '{name}' is a reserved Anthropic marketplace name")

    owner = data.get("owner")
    r.check(isinstance(owner, dict) and isinstance(owner.get("name"), str),
            f"{where}: 'owner.name' is required and must be a string")

    plugins = data.get("plugins")
    r.check(isinstance(plugins, list), f"{where}: 'plugins' must be an array")

    plugin_root = "."
    metadata = data.get("metadata")
    if isinstance(metadata, dict) and "pluginRoot" in metadata:
        pr = metadata["pluginRoot"]
        r.check(isinstance(pr, str), f"{where}: metadata.pluginRoot must be a string")
        if isinstance(pr, str):
            plugin_root = pr

    plugin_manifests: "list[str]" = []
    if not isinstance(plugins, list):
        return plugin_manifests

    seen: "set[str]" = set()
    market_root = market_path.parent.parent  # repo root (.claude-plugin/..)
    for i, entry in enumerate(plugins):
        tag = f"{where} plugins[{i}]"
        if not isinstance(entry, dict):
            r.check(False, f"{tag}: must be an object")
            continue
        pname = entry.get("name")
        r.check(_is_kebab(pname), f"{tag}: 'name' must be kebab-case string")
        r.check(pname not in seen, f"{tag}: duplicate plugin name '{pname}'")
        if isinstance(pname, str):
            seen.add(pname)

        source = entry.get("source")
        r.check(source is not None, f"{tag}: 'source' is required")
        # Relative-path source: resolve through pluginRoot and confirm it exists.
        if isinstance(source, str):
            r.check(source.startswith("./"), f"{tag}: relative source '{source}' must start with './'")
            rel = Path(plugin_root) / source[2:] if source.startswith("./") else Path(source)
            resolved = (market_root / rel).resolve()
            r.check(resolved.is_dir(), f"{tag}: source dir '{rel}' does not exist")
            manifest = resolved / ".claude-plugin" / "plugin.json"
            r.check(manifest.is_file(), f"{tag}: '{rel}' is missing .claude-plugin/plugin.json")
            if manifest.is_file():
                plugin_manifests.append(str(manifest))
        elif isinstance(source, dict):
            r.check(isinstance(source.get("source"), str),
                    f"{tag}: object source must have a 'source' type field")

    return plugin_manifests


def main(argv: "list[str] | None" = None) -> int:
    market_path = REPO_ROOT / ".claude-plugin" / "marketplace.json"
    r = Result()

    if not market_path.is_file():
        print(f"FAIL: {market_path} does not exist. Run gen_marketplace.py first.")
        return 1

    manifests = validate_marketplace(r, market_path)
    for m in manifests:
        validate_plugin(r, Path(m))

    if r.errors:
        print(f"validate_marketplace: {len(r.errors)} error(s) in {r.checks} checks:")
        for e in r.errors:
            print(f"  - {e}")
        return 1
    print(f"validate_marketplace: all {r.checks} checks passed "
          f"({len(manifests)} plugin manifest(s) validated).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
