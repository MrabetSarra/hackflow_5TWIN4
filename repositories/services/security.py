import re
import shutil
import uuid
import zipfile
import json
from pathlib import Path, PurePosixPath

from django.conf import settings
from django.core import signing
from django.core.exceptions import ValidationError


IGNORED_EXACT = {'.ds_store', '.env'}
IGNORED_DIRS = {'.git', 'node_modules', 'venv', '.venv', '__pycache__', '.idea', '.vscode'}
STAGE_SALT = 'repositories.upload-preview'


def normalize_repo_path(value):
    if not isinstance(value, str) or not value or '\x00' in value:
        raise ValidationError('The upload contains an invalid file path.')
    value = value.replace('\\', '/')
    raw_parts = value.split('/')
    path = PurePosixPath(value)
    if path.is_absolute() or re.match(r'^[a-zA-Z]:', value):
        raise ValidationError('Absolute file paths are not allowed.')
    parts = path.parts
    if not parts or any(part in ('', '.', '..') for part in raw_parts) or any(part == '..' for part in parts):
        raise ValidationError('The upload contains an unsafe file path.')
    if len(value) > 240 or any(len(part) > 100 for part in parts):
        raise ValidationError('The upload contains a file path that is too long.')
    if any(':' in part for part in parts):
        raise ValidationError('The upload contains an unsafe file path.')
    windows_devices = {'con', 'prn', 'aux', 'nul'}
    for part in parts:
        stem = part.split('.', 1)[0].lower()
        if any(ord(character) < 32 or character in '<>"|?*' for character in part):
            raise ValidationError('The upload contains a file path that is not supported by this server.')
        if part.endswith(('.', ' ')) or stem in windows_devices or re.fullmatch(r'(com|lpt)[1-9]', stem):
            raise ValidationError('The upload contains a file path that is not supported by this server.')
    if any(part.lower() in IGNORED_DIRS for part in parts):
        return None, True
    if any(part.lower() in IGNORED_EXACT for part in parts) or path.name.lower().endswith('.pyc'):
        return None, True
    return '/'.join(parts), False


def _read_upload(upload, total):
    max_file = settings.REPOSITORY_MAX_FILE_SIZE
    max_total = settings.REPOSITORY_MAX_TOTAL_UPLOAD_SIZE
    if upload.size > max_file:
        raise ValidationError(f'{upload.name}: files must be no larger than {max_file // (1024 * 1024)} MB.')
    if total + upload.size > max_total:
        raise ValidationError('The upload exceeds the total size limit.')
    chunks = []
    size = 0
    for chunk in upload.chunks():
        size += len(chunk)
        if size > max_file or total + size > max_total:
            raise ValidationError('The upload exceeds the configured size limit.')
        chunks.append(chunk)
    content = b''.join(chunks)
    if b'\x00' in content and size > settings.REPOSITORY_MAX_BINARY_FILE_SIZE:
        raise ValidationError(f'{upload.name}: binary files above {settings.REPOSITORY_MAX_BINARY_FILE_SIZE // (1024 * 1024)} MB are not allowed.')
    return content


def _zip_files(upload, total_budget):
    if upload.size > settings.REPOSITORY_MAX_TOTAL_UPLOAD_SIZE or total_budget + upload.size > settings.REPOSITORY_MAX_TOTAL_UPLOAD_SIZE:
        raise ValidationError('The ZIP archive exceeds the total upload size limit.')
    try:
        archive = zipfile.ZipFile(upload)
    except (zipfile.BadZipFile, OSError) as exc:
        raise ValidationError('Upload a valid ZIP archive or select files from a folder.') from exc
    output, ignored, expanded = {}, [], 0
    with archive:
        entries = archive.infolist()
        if len(entries) > settings.REPOSITORY_MAX_FILES:
            raise ValidationError('The ZIP archive contains too many files.')
        for info in entries:
            zip_path = info.filename[:-1] if info.is_dir() and info.filename.endswith('/') else info.filename
            normalized, skip = normalize_repo_path(zip_path)
            if skip:
                ignored.append(info.filename)
                continue
            if info.is_dir():
                continue
            # UNIX symlinks are not accepted, even when their target appears safe.
            if (info.external_attr >> 16) & 0o170000 == 0o120000:
                raise ValidationError('Symbolic links are not allowed in repository uploads.')
            if info.file_size > settings.REPOSITORY_MAX_FILE_SIZE:
                raise ValidationError(f'{info.filename}: files exceed the individual size limit.')
            expanded += info.file_size
            if expanded > settings.REPOSITORY_MAX_ZIP_UNCOMPRESSED_SIZE:
                raise ValidationError('The ZIP archive exceeds the uncompressed size limit.')
            if info.file_size and info.compress_size == 0:
                raise ValidationError('The ZIP archive contains an unsafe compression ratio.')
            ratio = info.file_size / max(info.compress_size, 1)
            if ratio > settings.REPOSITORY_MAX_COMPRESSION_RATIO:
                raise ValidationError('The ZIP archive contains an unsafe compression ratio.')
            if total_budget + expanded > settings.REPOSITORY_MAX_TOTAL_UPLOAD_SIZE:
                raise ValidationError('The upload exceeds the total size limit.')
            content = archive.read(info)
            if b'\x00' in content and len(content) > settings.REPOSITORY_MAX_BINARY_FILE_SIZE:
                raise ValidationError(f'{info.filename}: binary files above the size limit are not allowed.')
            if normalized in output:
                raise ValidationError('The ZIP archive contains duplicate file paths.')
            output[normalized] = content
    return output, ignored, expanded


def stage_uploads(uploads, user_id, relative_paths=None):
    if not uploads:
        raise ValidationError('Select a folder, ZIP archive, or one or more files.')
    total, files, ignored = 0, {}, []
    staging_root = settings.REPOS_ROOT / '.staging'
    staging_root.mkdir(parents=True, exist_ok=True)
    import time
    now = time.time()
    for old_stage in staging_root.iterdir():
        try:
            if old_stage.is_dir() and now - old_stage.stat().st_mtime > 60 * 60:
                shutil.rmtree(old_stage, ignore_errors=True)
        except OSError:
            continue
    relative_paths = relative_paths or []
    for index, upload in enumerate(uploads):
        if upload.name.lower().endswith('.zip'):
            extracted, skipped, size = _zip_files(upload, total)
            total += size
            for name, data in extracted.items():
                if name in files:
                    raise ValidationError('The upload contains duplicate file paths.')
                files[name] = data
            ignored.extend(skipped)
            if len(files) > settings.REPOSITORY_MAX_FILES:
                raise ValidationError('The upload contains too many files.')
            continue
        relative = relative_paths[index] if index < len(relative_paths) else upload.name
        normalized, skip = normalize_repo_path(relative)
        if skip:
            ignored.append(relative)
            continue
        data = _read_upload(upload, total)
        total += len(data)
        if normalized in files:
            raise ValidationError('The upload contains duplicate file paths.')
        files[normalized] = data
        if len(files) > settings.REPOSITORY_MAX_FILES:
            raise ValidationError('The upload contains too many files.')
    stage_id = uuid.uuid4().hex
    stage_dir = staging_root / stage_id
    stage_dir.mkdir(parents=True, exist_ok=False)
    try:
        for path, content in files.items():
            target = stage_dir / 'files' / Path(*PurePosixPath(path).parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content)
        (stage_dir / 'manifest.txt').write_text('\n'.join(files), encoding='utf-8')
        (stage_dir / 'ignored.txt').write_text('\n'.join(ignored), encoding='utf-8')
        from ..ai import scan_secrets
        findings = []
        for path, content in files.items():
            if len(content) > 1024 * 1024:
                findings.append({'path': path, 'kind': 'large_file', 'line': 0, 'blocked': False})
            if b'\x00' in content:
                findings.append({'path': path, 'kind': 'binary_file', 'line': 0, 'blocked': False})
            try:
                source = content.decode('utf-8')
            except UnicodeDecodeError:
                continue
            findings.extend({'path': path, **finding} for finding in scan_secrets(source))
        if settings.REPOSITORY_BLOCK_PRIVATE_KEYS and any(item['kind'] == 'private_key' for item in findings):
            raise ValidationError('A private key was detected in the upload. Remove it before pushing.')
        (stage_dir / 'secret-findings.json').write_text(json.dumps(findings), encoding='utf-8')
        token = signing.dumps({'id': stage_id, 'user': user_id}, salt=STAGE_SALT)
        return token, stage_dir, sorted(ignored), len(files)
    except Exception:
        shutil.rmtree(stage_dir, ignore_errors=True)
        raise


def get_staged_upload(token, user_id):
    try:
        payload = signing.loads(token, salt=STAGE_SALT, max_age=60 * 60)
    except signing.SignatureExpired as exc:
        raise ValidationError('This upload preview expired. Upload the files again.') from exc
    except signing.BadSignature as exc:
        raise ValidationError('This upload preview is invalid. Upload the files again.') from exc
    if payload.get('user') != user_id or not re.fullmatch(r'[0-9a-f]{32}', payload.get('id', '')):
        raise ValidationError('This upload preview is invalid. Upload the files again.')
    stage_dir = settings.REPOS_ROOT / '.staging' / payload['id']
    if not stage_dir.is_dir():
        raise ValidationError('This upload preview is no longer available. Upload the files again.')
    return stage_dir


def staged_ignored_files(stage_dir):
    file_path = stage_dir / 'ignored.txt'
    return file_path.read_text(encoding='utf-8').splitlines() if file_path.is_file() else []


def staged_secret_findings(stage_dir):
    report = stage_dir / 'secret-findings.json'
    if not report.is_file():
        return []
    try:
        return json.loads(report.read_text(encoding='utf-8'))
    except (ValueError, OSError):
        return []


def remove_stage(stage_dir):
    shutil.rmtree(stage_dir, ignore_errors=True)
