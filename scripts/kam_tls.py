#!/usr/bin/env python3
"""Run the independently pinned local TLS preparation helper."""
from pathlib import Path
from kam_source import source_path

if __name__ == '__main__':
    target = source_path() / 'deploy/make_tls.py'
    exec(compile(Path(target).read_bytes(), str(target), 'exec'), globals())
