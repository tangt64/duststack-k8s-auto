"""Validate local dedicated KAM TLS material without printing keys or passwords."""
import argparse
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import subprocess
from urllib.parse import urlsplit


def command(*args, data=None):
    return subprocess.run(['openssl', *args], input=data, capture_output=True, check=True).stdout


def validate(directory, url):
    endpoint = urlsplit(url)
    if endpoint.scheme != 'https' or not endpoint.hostname or endpoint.username or endpoint.password or endpoint.path or endpoint.query or endpoint.fragment:
        raise ValueError('Supply a bare HTTPS authentication origin')
    endpoint.port  # Validate the port syntax, too.
    folder = Path(directory)
    for name in ['kam-ca.crt', 'kam-server.crt', 'kam-server.key', 'kam-apiserver.crt', 'kam-apiserver.key']:
        path = folder / name
        if path.is_symlink() or not path.is_file():
            raise ValueError('Missing or symlink TLS file: ' + name)
        if name.endswith('.key') and os.name != 'nt' and path.stat().st_mode & 0o077:
            raise ValueError('Private TLS keys must have owner-only permissions')
    ca = str(folder / 'kam-ca.crt')
    command('x509', '-in', ca, '-checkend', '86400', '-noout')
    for name, purpose in [('kam-server', 'sslserver'), ('kam-apiserver', 'sslclient')]:
        cert, key = str(folder / (name + '.crt')), str(folder / (name + '.key'))
        command('x509', '-in', cert, '-checkend', '86400', '-noout')
        arguments = ['verify', '-CAfile', ca, '-purpose', purpose]
        if name == 'kam-server':
            try:
                ipaddress.ip_address(endpoint.hostname)
                arguments += ['-verify_ip', endpoint.hostname]
            except ValueError:
                arguments += ['-verify_hostname', endpoint.hostname]
        command(*arguments, cert)
        public = command('pkey', '-in', key, '-pubout', '-outform', 'DER')
        certificate_public = command('pkey', '-pubin', '-outform', 'DER', data=command('x509', '-in', cert, '-pubkey', '-noout'))
        if public != certificate_public:
            raise ValueError('Certificate and key do not match: ' + name)
    subject = command('x509', '-in', str(folder / 'kam-apiserver.crt'), '-noout', '-subject', '-nameopt', 'RFC2253').decode().strip().removeprefix('subject=')
    if subject != 'CN=kiki-kam-apiserver':
        raise ValueError('Dedicated webhook client subject must be exactly CN=kiki-kam-apiserver')
    return {'ca_fingerprint': hashlib.sha256(command('x509', '-in', ca, '-outform', 'DER')).hexdigest()}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--directory', required=True)
    parser.add_argument('--url', required=True)
    args = parser.parse_args()
    try:
        print(json.dumps(validate(args.directory, args.url)))
    except (ValueError, OSError, subprocess.CalledProcessError) as error:
        parser.exit(2, 'KAM TLS validation failed: ' + (str(error) if not isinstance(error, subprocess.CalledProcessError) else 'certificate validity, purpose, hostname or key validation failed') + '\n')
