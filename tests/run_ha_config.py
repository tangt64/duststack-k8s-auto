"""Validate rendered configs with the locally cached official HAProxy image."""
from pathlib import Path
import subprocess
import tempfile
from test_configuration import variables, render


def main():
    image = subprocess.check_output(['podman', 'image', 'inspect', 'docker.io/library/haproxy:3.2', '--format', '{{.Id}}'], text=True).strip()
    with tempfile.TemporaryDirectory(prefix='ha-config-') as directory:
        root = Path(directory)
        root.chmod(0o755)  # Container's unprivileged UID must traverse the test directory.
        subprocess.run(['openssl', 'req', '-x509', '-newkey', 'rsa:2048', '-nodes',
                        '-keyout', str(root / 'test.key'), '-out', str(root / 'kubernetes-ca.crt'),
                        '-days', '1', '-subj', '/CN=isolated-test'], check=True, capture_output=True)
        for ready in (False, True):
            text = render('roles/core/core-haproxy/templates/haproxy.conf.j2', variables(
                k8s_proxy_mode='haproxy_keepalived', k8s_lb_ready_checks=ready))
            (root / 'haproxy.cfg').write_text(text)
            subprocess.run(['podman', 'run', '--rm', '--network', 'none', '-v', directory + ':/etc/haproxy:ro,Z',
                            image, 'haproxy', '-c', '-f', '/etc/haproxy/haproxy.cfg'], check=True)
    print('HAPROXY_CONFIG_PASS bootstrap and CA-verified readiness; image=' + image)
    print('Not tested: VIP/VRRP and multi-VM failover')


if __name__ == '__main__':
    main()
