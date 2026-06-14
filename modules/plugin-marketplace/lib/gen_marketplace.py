#!/usr/bin/env python3
"""Project CCGM modules into a native Claude Code plugin marketplace (issue #703).

WHAT THIS DOES
--------------
CCGM's source of truth is `modules/*/module.json`. The bash installer
(`start.sh`) is and remains the canonical, full-fidelity install path: only it
performs the deep settings.json merge and writes the global CLAUDE.md context
that Claude Code auto-loads.

This generator ADDITIVELY projects the same modules into the native Claude Code
plugin format so CCGM can also be consumed as a plugin marketplace
(`claude plugin marketplace add <owner>/ccgm`; see the README for the owner).
It is a pure projection:

  * It reads every `modules/<name>/module.json`.
  * It writes one `modules/<name>/.claude-plugin/plugin.json` per module,
    declaring the native plugin components that module actually ships.
  * It writes the catalog `.claude-plugin/marketplace.json` at the repo root,
    listing every module as a plugin (via `metadata.pluginRoot: "./modules"`).

It NEVER edits module rule/command/agent/skill content. The only files it
writes are the generated manifests and rule-hook copies, all of which are
committed alongside this script.

WHY EACH modules/<name> IS ITS OWN PLUGIN ROOT
----------------------------------------------
A CCGM module's on-disk layout already matches a plugin's expected layout:
`commands/`, `agents/`, `skills/`, `output-styles/`, `hooks/`. So the plugin
root is simply `modules/<name>/`, and `.claude-plugin/plugin.json` goes inside
it. Plugins are copied to a cache on install and cannot reference files outside
their own directory, so keeping each module self-rooted means every plugin is
self-contained.

THE CLAUDE.md / rules GAP
-------------------------
A plugin's root `CLAUDE.md` is NOT loaded as context, and a plugin can only
contribute the `agent`/`subagentStatusLine` settings keys. Many CCGM modules
are rules-only (`rules/*.md`). To preserve their value under the plugin path,
modules that ship `type:"rule"` files get a SessionStart hook
(`hooks/plugin-rule-inject.py`) wired into their generated `plugin.json`. That
hook injects the plugin's own bundled rules as `additionalContext` at session
start. This is the documented workaround for plugin-CLAUDE.md-not-loading.

DETERMINISM
-----------
Output is fully sorted (modules, JSON keys) so re-running the generator on an
unchanged tree produces byte-identical files. CI runs the generator with
--check and fails if the working tree would change, guaranteeing the committed
output stays in sync with module.json.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

# Repo root is two levels up from this file: modules/plugin-marketplace/lib/.
REPO_ROOT = Path(__file__).resolve().parents[3]

# Marketplace identity. `name` is public-facing (users type `plugin@ccgm`).
# It must not collide with the reserved Anthropic names.
#
# Author/owner is the project name, NOT a personal handle: these manifests are
# committed to a public repo and the personal-data guard (tests/) forbids the
# maintainer username in any file but README/postInstall. The repository URL is
# likewise omitted here to stay clear of that guard; users discover the repo via
# the README install instructions.
MARKETPLACE_NAME = "ccgm"
MARKETPLACE_OWNER = {"name": "CCGM"}
MARKETPLACE_DESCRIPTION = (
    "Claude Code God Mode - modular rules, commands, agents, and skills. "
    "The bash installer (start.sh) remains the canonical full-fidelity path; "
    "this marketplace is an additive native-plugin projection of the same modules."
)
MARKETPLACE_SCHEMA = "https://json.schemastore.org/claude-code-marketplace.json"
PLUGIN_SCHEMA = "https://json.schemastore.org/claude-code-plugin-manifest.json"

# Where the per-plugin rule-injection hook lives inside an INSTALLED plugin.
HOOK_REL = "hooks/plugin-rule-inject.py"


def _load(path: Path) -> dict:
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def _module_manifests() -> "list[tuple[str, dict]]":
    """Return sorted (module_name, manifest) for every modules/*/module.json."""
    mods_dir = REPO_ROOT / "modules"
    out: "list[tuple[str, dict]]" = []
    for child in sorted(mods_dir.iterdir()):
        manifest = child / "module.json"
        if child.is_dir() and manifest.is_file():
            out.append((child.name, _load(manifest)))
    return out


def _file_types(manifest: dict) -> "set[str]":
    files = manifest.get("files")
    if not isinstance(files, dict):
        return set()
    return {
        v.get("type")
        for v in files.values()
        if isinstance(v, dict) and v.get("type")
    }


def _has_rule(manifest: dict) -> bool:
    return "rule" in _file_types(manifest)


def _has_output_style(manifest: dict) -> bool:
    """A module ships an output style iff it has a content file targeting
    output-styles/."""
    files = manifest.get("files")
    if not isinstance(files, dict):
        return False
    for v in files.values():
        if not isinstance(v, dict):
            continue
        target = v.get("target", "")
        if v.get("type") == "content" and isinstance(target, str) and \
                target.startswith("output-styles/"):
            return True
    return False


def _component_summary(manifest: dict) -> "list[str]":
    """Human-facing list of native plugin components this module contributes."""
    types = _file_types(manifest)
    comps: "list[str]" = []
    if "command" in types:
        comps.append("commands")
    if "agent" in types:
        comps.append("agents")
    if "skill" in types:
        comps.append("skills")
    if _has_output_style(manifest):
        comps.append("output-styles")
    if _has_rule(manifest):
        comps.append("rules")
    if "hook" in types:
        comps.append("hooks")
    return comps


def build_plugin_manifest(name: str, manifest: dict) -> dict:
    """Build the .claude-plugin/plugin.json for one module.

    Only `name` is strictly required. We add metadata for the /plugin picker and
    wire the rule-injection hook for modules that ship rules. Native components
    (commands/agents/skills/output-styles) are auto-discovered from their
    default directories, so we do not emit redundant path fields.
    """
    plugin: dict = {
        "$schema": PLUGIN_SCHEMA,
        "name": name,
        "description": manifest.get("description", ""),
        "author": dict(MARKETPLACE_OWNER),
        "license": "MIT",
    }

    display = manifest.get("displayName")
    if isinstance(display, str) and display:
        plugin["displayName"] = display

    tags = manifest.get("tags")
    if isinstance(tags, list) and tags:
        plugin["keywords"] = sorted({str(t) for t in tags if str(t)})

    # Rules-bearing modules get the session-start rule injector. The hook is
    # copied into each such plugin's hooks/ directory by the generator (see
    # _ensure_rule_hook) so ${CLAUDE_PLUGIN_ROOT}/hooks/... resolves after the
    # plugin is cached.
    if _has_rule(manifest):
        plugin["hooks"] = {
            "SessionStart": [
                {
                    "hooks": [
                        {
                            "type": "command",
                            "command": (
                                'python3 "${CLAUDE_PLUGIN_ROOT}/'
                                + HOOK_REL
                                + '"'
                            ),
                        }
                    ]
                }
            ]
        }

    return plugin


def build_marketplace(manifests: "list[tuple[str, dict]]") -> dict:
    plugins: "list[dict]" = []
    for name, manifest in manifests:
        entry: dict = {
            "name": name,
            # pluginRoot is "./modules", so source is just the module dir name.
            "source": f"./{name}",
            "description": manifest.get("description", ""),
            "category": manifest.get("category", "workflow"),
        }
        tags = manifest.get("tags")
        if isinstance(tags, list) and tags:
            entry["tags"] = sorted({str(t) for t in tags if str(t)})
        # Surface beta/deprecated status so the catalog mirrors module.json.
        status = manifest.get("status")
        if isinstance(status, str) and status and status != "stable":
            entry["keywords"] = [f"status:{status}"]
        plugins.append(entry)

    return {
        "$schema": MARKETPLACE_SCHEMA,
        "name": MARKETPLACE_NAME,
        "owner": dict(MARKETPLACE_OWNER),
        "description": MARKETPLACE_DESCRIPTION,
        "metadata": {"pluginRoot": "./modules"},
        "plugins": plugins,
    }


def _serialize(data: dict) -> str:
    return json.dumps(data, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def _dump(path: Path, data: dict) -> bool:
    """Write data as deterministic JSON. Return True if the file changed."""
    text = _serialize(data)
    if path.exists() and path.read_text(encoding="utf-8") == text:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return True


def _ensure_rule_hook(name: str, changed: "list[str]", check: bool) -> None:
    """Copy the shared rule-injection hook into a rules-bearing plugin.

    The hook source of truth is plugin-marketplace/hooks/plugin-rule-inject.py.
    Each rules-bearing plugin needs its own copy because installed plugins
    cannot reference files outside their directory. The copy is committed.
    """
    src = REPO_ROOT / "modules" / "plugin-marketplace" / HOOK_REL
    dst = REPO_ROOT / "modules" / name / HOOK_REL
    src_text = src.read_text(encoding="utf-8")
    if dst.exists() and dst.read_text(encoding="utf-8") == src_text:
        return
    changed.append(str(dst.relative_to(REPO_ROOT)))
    if not check:
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_text(src_text, encoding="utf-8")
        os.chmod(dst, 0o755)


def generate(check: bool = False) -> "list[str]":
    """Generate (or, with check=True, dry-run) all marketplace files.

    Returns the list of repo-relative paths that changed (or would change).
    """
    manifests = _module_manifests()
    changed: "list[str]" = []

    # Per-module plugin manifests + rule-hook copies.
    for name, manifest in manifests:
        # plugin-marketplace is the host module for the shared hook; it does not
        # need a self-injected copy, but it still gets a plugin.json so it can
        # be installed like any other plugin.
        if _has_rule(manifest) and name != "plugin-marketplace":
            _ensure_rule_hook(name, changed, check)
        plugin = build_plugin_manifest(name, manifest)
        dst = REPO_ROOT / "modules" / name / ".claude-plugin" / "plugin.json"
        if check:
            if not dst.exists() or dst.read_text(encoding="utf-8") != _serialize(plugin):
                changed.append(str(dst.relative_to(REPO_ROOT)))
        elif _dump(dst, plugin):
            changed.append(str(dst.relative_to(REPO_ROOT)))

    # Root marketplace catalog.
    market = build_marketplace(manifests)
    market_path = REPO_ROOT / ".claude-plugin" / "marketplace.json"
    if check:
        if not market_path.exists() or \
                market_path.read_text(encoding="utf-8") != _serialize(market):
            changed.append(str(market_path.relative_to(REPO_ROOT)))
    elif _dump(market_path, market):
        changed.append(str(market_path.relative_to(REPO_ROOT)))

    return changed


def main(argv: "list[str] | None" = None) -> int:
    parser = argparse.ArgumentParser(
        description="Generate the CCGM plugin marketplace from modules/*/module.json"
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Do not write; exit 1 if generated output would differ from "
        "what is committed. Use in CI.",
    )
    args = parser.parse_args(argv)

    changed = generate(check=args.check)

    if args.check:
        if changed:
            print("Marketplace files are STALE. Re-run the generator:")
            print("  python3 modules/plugin-marketplace/lib/gen_marketplace.py")
            print("\nFiles that would change:")
            for p in changed:
                print(f"  {p}")
            return 1
        print("Marketplace files are up to date.")
        return 0

    if changed:
        print(f"Wrote {len(changed)} file(s):")
        for p in changed:
            print(f"  {p}")
    else:
        print("Marketplace files already up to date; nothing written.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
