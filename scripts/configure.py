"""Generate a complete, private, single-control-plane inventory without deploying."""
import argparse
import ipaddress
import os
from pathlib import Path
import re
import shlex

import yaml

ROOT = Path(__file__).resolve().parents[1]


def parse_node(text):
    try:
        name, addresses = text.split('=', 1)
        ssh, internal = addresses.split('@', 1)
        interface = ipaddress.ip_interface(internal)
    except ValueError as error:
        raise ValueError('Node format: name=SSH_ADDRESS@INTERNAL_IP/PREFIX') from error
    if not re.fullmatch(r'[a-z0-9]([a-z0-9.-]*[a-z0-9])?', name) or len(name) > 63:
        raise ValueError('Node name must be a DNS-compatible name of at most 63 characters')
    if not re.fullmatch(r'[A-Za-z0-9.-]+', ssh) or interface.version != 4:
        raise ValueError('Specify a hostname/IPv4 SSH address and an IPv4 internal CIDR')
    return name, {'ansible_host': ssh, 'nodename': name, 'k8s_ip4': str(interface)}


def build_inventory(args):
    control = parse_node(args.control)
    workers = [parse_node(text) for text in args.worker]
    nodes = [control, *workers]
    if len({n[0] for n in nodes}) != len(nodes):
        raise ValueError('Duplicate node names')
    if len({ipaddress.ip_interface(n[1]['k8s_ip4']).ip for n in nodes}) != len(nodes):
        raise ValueError('Duplicate internal node addresses')
    if not workers:
        raise ValueError('At least one worker is required; the control-plane taint is preserved')
    if not re.fullmatch(r'[A-Za-z0-9_.:-]+', args.interface):
        raise ValueError('Invalid interface name')
    settings = {}
    for name in ['default', 'addons']:
        settings.update(yaml.safe_load((ROOT / 'inventory/group_vars/kubernetes' / name).read_text(encoding='utf-8')))
    settings.update(ansible_user=args.ssh_user, k8s_interface=args.interface,
                    k8s_proxy_mode_enable=False, k8s_network=args.cni)
    if args.cni == 'cilium':
        settings.update(yaml.safe_load((ROOT / 'profiles/cilium.yaml').read_text(encoding='utf-8')))
    if args.storage == 'rook':
        # Ceph CSI 3.18 is tested through Kubernetes 1.36, including Calico installs.
        settings.update(k8s_version='1.36.6', crio_version='1.36.7')
        settings['rook_csi_cephx_key_type'] = getattr(args, 'rook_csi_key_type', 'aes')
        settings['rook_csi_legacy_lab'] = getattr(args, 'rook_csi_legacy_lab', False)
        if settings['rook_csi_legacy_lab']:
            if settings['rook_csi_cephx_key_type'] != 'aes':
                raise ValueError('Legacy CSI lab requires aes client keys; aes256k needs a newer CSI and supported kernel')
            settings['rook_csi_version'] = 'v3.16.3'
    for option, setting in [('pod_cidr', 'k8s_pod_cidr'), ('service_cidr', 'k8s_cluster_svc_ip')]:
        if getattr(args, option, None):
            settings[setting] = str(ipaddress.ip_network(getattr(args, option)))
    settings['k8s_csi_providers'] = [] if args.storage == 'none' else [args.storage]
    ceph = {}
    if args.storage == 'nfs':
        if not args.nfs_server or not args.nfs_share or not args.nfs_share.startswith('/'):
            raise ValueError('NFS requires --nfs-server and an absolute --nfs-share')
        settings.update(nfs_server=args.nfs_server, nfs_share=args.nfs_share, k8s_default_storage_class='nfs-csi')
    if args.storage == 'rook':
        for text in args.rook_device:
            name, device = text.split('=', 1)
            if name not in dict(workers) or not re.fullmatch(r'[A-Za-z0-9_-]+', device):
                raise ValueError('Each --rook-device must identify a worker and a device basename')
            ceph.setdefault(name, {'rook_devices': []})['rook_devices'].append(device)
        if len(ceph) < 3:
            raise ValueError('Rook requires explicit devices on at least three workers')
        settings.update(k8s_default_storage_class='rook-ceph-block', rook_confirm_devices=args.confirm_rook_devices)
    pod_net, service_net = (ipaddress.ip_network(settings[n]) for n in ['k8s_pod_cidr', 'k8s_cluster_svc_ip'])
    if pod_net.version != 4 or service_net.version != 4:
        raise ValueError('IPv4 pod and service ranges are required')
    if pod_net.overlaps(service_net) or any(ipaddress.ip_interface(n[1]['k8s_ip4']).network.overlaps(net) for n in nodes for net in [pod_net, service_net]):
        raise ValueError('Pod, service and internal node network ranges must not overlap; use --pod-cidr/--service-cidr for a new cluster')
    return {'all': {'vars': settings, 'children': {'kubernetes': {'children': {
        'k8s_master': {'hosts': {control[0]: control[1]}},
        'k8s_node': {'hosts': dict(workers)},
        'k8s_storage_ceph': {'hosts': ceph},
        'lb': {'hosts': {}}, 'k8s_hub': {'hosts': {}}, 'k8s_spoke': {'hosts': {}},
    }}}}}


def main():
    parser = argparse.ArgumentParser(description='단일 control plane 설치 인벤토리 생성 (배포하지 않음)')
    parser.add_argument('--control', help='cp1=192.0.2.10@10.10.10.10/24')
    parser.add_argument('--worker', action='append', default=[], help='worker1=SSH_ADDRESS@INTERNAL_IP/PREFIX (반복 가능)')
    parser.add_argument('--interface', default='eth1')
    parser.add_argument('--ssh-user', default='root')
    parser.add_argument('--cni', choices=['calico', 'flannel', 'cilium'], default='calico')
    parser.add_argument('--rook-csi-legacy-lab', action='store_true', help='Experimental x86-64-v2 lab: Ceph CSI 3.16.3 on Kubernetes 1.36, outside upstream tested range')
    parser.add_argument('--rook-csi-key-type', choices=['aes', 'aes256k'], default='aes', help='New cluster CSI key type; aes256k needs Linux 7.0+ or a verified backport')
    parser.add_argument('--pod-cidr', help='신규 클러스터 Pod IPv4 CIDR (예: 172.22.0.0/16)')
    parser.add_argument('--service-cidr', help='신규 클러스터 Service IPv4 CIDR (예: 172.23.0.0/16)')
    parser.add_argument('--storage', choices=['none', 'nfs', 'rook'], default='none')
    parser.add_argument('--nfs-server')
    parser.add_argument('--nfs-share')
    parser.add_argument('--rook-device', action='append', default=[])
    parser.add_argument('--confirm-rook-devices', action='store_true')
    parser.add_argument('--output', type=Path, default=ROOT / 'inventory/local-lab/hosts.yaml')
    parser.add_argument('--interactive', action='store_true')
    args = parser.parse_args()
    if args.interactive:
        args.control = args.control or input('Control plane (name=SSH@INTERNAL/PREFIX): ').strip()
        if not args.worker:
            args.worker = input('Workers (공백으로 구분): ').split()
        args.cni = input('CNI [calico/flannel/cilium] (calico): ').strip() or 'calico'
        args.storage = input('CSI [none/nfs/rook] (none): ').strip() or 'none'
        if args.cni not in ['calico', 'flannel', 'cilium'] or args.storage not in ['none', 'nfs', 'rook']:
            parser.error('지원하지 않는 CNI 또는 CSI입니다')
        if args.storage == 'nfs':
            args.nfs_server = input('NFS server: ').strip()
            args.nfs_share = input('NFS export: ').strip()
    if not args.control:
        parser.error('--control 또는 --interactive를 지정하세요')
    try:
        inventory = build_inventory(args)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open('x', encoding='utf-8', newline='\n') as file:
            os.chmod(args.output, 0o600)
            yaml.safe_dump(inventory, file, allow_unicode=True, sort_keys=False)
    except (ValueError, OSError) as error:
        parser.exit(2, str(error) + '\n')
    print('인벤토리 생성: ' + str(args.output))
    print('계획 확인: bash setup-k8s.sh plan -i ' + shlex.quote(str(args.output)))
    print('설치 실행: bash setup-k8s.sh install -i ' + shlex.quote(str(args.output)))


if __name__ == '__main__':
    main()
