"""Platform abstraction for scheduled-job installation.

Locked API (referenced from plan.md §5 Epic 1, §3.11 Linux portability):

    install_scheduled_job(label: str, command: str, hour: int, minute: int) -> None
    uninstall_scheduled_job(label: str) -> None
    list_scheduled_jobs() -> list[str]

macOS uses launchd LaunchAgents under ~/Library/LaunchAgents/.
Linux is a documented v2 plug-in seam — the implementation raises
NotImplementedError with a clear message pointing at the planned cron
template.

Note: the plan spells this `lib/platform.py`, but that name shadows the
Python stdlib `platform` module for any hook that puts `~/.claude/lib`
on `sys.path`. Renamed to `sched_platform.py` to keep the stdlib
reachable. The locked API (install_scheduled_job, uninstall_scheduled_job,
list_scheduled_jobs) is unchanged.
"""
from __future__ import annotations

import os
import platform as _platform
import plistlib
import shutil
import subprocess
from typing import NoReturn

__all__ = [
    "install_scheduled_job",
    "uninstall_scheduled_job",
    "list_scheduled_jobs",
    "LAUNCH_AGENTS_DIR",
]


LAUNCH_AGENTS_DIR = os.path.expanduser("~/Library/LaunchAgents")


def _linux_v2(_op: str) -> NoReturn:
    raise NotImplementedError(
        "Linux scheduling is a v2 plug-in point. "
        "See modules/autoheal/lib/autoheal.cron.template for the planned "
        "cron implementation; the macOS launchd path is in lib/sched_platform.py."
    )


def _unsupported(op: str) -> NoReturn:
    raise NotImplementedError(
        f"Platform not supported for {op}: {_platform.system()!r}. "
        "macOS (Darwin) is the only v1 target; Linux is a v2 plug-in seam."
    )


def install_scheduled_job(label: str, command: str, hour: int, minute: int) -> None:
    """Install a daily scheduled job to fire at HH:MM local time.

    macOS: writes a launchd plist at ~/Library/LaunchAgents/{label}.plist
    and bootstraps it via `launchctl bootstrap gui/$UID`. Idempotent — an
    existing job with the same label is bootout'd first.

    Linux: raises NotImplementedError (v2 seam).
    """
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        raise ValueError(f"Bad schedule: hour={hour}, minute={minute}")

    sysname = _platform.system()
    if sysname == "Darwin":
        _install_launchd(label, command, hour, minute)
        return
    if sysname == "Linux":
        _linux_v2("install_scheduled_job")
    _unsupported("install_scheduled_job")


def uninstall_scheduled_job(label: str) -> None:
    """Remove a previously-installed scheduled job.

    macOS: bootout the launchd job and delete its plist. Tolerates a
    missing plist (treats it as already-uninstalled).

    Linux: raises NotImplementedError.
    """
    sysname = _platform.system()
    if sysname == "Darwin":
        _uninstall_launchd(label)
        return
    if sysname == "Linux":
        _linux_v2("uninstall_scheduled_job")
    _unsupported("uninstall_scheduled_job")


def list_scheduled_jobs() -> list[str]:
    """Return labels of currently-installed scheduled jobs.

    macOS: reads ~/Library/LaunchAgents and returns the basename
    (without .plist) of every plist whose Label matches the file name.
    Cheap and doesn't shell out.

    Linux: raises NotImplementedError.
    """
    sysname = _platform.system()
    if sysname == "Darwin":
        return _list_launchd()
    if sysname == "Linux":
        _linux_v2("list_scheduled_jobs")
    _unsupported("list_scheduled_jobs")


def _plist_path(label: str) -> str:
    return os.path.join(LAUNCH_AGENTS_DIR, f"{label}.plist")


def _gui_target() -> str:
    uid = os.getuid()
    return f"gui/{uid}"


def _install_launchd(label: str, command: str, hour: int, minute: int) -> None:
    os.makedirs(LAUNCH_AGENTS_DIR, exist_ok=True)
    path = _plist_path(label)

    # Best-effort uninstall first so a config change takes effect.
    if os.path.exists(path):
        _uninstall_launchd(label)

    plist = {
        "Label": label,
        "ProgramArguments": ["/bin/sh", "-c", command],
        "StartCalendarInterval": {"Hour": hour, "Minute": minute},
        "RunAtLoad": False,
        "StandardOutPath": os.path.expanduser(f"~/.claude/logs/{label}.out.log"),
        "StandardErrorPath": os.path.expanduser(f"~/.claude/logs/{label}.err.log"),
        "EnvironmentVariables": {
            "PATH": "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin",
        },
    }
    os.makedirs(os.path.expanduser("~/.claude/logs"), exist_ok=True)
    with open(path, "wb") as fh:
        plistlib.dump(plist, fh)

    if shutil.which("launchctl"):
        # bootstrap is the modern (Big Sur+) way; ignore non-zero on
        # already-loaded (launchctl is grumpy about idempotency).
        subprocess.run(
            ["launchctl", "bootstrap", _gui_target(), path],
            check=False,
            capture_output=True,
        )


def _uninstall_launchd(label: str) -> None:
    path = _plist_path(label)
    if shutil.which("launchctl") and os.path.exists(path):
        subprocess.run(
            ["launchctl", "bootout", _gui_target(), path],
            check=False,
            capture_output=True,
        )
    if os.path.exists(path):
        try:
            os.remove(path)
        except OSError:
            pass


def _list_launchd() -> list[str]:
    if not os.path.isdir(LAUNCH_AGENTS_DIR):
        return []
    labels: list[str] = []
    for entry in os.listdir(LAUNCH_AGENTS_DIR):
        if entry.endswith(".plist"):
            labels.append(entry[: -len(".plist")])
    labels.sort()
    return labels
