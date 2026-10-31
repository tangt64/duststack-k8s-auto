"""Verify pinned chart bytes, lint and render without contacting a cluster."""
import hashlib
import io
import json
import os
from pathlib import Path
import platform
import subprocess
import tarfile
import urllib.request

import yaml
from ansible.parsing.dataloader import DataLoader
from ansible.template import Templar, trust_as_template

ROOT = Path(__file__).resolve().parents[1]
CACHE = ROOT / '.tools/charts'


def fetch(url, digest, destination):
    if destination.is_file() and hashlib.sha256(destination.read_bytes()).hexdigest() == digest:
        return destination.read_bytes()
    if not url.startswith('https://'):
        raise ValueError('HTTPS artifact URL required')
    data = urllib.request.urlopen(url, timeout=60).read()
    if hashlib.sha256(data).hexdigest() != digest:
        raise ValueError('Artifact SHA-256 mismatch: ' + url)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(data)
    return data


def helm_binary():
    if os.environ.get('HELM_BINARY'):
        return os.environ['HELM_BINARY']
    arch = {'x86_64': 'amd64', 'aarch64': 'arm64'}.get(platform.machine())
    if platform.system() != 'Linux' or not arch:
        raise RuntimeError('Chart validation requires Linux amd64/arm64 or HELM_BINARY')
    config = yaml.safe_load((ROOT / 'roles/common/cli-tool/defaults/main.yaml').read_text(encoding='utf-8'))['cli_tool_catalog']['helm']
    url = config['url'].replace('{{ cli_tool_arch }}', arch)
    data = fetch(url, config['sha256'][arch], ROOT / '.tools' / ('helm-' + arch + '.tar.gz'))
    with tarfile.open(fileobj=io.BytesIO(data), mode='r:gz') as archive:
        executable = archive.extractfile('linux-' + arch + '/helm').read()
    path = ROOT / '.tools/bin/helm-validation'
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(executable)
    path.chmod(0o755)
    return str(path)


def main():
    CACHE.mkdir(parents=True, exist_ok=True)
    binary = helm_binary()
    settings = {}
    for name in ['default', 'addons']:
        settings.update(yaml.safe_load((ROOT / 'inventory/group_vars/kubernetes' / name).read_text(encoding='utf-8')))
    cases = [('cilium', 'cni/cni-cilium', 'kube-system', '1.36.6', 'standard'),
             ('nfs', 'storage/csi-nfs', 'kube-system', '1.37.2', 'standard'),
             ('rook', 'storage/csi-rook', 'rook-ceph', '1.36.6', 'standard'),
             ('rook', 'storage/csi-rook', 'rook-ceph', '1.36.6', 'legacy-lab')]
    report = []
    for key, role, namespace, kube_version, profile in cases:
        case_id = key if profile == 'standard' else key + '-' + profile
        case_settings = dict(settings)
        if profile == 'legacy-lab':
            case_settings.update(yaml.safe_load((ROOT / 'profiles/rook-csi-legacy-lab.yaml').read_text(encoding='utf-8')))
        chart = settings['addon_chart_catalog'][key]
        path = CACHE / chart['asset']
        fetch(chart['url'], chart['sha256'], path)
        text = (ROOT / 'roles' / role / 'templates/values.yaml.j2').read_text(encoding='utf-8')
        values = Templar(loader=DataLoader(), variables=case_settings).template(trust_as_template(text))
        value_file = CACHE / (case_id + '-test-values.yaml')
        value_file.write_text(values, encoding='utf-8')
        common = [str(path), '--namespace', namespace, '--values', str(value_file), '--kube-version', kube_version]
        lint = subprocess.run([binary, 'lint', *common], capture_output=True, text=True)
        if lint.returncode:
            raise RuntimeError(lint.stdout + lint.stderr)
        result = subprocess.run([binary, 'template', key, *common, '--include-crds'], capture_output=True, text=True)
        if result.returncode:
            raise RuntimeError(result.stdout + result.stderr)
        resources = [x for x in yaml.safe_load_all(result.stdout) if x]
        if not resources or not any(x.get('kind') in ['DaemonSet', 'Deployment'] for x in resources):
            raise RuntimeError('Expected controller resources missing: ' + key)
        if key == 'rook':
            image_set = next(x for x in resources if x.get('kind') == 'ConfigMap' and x['metadata']['name'] == 'rook-csi-operator-image-set-configmap')
            version = case_settings['rook_csi_version']
            expected = 'quay.io/cephcsi/cephcsi:' + version + '@sha256:' + case_settings['rook_csi_image_digests'][version]
            if image_set['data']['plugin'] != expected:
                raise RuntimeError('Rendered CSI image does not match the reviewed digest: ' + profile)
        (CACHE / (case_id + '-rendered.yaml')).write_text(result.stdout, encoding='utf-8')
        report.append({'chart': key, 'profile': profile, 'version': chart['version'], 'sha256': chart['sha256'], 'kubernetes': kube_version, 'resources': len(resources)})
    (ROOT / '.tools/chart-validation.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    for row in report:
        print('Chart verified:', row['chart'], row['profile'], row['version'], str(row['resources']) + ' rendered resources')


if __name__ == '__main__':
    main()
