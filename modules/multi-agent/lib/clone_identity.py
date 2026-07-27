#!/usr/bin/env python3
"""Derive a clone's identity and port allocation from its own absolute path.

WHY THIS EXISTS
---------------
`.env.clone` used to be written once, by an inline heredoc inside the
`/workspace-setup` prose, and never checked again. Every consumer then read it
back as the source of truth. So the moment a file was copied between clones --
which is what happens when someone syncs `.env*` from a working clone -- the
wrong identity became permanent and invisible. One bad file cascaded: two
clones claimed the same Vite port, Vite silently auto-incremented onto a third
clone's port, and the tracking CSV recorded work under the wrong agent id.

A clone's absolute path cannot drift from itself. So the path is the source of
truth for identity, the port registry is the source of truth for ports, and
`.env.clone` is a derived cache that is rewritten whenever it disagrees.

DERIVATION (fully deterministic -- no git, no network, no clock)
----------------------------------------------------------------
    Workspace model   ~/code/{repo}-workspaces/{repo}-w{W}/{repo}-w{W}-c{C}
                      agent id = agent-w{W}-c{C}
                      offset   = W * clones_per_workspace + C

    Flat clone model  ~/code/{repo}-repos/{repo}-{N}
                      agent id = agent-{N}
                      offset   = N

    port = registry.repos[repo].{frontend,backend} + offset

`clones_per_workspace` is read from the repo's registry entry (default 4). It
lives in the registry rather than being inferred from sibling directories
because counting siblings is not stable: a partially created workspace, or a
stray directory, silently changes every port in the workspace.

A repo absent from the registry has NO derivable port allocation. Such a clone
is reported as unregistered and left alone -- inventing a fallback base port is
how two different repos end up on 5173.

CLI
---
    python3 ~/.claude/lib/clone_identity.py show    [DIR]
    python3 ~/.claude/lib/clone_identity.py audit   [--root DIR]... [--json]
    python3 ~/.claude/lib/clone_identity.py repair  [DIR] [--dry-run]
    python3 ~/.claude/lib/clone_identity.py repair  --all [--root DIR]... [--dry-run]
    python3 ~/.claude/lib/clone_identity.py workspace-table WORKSPACE_DIR [--write]
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

DEFAULT_REGISTRY_PATH = Path.home() / ".claude" / "port-registry.json"
DEFAULT_CLONES_PER_WORKSPACE = 4
DEFAULT_BLOCK_SIZE = 16

ENV_CLONE_FILENAME = ".env.clone"

HEADER = (
    "# Auto-generated from the clone path + ~/.claude/port-registry.json.\n"
    "# Do not edit: it is rewritten whenever it disagrees with the path.\n"
    "# Regenerate by hand with:\n"
    "#   python3 ~/.claude/lib/clone_identity.py repair\n"
)

# Keys this module owns. Anything else in an existing .env.clone (e.g. a
# project-specific ARGUS_SIM_UDID) is preserved verbatim on repair.
MANAGED_KEYS = (
    "WORKSPACE_NUMBER",
    "CLONE_NUMBER",
    "AGENT_ID",
    "PORT_OFFSET",
    "FRONTEND_PORT",
    "BACKEND_PORT",
)

# Legacy spellings written by ad-hoc generators before this module existed.
# They are removed on repair so a clone carries exactly one identity.
LEGACY_KEYS = ("WORKSPACE", "CLONE", "WORKSPACE_NUM", "CLONE_NUM")

WORKSPACE_DIR_RE = re.compile(r"^(?P<repo>.+)-w(?P<w>\d+)-c(?P<c>\d+)$")
FLAT_DIR_RE = re.compile(r"^(?P<repo>.+?)-(?P<n>\d+)$")

MODEL_WORKSPACE = "workspace"
MODEL_FLAT = "flat"


class Identity:
    """The derived, canonical identity of one clone directory."""

    __slots__ = (
        "path", "model", "repo", "workspace", "clone", "agent_id",
        "port_offset", "frontend_port", "backend_port", "registered",
        "block_overflow",
    )

    def __init__(
        self, path: Path, model: str, repo: str, workspace: int | None,
        clone: int, agent_id: str, port_offset: int,
        frontend_port: int | None, backend_port: int | None,
        registered: bool, block_overflow: bool,
    ) -> None:
        self.path = path
        self.model = model
        self.repo = repo
        self.workspace = workspace
        self.clone = clone
        self.agent_id = agent_id
        self.port_offset = port_offset
        self.frontend_port = frontend_port
        self.backend_port = backend_port
        self.registered = registered
        self.block_overflow = block_overflow

    def to_dict(self) -> dict:
        return {
            "path": str(self.path),
            "model": self.model,
            "repo": self.repo,
            "workspace": self.workspace,
            "clone": self.clone,
            "agent_id": self.agent_id,
            "port_offset": self.port_offset,
            "frontend_port": self.frontend_port,
            "backend_port": self.backend_port,
            "registered": self.registered,
            "block_overflow": self.block_overflow,
        }

    def managed_values(self) -> dict[str, str]:
        """The managed keys this identity implies, in canonical order."""
        vals: dict[str, str] = {}
        if self.model == MODEL_WORKSPACE:
            vals["WORKSPACE_NUMBER"] = str(self.workspace)
        vals["CLONE_NUMBER"] = str(self.clone)
        vals["AGENT_ID"] = self.agent_id
        vals["PORT_OFFSET"] = str(self.port_offset)
        if self.frontend_port is not None:
            vals["FRONTEND_PORT"] = str(self.frontend_port)
        if self.backend_port is not None:
            vals["BACKEND_PORT"] = str(self.backend_port)
        return vals


def load_registry(registry_path: str | os.PathLike | None = None) -> dict:
    """Load the port registry. A missing or unreadable registry is empty."""
    path = Path(registry_path) if registry_path else DEFAULT_REGISTRY_PATH
    try:
        with open(path) as fh:
            data = json.load(fh)
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def clones_per_workspace(registry: dict, repo: str) -> int:
    """How many clones a workspace of `repo` holds. Registry wins, else 4."""
    entry = registry.get("repos", {}).get(repo)
    if isinstance(entry, dict):
        value = entry.get("clones_per_workspace")
        if isinstance(value, int) and value > 0:
            return value
    return DEFAULT_CLONES_PER_WORKSPACE


def parse_clone_path(clone_dir: str | os.PathLike) -> tuple[str, str, int | None, int] | None:
    """Parse a clone directory path into (model, repo, workspace, clone).

    Returns None when the path is not a managed clone (a standalone checkout,
    a worktree, a bare repo). Only the directory names are consulted, so this
    is pure and testable against paths that do not exist on disk.
    """
    path = Path(clone_dir)
    name = path.name
    parent = path.parent.name
    grandparent = path.parent.parent.name

    match = WORKSPACE_DIR_RE.match(name)
    if match:
        repo = match.group("repo")
        w, c = int(match.group("w")), int(match.group("c"))
        # Only accept it inside the layout the workspace model defines, so a
        # feature directory that happens to end in -w1-c0 is not adopted.
        if parent == f"{repo}-w{w}" and grandparent == f"{repo}-workspaces":
            return (MODEL_WORKSPACE, repo, w, c)
        return None

    match = FLAT_DIR_RE.match(name)
    if match:
        repo = match.group("repo")
        n = int(match.group("n"))
        if parent == f"{repo}-repos":
            return (MODEL_FLAT, repo, None, n)
    return None


def derive_identity(
    clone_dir: str | os.PathLike, registry: dict | None = None,
) -> Identity | None:
    """Derive the canonical identity of `clone_dir`, or None if unmanaged."""
    parsed = parse_clone_path(clone_dir)
    if parsed is None:
        return None
    model, repo, workspace, clone = parsed
    reg = registry if registry is not None else load_registry()

    if model == MODEL_WORKSPACE:
        offset = workspace * clones_per_workspace(reg, repo) + clone
        agent_id = f"agent-w{workspace}-c{clone}"
    else:
        offset = clone
        agent_id = f"agent-{clone}"

    entry = reg.get("repos", {}).get(repo)
    registered = isinstance(entry, dict)
    frontend = backend = None
    if registered:
        fbase, bbase = entry.get("frontend"), entry.get("backend")
        if isinstance(fbase, int):
            frontend = fbase + offset
        if isinstance(bbase, int):
            backend = bbase + offset

    block = reg.get("_block_size", DEFAULT_BLOCK_SIZE)
    block = block if isinstance(block, int) and block > 0 else DEFAULT_BLOCK_SIZE

    return Identity(
        path=Path(clone_dir), model=model, repo=repo, workspace=workspace,
        clone=clone, agent_id=agent_id, port_offset=offset,
        frontend_port=frontend, backend_port=backend,
        registered=registered, block_overflow=offset >= block,
    )


def parse_env_clone(text: str) -> tuple[dict[str, str], list[str]]:
    """Parse `.env.clone` text into (values, comment lines)."""
    values: dict[str, str] = {}
    comments: list[str] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith("#"):
            comments.append(raw)
            continue
        if "=" in line:
            key, val = line.split("=", 1)
            values[key.strip()] = val.strip()
    return values, comments


def read_env_clone(clone_dir: str | os.PathLike) -> dict[str, str]:
    """Read a clone's `.env.clone` values. Missing file reads as empty."""
    try:
        text = Path(clone_dir, ENV_CLONE_FILENAME).read_text()
    except OSError:
        return {}
    return parse_env_clone(text)[0]


def render_env_clone(identity: Identity, existing: dict[str, str] | None = None) -> str:
    """Render the canonical `.env.clone` for `identity`.

    Unmanaged keys already present are carried through unchanged; legacy
    identity spellings are dropped so exactly one identity survives.
    """
    lines = [HEADER.rstrip("\n")]
    managed = identity.managed_values()
    lines.extend(f"{k}={v}" for k, v in managed.items())

    if existing:
        extras = [
            (k, v) for k, v in existing.items()
            if k not in MANAGED_KEYS and k not in LEGACY_KEYS
        ]
        if extras:
            lines.append("")
            lines.append("# Project-specific values, preserved as-is.")
            lines.extend(f"{k}={v}" for k, v in extras)
    return "\n".join(lines) + "\n"


def diff_env_clone(identity: Identity, existing: dict[str, str]) -> dict[str, tuple[str | None, str]]:
    """Managed keys whose current value differs from the derived one.

    Maps key -> (current or None, expected). A legacy key still present counts
    as drift on the managed key it shadows.
    """
    drift: dict[str, tuple[str | None, str]] = {}
    for key, expected in identity.managed_values().items():
        current = existing.get(key)
        if current != expected:
            drift[key] = (current, expected)
    for legacy in LEGACY_KEYS:
        if legacy in existing:
            drift[legacy] = (existing[legacy], "<removed>")
    return drift


def repair_clone(
    clone_dir: str | os.PathLike, registry: dict | None = None,
    dry_run: bool = False,
) -> dict:
    """Bring one clone's `.env.clone` in line with its path and the registry.

    Returns a result dict with `status` in:
      unmanaged   - not a workspace/flat clone; nothing to do
      unregistered- repo absent from the registry; NOT rewritten
      ok          - already correct
      repaired    - rewritten (or would be, under --dry-run)
    """
    identity = derive_identity(clone_dir, registry)
    if identity is None:
        return {"path": str(clone_dir), "status": "unmanaged"}

    existing = read_env_clone(clone_dir)
    result = identity.to_dict()

    if not identity.registered:
        result["status"] = "unregistered"
        result["drift"] = {}
        return result

    drift = diff_env_clone(identity, existing)
    result["drift"] = {k: {"current": c, "expected": e} for k, (c, e) in drift.items()}
    if not drift:
        result["status"] = "ok"
        return result

    result["status"] = "repaired"
    if not dry_run:
        target = Path(clone_dir, ENV_CLONE_FILENAME)
        tmp = target.with_suffix(target.suffix + ".tmp")
        tmp.write_text(render_env_clone(identity, existing))
        os.replace(tmp, target)
    return result


def default_roots() -> list[Path]:
    return [Path.home() / "code"]


def discover_clones(roots: list[Path] | None = None) -> list[Path]:
    """Find every managed clone directory under `roots`."""
    found: list[Path] = []
    for root in roots or default_roots():
        for pattern in ("*-workspaces/*/*", "*-repos/*"):
            for candidate in sorted(root.glob(pattern)):
                if candidate.is_dir() and parse_clone_path(candidate):
                    found.append(candidate)
    return found


def audit(roots: list[Path] | None = None, registry: dict | None = None) -> dict:
    """Audit every discovered clone. Read-only; also reports port collisions."""
    reg = registry if registry is not None else load_registry()
    rows = [repair_clone(c, reg, dry_run=True) for c in discover_clones(roots)]

    # A collision is two clones deriving the SAME port. That is a registry
    # allocation problem (overlapping blocks), not something repair can fix,
    # so it is reported rather than silently reassigned.
    claims: dict[tuple[str, int], list[str]] = {}
    for row in rows:
        if row["status"] in ("unmanaged", "unregistered"):
            continue
        for service in ("frontend_port", "backend_port"):
            port = row.get(service)
            if isinstance(port, int):
                claims.setdefault((service, port), []).append(row["agent_id"] + " @ " + row["path"])
    collisions = [
        {"service": s, "port": p, "claimants": sorted(who)}
        for (s, p), who in sorted(claims.items()) if len(who) > 1
    ]
    return {"clones": rows, "collisions": collisions}


TABLE_BEGIN = "<!-- BEGIN clone-identity-table -->"
TABLE_END = "<!-- END clone-identity-table -->"
STRUCTURE_HEADING = "## Structure"


def workspace_table(workspace_dir: str | os.PathLike, registry: dict | None = None) -> str:
    """Render the markdown clone table for a workspace, from the registry.

    The workspace CLAUDE.md table and the port registry were two independent
    sources of truth that could disagree. Generating the table from the
    registry removes the second one.
    """
    reg = registry if registry is not None else load_registry()
    path = Path(workspace_dir)
    clones = [c for c in sorted(path.iterdir()) if c.is_dir() and parse_clone_path(c)] \
        if path.is_dir() else []

    header = (
        "| Clone | Directory | Agent ID | Frontend Port | Backend Port |\n"
        "|-------|-----------|----------|---------------|--------------|\n"
    )
    rows = []
    for clone in clones:
        ident = derive_identity(clone, reg)
        if ident is None:
            continue
        fe = ident.frontend_port if ident.frontend_port is not None else "unregistered"
        be = ident.backend_port if ident.backend_port is not None else "unregistered"
        rows.append(
            f"| c{ident.clone} | {clone.name}/ | {ident.agent_id} | {fe} | {be} |"
        )
    return header + "\n".join(rows) + ("\n" if rows else "")


def write_workspace_table(
    workspace_dir: str | os.PathLike, registry: dict | None = None,
    dry_run: bool = False,
) -> dict:
    """Refresh the generated clone table inside a workspace's CLAUDE.md.

    The table used to be typed by hand, which made it a second source of truth
    that could disagree with the port registry. Writing it from the same
    derivation `.env.clone` uses removes the disagreement by construction.

    Marker-delimited content is replaced. If the markers are absent, the block
    is inserted directly under `## Structure`, replacing a markdown table
    already sitting there. Prose outside that region is never touched.

    Refuses outright when any clone's repo is missing from the registry. The
    derivation has no ports to offer there, so writing would replace whatever
    the table documented with the word "unregistered" -- destroying real
    information to assert an absence. Same non-destructive rule as repair().
    """
    reg = registry if registry is not None else load_registry()
    path = Path(workspace_dir, "CLAUDE.md")

    ws = Path(workspace_dir)
    if ws.is_dir():
        for clone in sorted(ws.iterdir()):
            if not (clone.is_dir() and parse_clone_path(clone)):
                continue
            identity = derive_identity(clone, reg)
            if identity is not None and not identity.registered:
                return {"path": str(path), "status": "unregistered", "repo": identity.repo}

    block = f"{TABLE_BEGIN}\n{workspace_table(workspace_dir, reg)}{TABLE_END}"

    try:
        original = path.read_text()
    except OSError:
        return {"path": str(path), "status": "missing"}

    if TABLE_BEGIN in original and TABLE_END in original:
        head, rest = original.split(TABLE_BEGIN, 1)
        _, tail = rest.split(TABLE_END, 1)
        updated = head + block + tail
    elif STRUCTURE_HEADING in original:
        head, rest = original.split(STRUCTURE_HEADING, 1)
        lines = rest.splitlines(keepends=True)
        cursor = 0
        # Skip the blank line(s) after the heading, then drop a contiguous
        # markdown table if one is there.
        while cursor < len(lines) and not lines[cursor].strip():
            cursor += 1
        while cursor < len(lines) and lines[cursor].lstrip().startswith("|"):
            cursor += 1
        updated = f"{head}{STRUCTURE_HEADING}\n\n{block}\n{''.join(lines[cursor:])}"
    else:
        return {"path": str(path), "status": "no-anchor"}

    if updated == original:
        return {"path": str(path), "status": "ok"}
    if not dry_run:
        path.write_text(updated)
    return {"path": str(path), "status": "updated"}


def _cmd_show(args: argparse.Namespace) -> int:
    reg = load_registry(args.registry)
    identity = derive_identity(args.dir, reg)
    if identity is None:
        print(f"{args.dir}: not a managed clone directory", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(identity.to_dict(), indent=2))
    else:
        for key, val in identity.to_dict().items():
            print(f"{key}: {val}")
    return 0


def _cmd_audit(args: argparse.Namespace) -> int:
    reg = load_registry(args.registry)
    report = audit([Path(r) for r in args.root] if args.root else None, reg)
    if args.json:
        print(json.dumps(report, indent=2))
        return 0

    drifted = [r for r in report["clones"] if r["status"] == "repaired"]
    unreg = [r for r in report["clones"] if r["status"] == "unregistered"]
    ok = [r for r in report["clones"] if r["status"] == "ok"]

    print(f"{len(report['clones'])} clones: {len(ok)} ok, {len(drifted)} drifted, "
          f"{len(unreg)} unregistered")
    for row in drifted:
        keys = ", ".join(
            f"{k} {v['current']!r}->{v['expected']!r}" for k, v in row["drift"].items()
        )
        print(f"  DRIFT  {row['path']}\n         {keys}")
    for row in unreg:
        print(f"  UNREG  {row['path']} (repo {row['repo']!r} not in port registry)")
    for col in report["collisions"]:
        print(f"  CLASH  {col['service']} {col['port']}: {', '.join(col['claimants'])}")
    return 1 if (drifted or report["collisions"]) else 0


def _cmd_repair(args: argparse.Namespace) -> int:
    reg = load_registry(args.registry)
    targets = (
        discover_clones([Path(r) for r in args.root] if args.root else None)
        if args.all else [Path(args.dir)]
    )
    changed = 0
    for target in targets:
        result = repair_clone(target, reg, dry_run=args.dry_run)
        if result["status"] == "repaired":
            changed += 1
            verb = "would repair" if args.dry_run else "repaired"
            print(f"{verb}: {result['path']} -> {result['agent_id']} "
                  f"fe={result.get('frontend_port')} be={result.get('backend_port')}")
        elif result["status"] == "unregistered" and args.all:
            print(f"skipped (unregistered repo): {result['path']}")
        elif not args.all:
            print(f"{result['status']}: {result['path']}")
    if args.all:
        print(f"{changed} of {len(targets)} clones "
              f"{'would be ' if args.dry_run else ''}repaired")
    return 0


def _cmd_workspace_table(args: argparse.Namespace) -> int:
    registry = load_registry(args.registry)
    if not args.write:
        print(workspace_table(args.dir, registry), end="")
        return 0
    result = write_workspace_table(args.dir, registry, dry_run=args.dry_run)
    print(f"{result['status']}: {result['path']}")
    if result["status"] == "no-anchor":
        print(f"  add {TABLE_BEGIN} / {TABLE_END} markers, or a '{STRUCTURE_HEADING}' "
              f"heading, where the table belongs", file=sys.stderr)
        return 1
    if result["status"] == "unregistered":
        print(f"  add repo {result['repo']!r} to the port registry first; nothing was "
              f"written", file=sys.stderr)
        return 1
    return 0 if result["status"] != "missing" else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="clone_identity.py",
        description="Derive and repair .env.clone from the clone path + port registry.",
    )
    parser.add_argument("--registry", help="Path to port-registry.json")
    sub = parser.add_subparsers(dest="command", required=True)

    show = sub.add_parser("show", help="Show the derived identity of a clone")
    show.add_argument("dir", nargs="?", default=os.getcwd())
    show.add_argument("--json", action="store_true")
    show.set_defaults(func=_cmd_show)

    aud = sub.add_parser("audit", help="Audit every clone; exit 1 on drift or collision")
    aud.add_argument("--root", action="append", help="Search root (repeatable)")
    aud.add_argument("--json", action="store_true")
    aud.set_defaults(func=_cmd_audit)

    rep = sub.add_parser("repair", help="Rewrite .env.clone where it disagrees")
    rep.add_argument("dir", nargs="?", default=os.getcwd())
    rep.add_argument("--all", action="store_true", help="Repair every discovered clone")
    rep.add_argument("--root", action="append", help="Search root (repeatable, with --all)")
    rep.add_argument("--dry-run", action="store_true")
    rep.set_defaults(func=_cmd_repair)

    tbl = sub.add_parser("workspace-table", help="Render a workspace's clone table")
    tbl.add_argument("dir")
    tbl.add_argument("--write", action="store_true",
                     help="Write the table into the workspace's CLAUDE.md")
    tbl.add_argument("--dry-run", action="store_true")
    tbl.set_defaults(func=_cmd_workspace_table)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
