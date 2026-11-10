"""Release bundle construction and version tagging for Phase 17."""
import hashlib
import json
import os
import re
import subprocess
import zipfile
from datetime import datetime, timezone

VERSION_RE = re.compile(r'^\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?$')
ARCHIVE_ROOT = 'choregremlin'
EXCLUDED_DIRS = {
    '.git', '__pycache__', 'venv', '.venv', 'env', 'instance', 'dist',
    'releases', 'uploads', 'node_modules', '.pytest_cache', '.mypy_cache',
    '.ruff_cache', 'htmlcov',
}
EXCLUDED_SUFFIXES = (
    '.pyc', '.pyo', '.db', '.db-wal', '.db-shm', '.sqlite', '.sqlite3',
    '.log',
)
EXCLUDED_FILES = {'.env', 'choregremlin.db', '.DS_Store'}


class ReleaseError(ValueError):
    pass


def validate_version(version):
    version = (version or '').strip()
    if not VERSION_RE.match(version):
        raise ReleaseError('Version must look like 1.2.3 (optional -rc1 suffix).')
    return version


def read_version(root):
    path = os.path.join(root, 'VERSION')
    try:
        with open(path, encoding='utf-8') as handle:
            value = handle.read().strip()
    except OSError:
        return '0.0.0'
    try:
        return validate_version(value)
    except ReleaseError:
        return '0.0.0'


def write_version(root, version):
    version = validate_version(version)
    with open(os.path.join(root, 'VERSION'), 'w', encoding='utf-8') as handle:
        handle.write(version + '\n')
    return version


def bump_version(version, part='minor'):
    core = validate_version(version).split('-')[0].split('+')[0]
    major, minor, patch = (int(bit) for bit in core.split('.'))
    if part == 'major':
        major, minor, patch = major + 1, 0, 0
    elif part == 'minor':
        minor, patch = minor + 1, 0
    elif part == 'patch':
        patch += 1
    else:
        raise ReleaseError('Bump part must be major, minor or patch.')
    return f'{major}.{minor}.{patch}'


def tag_name(version):
    return 'v' + validate_version(version)


def bundle_filename(version):
    return f'ChoreGremlin-{tag_name(version)}.zip'


def _iter_release_files(root, out_dir=None):
    root = os.path.abspath(root)
    out_dir = os.path.abspath(out_dir) if out_dir else None
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(
            name for name in dirnames
            if name not in EXCLUDED_DIRS and not name.startswith('.')
        )
        for name in sorted(filenames):
            if name in EXCLUDED_FILES or name.endswith(EXCLUDED_SUFFIXES):
                continue
            if name.startswith('.') and name != '.gitignore':
                continue
            path = os.path.abspath(os.path.join(dirpath, name))
            if out_dir and (path == out_dir or path.startswith(out_dir + os.sep)):
                continue
            yield path


def checksum(path):
    digest = hashlib.sha256()
    with open(path, 'rb') as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def human_size(num_bytes):
    size = float(num_bytes or 0)
    for unit in ('B', 'KB', 'MB', 'GB'):
        if size < 1024 or unit == 'GB':
            return f'{size:.0f} {unit}' if unit == 'B' else f'{size:.1f} {unit}'
        size /= 1024
    return f'{size:.1f} GB'


def build_bundle(root, version=None, out_dir=None, notes=None):
    root = os.path.abspath(root)
    version = validate_version(version or read_version(root))
    out_dir = os.path.abspath(out_dir or os.path.join(root, 'dist'))
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, bundle_filename(version))
    files = list(_iter_release_files(root, out_dir))

    built_at = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    manifest = {
        'name': 'Chore Gremlin',
        'version': version,
        'tag': tag_name(version),
        'built_at': built_at,
        'file_count': len(files),
    }
    if notes:
        manifest['notes'] = notes

    with zipfile.ZipFile(path, 'w', zipfile.ZIP_DEFLATED) as archive:
        for file_path in files:
            relative = os.path.relpath(file_path, root)
            archive.write(file_path, os.path.join(ARCHIVE_ROOT, relative))
        archive.writestr(
            os.path.join(ARCHIVE_ROOT, 'RELEASE_INFO.json'),
            json.dumps(manifest, indent=2) + '\n',
        )

    size_bytes = os.path.getsize(path)
    return {
        'path': path,
        'filename': os.path.basename(path),
        'version': version,
        'tag': tag_name(version),
        'size_bytes': size_bytes,
        'size_human': human_size(size_bytes),
        'checksum': checksum(path),
        'file_count': len(files) + 1,
        'created_at': built_at,
    }


def list_bundles(out_dir):
    if not os.path.isdir(out_dir):
        return []
    bundles = []
    for name in os.listdir(out_dir):
        if not name.lower().endswith('.zip'):
            continue
        path = os.path.join(out_dir, name)
        if not os.path.isfile(path):
            continue
        stat = os.stat(path)
        bundles.append({
            'filename': name,
            'size_bytes': stat.st_size,
            'size_human': human_size(stat.st_size),
            'created_at': datetime.fromtimestamp(
                stat.st_mtime, timezone.utc
            ).strftime('%Y-%m-%d %H:%M UTC'),
            'checksum': checksum(path),
        })
    return sorted(bundles, key=lambda item: item['filename'], reverse=True)


def tag_release(root, version, message=None, runner=subprocess.run):
    version = validate_version(version)
    tag = tag_name(version)
    message = message or f'Chore Gremlin {tag}'
    command = ['git', 'tag', '-a', tag, '-m', message]
    try:
        result = runner(
            command, cwd=root, capture_output=True, text=True, timeout=30,
        )
    except Exception as exc:  # pragma: no cover - unexpected runner failure
        return {'status': 'error', 'tag': tag, 'output': str(exc)}
    output = ((result.stdout or '') + (result.stderr or '')).strip()
    if getattr(result, 'returncode', 1) == 0:
        return {'status': 'tagged', 'tag': tag, 'output': output}
    lowered = output.lower()
    status = 'exists' if 'already exists' in lowered else 'error'
    return {'status': status, 'tag': tag, 'output': output}


def changelog_excerpt(root, limit=40):
    path = os.path.join(root, 'CHANGELOG.md')
    try:
        with open(path, encoding='utf-8') as handle:
            lines = handle.readlines()
    except OSError:
        return ''
    return ''.join(lines[:limit]).strip()
