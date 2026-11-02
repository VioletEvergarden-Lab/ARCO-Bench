"""Run-local artifacts, with immutable inputs and atomic result replacement."""
from pathlib import Path
import csv
import json
import os
from contextlib import contextmanager
from benchmark.data import ROOT, canonical


@contextmanager
def run_lock(root):
    """OS-owned lock: process exit releases it, including after interruption."""
    with (root / '.run.lock').open('a+b') as f:
        try:
            if os.fstat(f.fileno()).st_size == 0:
                f.write(b'0'); f.flush()
            f.seek(0)
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            raise RuntimeError('Another process is using this run directory') from None
        try:
            yield
        finally:
            f.seek(0)
            if os.name == 'nt':
                msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(f.fileno(), fcntl.LOCK_UN)


def output_path(path):
    path = path.resolve()
    if path == ROOT or ROOT.is_relative_to(path):
        raise ValueError('Choose a separate run directory')
    if path.is_relative_to(ROOT) and path.relative_to(ROOT).parts[0] not in ('runs', 'local_results'):
        raise ValueError('Inside the package, use runs/ or local_results/; benchmark inputs are read-only')
    return path


def write(path, value, immutable=False):
    data = canonical(value) + b'\n'
    path.parent.mkdir(parents=True, exist_ok=True)
    if immutable:
        with path.open('xb') as f:
            f.write(data); f.flush(); os.fsync(f.fileno())
    else:
        tmp = path.with_name(path.name + '.tmp')
        with tmp.open('wb') as f:
            f.write(data); f.flush(); os.fsync(f.fileno())
        tmp.replace(path)


def jsonl(path, rows):
    tmp = path.with_name(path.name + '.tmp')
    with tmp.open('wb') as f:
        for row in rows:
            f.write(canonical(row) + b'\n')
    tmp.replace(path)


def table(path, rows):
    keys = list(dict.fromkeys(k for r in rows for k in r))
    with path.open('w', encoding='utf-8-sig', newline='') as f:
        writer = csv.DictWriter(f, keys); writer.writeheader()
        writer.writerows({k: json.dumps(v, ensure_ascii=False) if isinstance(v, (dict, list)) else v for k, v in r.items()} for r in rows)
