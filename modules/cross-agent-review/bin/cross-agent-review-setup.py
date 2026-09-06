#!/usr/bin/env python3
"""Own only the cross-agent-review Codex skill; never modify Codex config/auth."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile

OWNER = '.ccgm-owner.json'


def hashes(root):
    result = {}
    for path in root.rglob('*'):
        if path.name == OWNER or '__pycache__' in path.parts:
            continue
        if path.is_symlink():
            raise ValueError('Refusing symlink content: ' + str(path))
        if path.is_file():
            result[str(path.relative_to(root))] = hashlib.sha256(path.read_bytes()).hexdigest()
    return result


def manage(action, codex_home, source=None):
    target = codex_home / 'skills' / 'cross-agent-review'
    if target.is_symlink():
        raise ValueError('Existing skill is a symlink; no ownership assumed.')
    manifest = None
    if target.exists():
        marker = target / OWNER
        if not marker.is_file() or marker.is_symlink():
            raise ValueError('Existing skill is not owned by this installer.')
        manifest = json.loads(marker.read_text())
        if manifest.get('owner') != 'ccgm/cross-agent-review' or not isinstance(manifest.get('files'), dict):
            raise ValueError('Invalid ownership manifest.')
        current = hashes(target)
        for relative, expected in manifest['files'].items():
            parts = Path(relative).parts
            if Path(relative).is_absolute() or '..' in parts or current.get(relative) != expected:
                raise ValueError('Owned skill content changed; preserve and reconcile before ' + action + '.')
    if action == 'remove':
        if manifest is None:
            return {'status': 'ABSENT'}
        for relative in manifest['files']:
            (target / relative).unlink()
        (target / OWNER).unlink()
        for path in sorted(target.rglob('*'), key=lambda value: len(value.parts), reverse=True):
            if path.is_dir():
                try:
                    path.rmdir()
                except OSError:
                    pass
        try:
            target.rmdir()
        except OSError:
            pass
        return {'status': 'REMOVED', 'user_files_preserved': target.exists()}
    source = source or Path(__file__).resolve().parents[1] / 'skills' / 'cross-agent-review'
    if not (source / 'SKILL.md').is_file():
        raise ValueError('Skill source is missing.')
    content = hashes(source)
    if manifest and set(current) != set(manifest['files']):
        raise ValueError('Additional user files exist; preserve them before upgrading.')
    if manifest and current == content:
        return {'status': 'CURRENT'}
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.ccgm-skill-', dir=target.parent) as temporary:
        staged = Path(temporary) / 'new'
        shutil.copytree(source, staged, ignore=shutil.ignore_patterns('__pycache__', OWNER))
        (staged / OWNER).write_text(json.dumps({'owner': 'ccgm/cross-agent-review', 'version': 1,
                                               'files': content}, indent=2) + '\n')
        backup = Path(temporary) / 'previous'
        if target.exists():
            target.rename(backup)
        try:
            staged.rename(target)
        except BaseException:
            if backup.exists():
                backup.rename(target)
            raise
    return {'status': 'INSTALLED', 'skill': str(target)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('install', 'remove'))
    parser.add_argument('--codex-home', type=Path,
                        default=Path(os.environ.get('CODEX_HOME', str(Path.home() / '.codex'))))
    args = parser.parse_args()
    try:
        print(json.dumps(manage(args.action, args.codex_home)))
    except (OSError, ValueError) as error:
        parser.exit(2, str(error) + '\n')


if __name__ == '__main__':
    main()
