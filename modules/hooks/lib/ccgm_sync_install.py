"""Post-pull install step for the canonical CCGM clone (#1131).

CCGM link-mode installs symlink each module file from ~/.claude into the
canonical clone. A pull updates files already linked, but a file a PR newly
adds to an installed module's module.json stays uninstalled. This module
links those files and reports hook commands that are not yet registered.

Target rules mirror start.sh and lib/modules.sh (get_module_files): every
module.json "files" entry has a target, and `template` / `merge` flags. Only
plain entries are linked. Template and merge entries (settings.json) are
skipped, and nothing that already exists is touched.
"""

from __future__ import annotations

import json
import os
import tempfile

MANIFEST_NAME = ".ccgm-manifest.json"


def _load_json(path: str):
    try:
        with open(path) as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def load_manifest(claude_dir: str) -> dict | None:
    m = _load_json(os.path.join(claude_dir, MANIFEST_NAME))
    return m if isinstance(m, dict) else None


def install_new_files(claude_dir: str, canonical_dir: str) -> list[str]:
    """Symlink module files missing from claude_dir. Returns the new link paths.

    No-op unless the manifest exists, is in link mode, and was installed from
    canonical_dir. Only global-scope modules recorded in the manifest are used.
    """
    manifest = load_manifest(claude_dir)
    if not manifest or manifest.get("linkMode") is not True:
        return []
    root = manifest.get("ccgmRoot") or ""
    if not root or os.path.realpath(root) != os.path.realpath(canonical_dir):
        return []

    created: list[str] = []
    for mod in manifest.get("modules") or []:
        mj = _load_json(os.path.join(root, "modules", mod, "module.json"))
        if not isinstance(mj, dict):
            continue
        scopes = mj.get("scope") or ["global"]
        if "global" not in scopes:
            continue
        for src_rel, spec in (mj.get("files") or {}).items():
            if spec.get("template") or spec.get("merge"):
                continue
            target = os.path.join(claude_dir, spec["target"])
            src = os.path.join(root, "modules", mod, src_rel)
            if os.path.lexists(target) or not os.path.exists(src):
                continue
            try:
                os.makedirs(os.path.dirname(target), exist_ok=True)
                os.symlink(src, target)
            except OSError:
                continue
            created.append(target)

    if created:
        _record_in_manifest(claude_dir, manifest, created)
    return created


def _record_in_manifest(claude_dir: str, manifest: dict, created: list[str]) -> None:
    files = list(manifest.get("files") or [])
    manifest["files"] = files + [p for p in created if p not in files]
    path = os.path.join(claude_dir, MANIFEST_NAME)
    try:
        fd, tmp = tempfile.mkstemp(dir=claude_dir, prefix=".ccgm-manifest.")
        with os.fdopen(fd, "w") as f:
            json.dump(manifest, f, indent=2)
            f.write("\n")
        os.replace(tmp, path)
    except OSError:
        pass


def _hook_commands(settings) -> set[str]:
    cmds: set[str] = set()
    hooks = settings.get("hooks") if isinstance(settings, dict) else None
    for groups in (hooks or {}).values():
        for group in groups or []:
            for h in group.get("hooks") or []:
                if isinstance(h, dict) and h.get("command"):
                    cmds.add(h["command"])
    return cmds


def unregistered_hooks(claude_dir: str, canonical_dir: str, modules: list[str]) -> list[str]:
    """Hook commands in each module's settings.partial.json missing from the
    live settings.json. Never modifies settings."""
    live = _load_json(os.path.join(claude_dir, "settings.json")) or {}
    registered = _hook_commands(live)
    missing: list[str] = []
    for mod in modules:
        partial = _load_json(os.path.join(canonical_dir, "modules", mod, "settings.partial.json"))
        for cmd in sorted(_hook_commands(partial or {})):
            if cmd not in registered and cmd not in missing:
                missing.append(cmd)
    return missing
