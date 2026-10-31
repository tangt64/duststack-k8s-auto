"""Local integration: HTTPS download, offline sources, retries and failures.

Generated archives, test executables, CA keys and install paths use an isolated
temporary directory (.tools by default; CLI_TEST_TEMP_DIR overrides its parent). No cluster APIs, real host install directories or external downloads.
"""
import copy
import functools
import hashlib
import http.server
import io
import json
import os
from pathlib import Path
import ssl
import sys
import subprocess
import tarfile
import tempfile
import threading

ROOT = Path(__file__).resolve().parents[1]
PAYLOAD = b'#!/bin/sh\necho duststack-fixture\n'


class QuietHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *_):
        pass


def main():
    (ROOT / '.tools').mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='cli-integration-', dir=os.environ.get('CLI_TEST_TEMP_DIR', str(ROOT / '.tools'))) as tmp:
        root = Path(tmp)
        archive = root / 'fixture.tar.gz'
        with tarfile.open(archive, 'w:gz') as stream:
            member = tarfile.TarInfo('clusteradm')
            member.size, member.mode = len(PAYLOAD), 0o755
            stream.addfile(member, io.BytesIO(PAYLOAD))
        bad_archive = root / 'fixture-bad.tar.gz'
        with tarfile.open(bad_archive, 'w:gz') as stream:
            member = tarfile.TarInfo('unexpected-file')
            member.size, member.mode = len(PAYLOAD), 0o755
            stream.addfile(member, io.BytesIO(PAYLOAD))
        raw = root / 'fixture.raw'
        raw.write_bytes(PAYLOAD)
        for mode in ('controller', 'target', 'empty', 'tampered'):
            for tool, source in [('clusteradm', archive), ('virtctl', raw)]:
                path = root / mode / tool / 'v1.2.3' / 'linux-amd64' / source.name
                path.parent.mkdir(parents=True)
                path.write_bytes(b'' if mode == 'empty' else b'invalid' if mode == 'tampered' else source.read_bytes())
        bad_path = root / 'controller/clusteradm/v1.2.3/linux-amd64' / bad_archive.name
        bad_path.write_bytes(bad_archive.read_bytes())
        subprocess.run(['openssl' , 'req', '-x509', '-newkey', 'rsa:2048', '-nodes',
                        '-keyout', str(root / 'ca.key'), '-out', str(root / 'ca.crt'),
                        '-days', '1', '-subj', '/CN=127.0.0.1',
                        '-addext', 'subjectAltName=IP:127.0.0.1'], check=True, capture_output=True)
        server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), functools.partial(QuietHandler, directory=str(root)))
        tls = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        tls.load_cert_chain(root / 'ca.crt', root / 'ca.key')
        server.socket = tls.wrap_socket(server.socket, server_side=True)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        catalog = {}
        for tool, source in [('clusteradm', archive), ('virtctl', raw)]:
            catalog[tool] = {'version': 'v1.2.3', 'asset': source.name,
                             'url': f'https://127.0.0.1:{server.server_port}/{source.name}',
                             'sha256': {'amd64': hashlib.sha256(source.read_bytes()).hexdigest()},
                             'archive_member': 'clusteradm' if tool == 'clusteradm' else ''}
        bad_catalog = copy.deepcopy(catalog)
        bad_catalog['clusteradm'].update(asset=bad_archive.name,
                                         sha256={'amd64': hashlib.sha256(bad_archive.read_bytes()).hexdigest()})
        variables = root / 'vars.json'
        variables.write_text(json.dumps({'cli_fixture_root': str(root), 'cli_fixture_catalog': catalog, 'cli_fixture_bad_catalog': bad_catalog, 'ansible_python_interpreter': sys.executable, 'ansible_remote_tmp': str(root / 'ansible-tmp')}), encoding='utf-8')
        try:
            result = subprocess.run(['ansible-playbook', '-i', 'localhost,', 'tests/cli-tools.yaml', '-e', '@' + str(variables)],
                                    cwd=ROOT, env=os.environ.copy(), capture_output=True, text=True)
            if result.returncode:
                (ROOT / '.tools/cli-integration-failure.log').write_text(result.stdout + result.stderr, encoding='utf-8')
                print(result.stdout[-12000:])
                print(result.stderr)
                raise SystemExit(result.returncode)
            for mode in ('download', 'controller', 'target'):
                assert (root / 'bin' / mode / 'clusteradm').read_bytes() == PAYLOAD
                assert (root / 'bin' / mode / 'clusteradm').stat().st_mode & 0o777 == 0o755
            assert (root / 'bin/controller/virtctl').read_bytes() == PAYLOAD
            assert (root / 'bin/controller/virtctl').stat().st_mode & 0o777 == 0o755
            assert not list((root / 'cache').rglob('extract-*')), 'Extraction directories leaked'
            print('CLI integration passed: verified HTTPS download, controller/target staging, raw/archive installs, unchanged reinstall, missing/empty/tampered input metadata rejection and incomplete-archive cleanup.')
        finally:
            server.shutdown()
            server.server_close()
            thread.join()


if __name__ == '__main__':
    main()
