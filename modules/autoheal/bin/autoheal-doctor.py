#!/usr/bin/env python3
"""autoheal-doctor.py - diagnose the autoheal launchd job (/autoheal doctor).

Read-only. Prints:
  - the loaded launchd job's plist path (`launchctl print gui/$UID/<label>`)
  - whether its program/arguments resolve to an existing file under the real
    home directory
  - the job's last exit code
  - heartbeat age and status (health.json)
  - whether ANTHROPIC_API_KEY is set in autoheal's .env (never the value)
  - the last cost.log row
  - whether every module.json file target of the autoheal module exists under
    the real home's .claude (merge entries such as settings.json are skipped)
  - when something is wrong, the exact repair: bootout plus bootstrap of the
    real plist, or the command that links missing module files. The doctor never
    runs a repair; /autoheal asks first.

Exit 0 when every check passes, 1 otherwise.

Env (tests): CCGM_DOCTOR_REAL_HOME (default: the passwd home of the current
uid, not $HOME, which a temp-HOME run overrides), CCGM_AUTOHEAL_DIR,
CCGM_AUTOHEAL_USERNAME (label owner, default $USER), CCGM_AUTOHEAL_LABEL,
CCGM_DOCTOR_MANIFEST (module.json to check, default: the one beside this
script's real path; with no manifest the install check is skipped).

Python 3 standard library only.
"""
from __future__ import annotations

import json
import os
import pwd
import re
import shlex
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

STALE_HOURS = 26
SHELLS = {"sh", "bash", "zsh", "dash"}
INSTALL_PROBLEM = "module files not installed"


def real_home() -> Path:
    override = os.environ.get("CCGM_DOCTOR_REAL_HOME")
    return Path(override or pwd.getpwuid(os.getuid()).pw_dir)


def manifest_path() -> Path:
    override = os.environ.get("CCGM_DOCTOR_MANIFEST")
    if override:
        return Path(override)
    return Path(os.path.realpath(__file__)).parent.parent / "module.json"


def missing_files(manifest: Path, claude_dir: Path) -> "tuple[int, list[str]] | None":
    """Return (files checked, targets missing under claude_dir), or None when
    the manifest cannot be read. Entries with `merge` (settings.json) are not
    files of their own and are skipped. A dangling symlink counts as missing."""
    try:
        files = json.loads(manifest.read_text(encoding="utf-8"))["files"]
    except (OSError, ValueError, KeyError, TypeError):
        return None
    targets = [e["target"] for e in files.values()
               if isinstance(e, dict) and isinstance(e.get("target"), str) and not e.get("merge")]
    return len(targets), [t for t in targets if not (claude_dir / t).exists()]


def install_repair(manifest: Path, claude_dir: Path) -> "list[str]":
    """The command that links the missing files. install_new_files only links;
    it does nothing for a copy-mode install, which needs ./start.sh again."""
    repo = manifest.resolve().parent.parent.parent
    code = (f"import os,sys; sys.path.insert(0,{str(repo / 'modules' / 'hooks' / 'lib')!r}); "
            f"import ccgm_sync_install as i; print(i.install_new_files({str(claude_dir)!r}, {str(repo)!r}))")
    return ["install repair (links the missing files; a copy-mode install needs ./start.sh instead):",
            f"  python3 -c {shlex.quote(code)}"]


def label() -> str:
    explicit = os.environ.get("CCGM_AUTOHEAL_LABEL")
    if explicit:
        return explicit
    user = os.environ.get("CCGM_AUTOHEAL_USERNAME") or os.environ.get("USER") or "unknown"
    return f"com.{user}.ccgm.autoheal.daily"


def launchctl_print(target: str) -> "tuple[int, str]":
    try:
        res = subprocess.run(["launchctl", "print", target], capture_output=True, text=True, check=False)
    except OSError as exc:
        return 127, str(exc)
    return res.returncode, res.stdout


def parse_print(text: str) -> "dict[str, object]":
    """Pull path, program, arguments and last exit code from `launchctl print`."""
    info: dict[str, object] = {"arguments": []}
    in_args = False
    for raw in text.splitlines():
        line = raw.strip()
        if in_args:
            if line == "}":
                in_args = False
            else:
                info["arguments"].append(line)  # type: ignore[union-attr]
            continue
        if line.startswith("arguments = {"):
            in_args = True
            continue
        m = re.match(r"(path|program|stderr path|last exit code) = (.+)$", line)
        if m:
            info[m.group(1)] = m.group(2).strip()
    return info


def script_paths(info: "dict[str, object]", home: Path) -> "list[str]":
    """Files the job runs: program, plus each argument that is a path, plus the
    first word of a `sh -c "<command>"` string. Shell binaries and flags are
    skipped. $HOME and ~ expand to the real home, as launchd's shell would."""
    candidates: list[str] = []
    program = info.get("program")
    args = [a for a in info.get("arguments", []) if isinstance(a, str)]  # type: ignore[union-attr]
    for item in ([program] if isinstance(program, str) else []) + args:
        try:
            words = shlex.split(item)
        except ValueError:
            words = item.split()
        if not words:
            continue
        word = words[0].replace("$HOME", str(home)).replace("${HOME}", str(home))
        if word.startswith("~/"):
            word = str(home / word[2:])
        if word.startswith("-") or not word.startswith("/"):
            continue
        if os.path.basename(word) in SHELLS:
            continue
        if word not in candidates:
            candidates.append(word)
    return candidates


def under(path: str, home: Path) -> bool:
    try:
        Path(os.path.realpath(path)).relative_to(os.path.realpath(home))
    except ValueError:
        return False
    return True


GOOD_STATUSES = ("ok", "partial", "paused")


def stale_exit(info: "dict[str, object]", good_at: "datetime | None") -> "str | None":
    """Return a note when launchd's last exit code predates the last good run.

    launchd records no time for the exit code. The evidence readable here: the
    mtime of the job's stderr file (a launch that fails, such as exit 127,
    writes there; a good run logs to ~/.claude/logs instead) against the
    generated_at of a successful health.json. The exit is stale only when the
    good heartbeat is newer than that file. No stderr path, or an unreadable
    file, proves nothing, so the exit code stays a problem."""
    err = info.get("stderr path")
    if good_at is None or not isinstance(err, str):
        return None
    try:
        err_at = datetime.fromtimestamp(os.stat(err).st_mtime, timezone.utc)
    except OSError:
        return None
    if good_at <= err_at:
        return None
    return (f"stale: predates the last good run at {good_at.strftime('%Y-%m-%dT%H:%M:%SZ')} "
            f"(compared launchd stderr mtime {err_at.strftime('%Y-%m-%dT%H:%M:%SZ')} "
            f"with health.json generated_at)")


def heartbeat(adir: Path, now: datetime) -> "tuple[list[str], bool, datetime | None]":
    """Return (output lines, healthy, time of the last good run's heartbeat)."""
    path = adir / "health.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        stamp = datetime.fromisoformat(str(data["generated_at"]).replace("Z", "+00:00"))
    except (OSError, ValueError, KeyError):
        return [f"heartbeat: no health.json at {path} (the job has never finished a run)"], False, None
    age_h = int((now - stamp).total_seconds() // 3600)
    status = data.get("status", "unknown")
    lines = [f"heartbeat: status={status}, age {age_h}h (generated {data['generated_at']})"]
    for r in data.get("reasons") or []:
        if isinstance(r, dict):
            lines.append(f"  reason {r.get('code')}: {r.get('message')}")
    ok = status in GOOD_STATUSES and age_h <= STALE_HOURS
    if age_h > STALE_HOURS:
        lines.append(f"  stale: older than {STALE_HOURS}h")
    return lines, ok, (stamp if status in GOOD_STATUSES else None)


def api_key(adir: Path) -> bool:
    try:
        text = (adir / ".env").read_text(encoding="utf-8")
    except OSError:
        return False
    for line in text.splitlines():
        m = re.match(r"\s*(?:export\s+)?ANTHROPIC_API_KEY\s*=\s*(.*)$", line)
        if m and m.group(1).strip().strip("'\""):
            return True
    return False


def last_cost_row(adir: Path) -> "str | None":
    try:
        rows = [ln for ln in (adir / "cost.log").read_text(encoding="utf-8").splitlines() if ln.strip()]
    except OSError:
        return None
    return rows[-1] if rows else None


def main() -> int:
    home = real_home()
    adir = Path(os.environ.get("CCGM_AUTOHEAL_DIR") or home / ".claude" / "autoheal")
    job = label()
    target = f"gui/{os.getuid()}/{job}"
    real_plist = home / "Library" / "LaunchAgents" / f"{job}.plist"
    problems: list[str] = []
    loaded = False
    out: list[str] = [f"autoheal doctor ({job})"]

    beat, beat_ok, good_at = heartbeat(adir, datetime.now(timezone.utc))

    rc, text = launchctl_print(target)
    if rc != 0:
        out.append(f"launchd: not loaded ({target}; launchctl print rc={rc})")
        problems.append("job not loaded")
    else:
        loaded = True
        info = parse_print(text)
        plist = str(info.get("path", "(unknown)"))
        out.append(f"launchd: loaded from {plist}")
        exit_code = str(info.get("last exit code", "unknown"))
        stale = stale_exit(info, good_at) if exit_code not in ("0", "(never exited)", "unknown") else None
        out.append(f"last exit code: {exit_code}" + (f" ({stale})" if stale else ""))
        if plist != "(unknown)" and not under(plist, home):
            out.append(f"  plist is not under the real home {home}")
            problems.append("plist outside real home")
        if plist != "(unknown)" and not Path(plist).exists():
            out.append(f"  plist file missing: {plist}")
            problems.append("plist missing")
        scripts = script_paths(info, home)
        if not scripts:
            out.append("program: could not find a script path in program/arguments")
            problems.append("no script path")
        for path in scripts:
            exists = os.path.isfile(path)
            inside = under(path, home)
            out.append(f"program: {path} ({'exists' if exists else 'missing'}"
                       f"{'' if inside else f', not under real home {home}'})")
            if not exists:
                problems.append(f"{path} missing")
            elif not inside:
                problems.append(f"{path} outside real home")
        if exit_code not in ("0", "(never exited)", "unknown") and not stale:
            problems.append(f"last exit code {exit_code}")

    out.extend(beat)
    if not beat_ok:
        problems.append("heartbeat unhealthy")

    key = api_key(adir)
    out.append(f"ANTHROPIC_API_KEY: {'present' if key else 'missing'} in {adir / '.env'}")
    if not key:
        problems.append("API key missing")

    row = last_cost_row(adir)
    out.append(f"last cost.log row: {row}" if row else f"last cost.log row: no cost.log rows in {adir / 'cost.log'}")

    claude_dir = home / ".claude"
    manifest = manifest_path()
    checked = missing_files(manifest, claude_dir)
    gaps: list[str] = []
    if checked is None:
        out.append(f"install: skipped, cannot read {manifest}")
    else:
        total, gaps = checked
        if gaps:
            out.append(f"install: {len(gaps)} of {total} module files missing under {claude_dir}")
            out.extend(f"  missing: {t}" for t in gaps)
            problems.append(INSTALL_PROBLEM)
        else:
            out.append(f"install: all {total} module files present under {claude_dir}")

    if problems:
        out.append("")
        out.append("problems: " + "; ".join(problems))
        if any(p != INSTALL_PROBLEM for p in problems):
            if real_plist.exists():
                out.append("repair (run in order):")
                if loaded:
                    out.append(f"  launchctl bootout gui/{os.getuid()}/{job}")
                out.append(f"  launchctl bootstrap gui/{os.getuid()} {real_plist}")
            else:
                out.append(f"repair: the real plist {real_plist} does not exist; reinstall with")
                out.append("  bash modules/autoheal/bin/autoheal-install.sh")
        if gaps:
            out.extend(install_repair(manifest, claude_dir))
    print("\n".join(out))
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
