"""Add a KAM TokenReview webhook to kubeadm's static Pod without changing native auth."""
import argparse
import hashlib
import json
import os
import sys
from pathlib import Path
import tempfile
import yaml

DIRECTORY = '/etc/kubernetes/kiki-kam'
CONFIG = DIRECTORY + '/webhook.yaml'


def inspect(document):
    containers = document['spec']['containers']
    api = next(c for c in containers if c['name'] == 'kube-apiserver')
    if document.get('kind') != 'Pod':
        raise ValueError('Expected a kube-apiserver static Pod')
    flags = {}
    command = api.get('command', []) + api.get('args', [])
    for word in command:
        if word.startswith('--') and '=' in word:
            name, value = word[2:].split('=', 1)
            if name in flags:
                raise ValueError('Duplicate API server flag: ' + name)
            flags[name] = value
    audience = flags.get('api-audiences', flags.get('service-account-issuer', '')).split(',')[0]
    if not audience or 'client-ca-file' not in flags or 'service-account-issuer' not in flags:
        raise ValueError('Existing client certificate/ServiceAccount auth and audience are required')
    return api, flags, audience


def configure(document, cache_ttl='5s'):
    api, flags, audience = inspect(document)
    existing = flags.get('authentication-token-webhook-config-file')
    if any(word in ('--authentication-token-webhook-config-file', '--authentication-token-webhook-version',
                     '--authentication-token-webhook-cache-ttl') for word in api.get('command', []) + api.get('args', [])):
        raise ValueError('Use unambiguous --flag=value webhook arguments')
    if existing and existing != CONFIG:
        raise ValueError('Refusing to replace another authentication webhook')
    desired = {'authentication-token-webhook-config-file': CONFIG,
               'authentication-token-webhook-version': 'v1',
               'authentication-token-webhook-cache-ttl': cache_ttl}
    if cache_ttl not in {'1s', '5s', '10s'}:
        raise ValueError('Choose a reviewed webhook cache TTL: 1s/5s/10s')
    for field in ['command', 'args']:
        if field in api:
            api[field] = [word for word in api[field] if not any(
                word == '--' + key or word.startswith('--' + key + '=') for key in desired)]
    api.setdefault('command', []).extend('--' + key + '=' + value for key, value in desired.items())
    volumes = document['spec'].setdefault('volumes', [])
    mounts = api.setdefault('volumeMounts', [])
    for volume in volumes:
        if volume['name'] == 'kiki-kam-webhook' and volume.get('hostPath', {}).get('path') != DIRECTORY:
            raise ValueError('Conflicting webhook volume')
    for mount in mounts:
        if mount['name'] == 'kiki-kam-webhook' and (mount.get('mountPath') != DIRECTORY or not mount.get('readOnly')):
            raise ValueError('Conflicting webhook mount')
    if not any(v['name'] == 'kiki-kam-webhook' for v in volumes):
        volumes.append({'name': 'kiki-kam-webhook', 'hostPath': {'path': DIRECTORY, 'type': 'Directory'}})
    if not any(v['name'] == 'kiki-kam-webhook' for v in mounts):
        mounts.append({'name': 'kiki-kam-webhook', 'mountPath': DIRECTORY, 'readOnly': True})
    return document, audience


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--manifest', default='/etc/kubernetes/manifests/kube-apiserver.yaml')
    p.add_argument('--inspect', action='store_true')
    p.add_argument('--stdin-render', action='store_true')
    p.add_argument('--cache-ttl', default='5s')
    args = p.parse_args()
    path = Path(args.manifest)
    before = sys.stdin.buffer.read() if args.stdin_render else path.read_bytes()
    document = yaml.safe_load(before)
    _, _, audience = inspect(document)
    if args.inspect:
        print(json.dumps({'audience': audience}))
        return
    configured, _ = configure(document, args.cache_ttl)
    if args.stdin_render:
        print(json.dumps({'changed': configured != yaml.safe_load(before), 'audience': audience,
                          'manifest': yaml.safe_dump(configured, sort_keys=False)}))
        return
    if configured == yaml.safe_load(before):
        print(json.dumps({'changed': False, 'audience': audience}))
        return
    directory = Path(DIRECTORY)
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    backup_dir = directory / 'backups'
    backup_dir.mkdir(mode=0o700, exist_ok=True)
    digest = hashlib.sha256(before).hexdigest()
    backup = backup_dir / (digest + '-kube-apiserver.yaml')
    if not backup.exists():
        backup.write_bytes(before)
        backup.chmod(0o600)
    # Never leave backups or temporary manifests in kubelet's watched directory.
    with tempfile.NamedTemporaryFile(dir=directory, delete=False) as handle:
        temporary = Path(handle.name)
        try:
            handle.write(yaml.safe_dump(configured, sort_keys=False).encode())
            handle.flush()
            os.fsync(handle.fileno())
            temporary.chmod(path.stat().st_mode & 0o777)
            temporary.replace(path)
        finally:
            temporary.unlink(missing_ok=True)
    print(json.dumps({'changed': True, 'audience': audience, 'backup': str(backup)}))


if __name__ == '__main__':
    main()
