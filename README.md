# Kubernetes 설치 자동화

Ansible과 kubeadm으로 RHEL 계열 호스트에 Kubernetes를 설치합니다. 2026-10-31 기준
최신 안정 릴리스인 **Kubernetes 1.37.2**에 맞춰 기본 설치 경로를 정비했습니다.

## 지원 범위와 버전

| 구성요소 | 기본값 |
| --- | --- |
| Kubernetes | 1.37.2 / kubeadm API v1beta4 |
| CRI-O | 1.37.2, 기본 런타임 |
| containerd | 2.4.2, 선택 가능 / config v3 |
| Calico | 3.33.0, 기본 CNI / VXLAN |
| Flannel | 0.28.10, 선택 가능 |
| Cilium | 1.20.4, Kubernetes 1.36.6 프로필 |
| NFS CSI | 4.13.6, 기존 NFS export에 선택 설치 |
| Rook/Ceph RBD | 1.21.1 / Ceph 20.2.4, 전용 디스크에 선택 설치 |
| Ceph CSI | 3.18.1 / Kubernetes 1.36.6 / x86-64-v3, v2 전용 랩의 3.16.3 실험 프로필 별도 |
| ansible-core | 2.21.5 |
| clusteradm CLI | 1.4.0, 별도 설치 |
| virtctl CLI | 1.9.1, 별도 설치 |
| Helm CLI | 4.3.1, 별도 설치 |

대상은 Rocky Linux·AlmaLinux·RHEL 9 이상, Linux 커널 5.10 이상, cgroup v2,
Python 3.9 이상입니다. 컨트롤러는 Linux 또는 WSL, Python 3.12~3.14를 사용합니다.
각 노드는 최소 2 CPU / 2 GiB RAM이 필요하며, 워크로드에 맞춰 별도로 산정하세요.
단일 control plane과 다중 control plane을 지원합니다. 단일 control plane만 있는
구성에서도 워크로드 실행에는 별도 worker를 권장합니다. 기본 taint는 유지합니다.

**이 플레이북은 신규 설치 및 같은 버전 재실행용입니다. 기존 1.28 클러스터를
1.37로 바로 업그레이드하지 않습니다.** 기존 kubelet·API 서버·런타임 버전이
요청값과 다르면 호스트 변경 전에 중단합니다. 업그레이드는 etcd 백업 후
공식 kubeadm 절차에 따라 minor 버전을 하나씩 진행해야 합니다.

Kubernetes 기본 설치와 CLI 도구 설치는 별도 플레이북입니다. `clusteradm`, `virtctl`,
`helm`은 검증된 릴리스 파일을 외부에서 공급합니다. 저장소에는 실행 바이너리를
포함하지 않습니다. 자동 다운로드와 수동 배치는 [도구 설치 안내](docs/TOOLS.md)를 참고하세요.

OCM·KubeVirt 서버 리소스, Dashboard/Ingress 확장, CentOS 7 기반 VM 프로비저닝,
수동 TLS/외부 etcd는 별도 검증이 필요한 레거시입니다. OCM·KubeVirt의 기존 역할은
CLI 설치로 연결되며, 과거의 init/join 명령이나 구형 매니페스트를 자동 실행하지 않습니다.
KubeVirt 서버 배포 전용 플레이북은 계속 중단합니다. 세부 보강 과제는
[검토 문서](docs/REVIEW.md)에 있습니다.

## 간편 시작과 CNI·CSI 선택

```bash
bash setup-k8s.sh deps
bash setup-k8s.sh configure --interactive
bash setup-k8s.sh plan -i inventory/local-lab/hosts.yaml
bash setup-k8s.sh install -i inventory/local-lab/hosts.yaml
```

[간편 설정](docs/SETUP.md)은 새 인벤토리를 생성하고 의존성 준비·계획·설치를 하나의
진입점으로 제공합니다. Cilium 1.20은 공식 검증 범위에 맞춰 Kubernetes 1.36.6과
CRI-O 1.36.7을 사용합니다. 기존 1.37 클러스터를 다운그레이드하거나 CNI를 교체하는
프로필이 아닙니다. 기본 Kubernetes 1.37.2/Calico 조합은 유지합니다.

NFS CSI와 Rook/Ceph를 기본 선택지로 제공하되 `k8s_csi_providers: []`로 시작합니다.
NFS 서버·export 또는 Rook 전용 빈 디스크와 3개 스토리지 worker를 지정해야 설치합니다.
데이터는 Retain으로 보존하고 기본 StorageClass 충돌과 기존 Ceph 재구성을 차단합니다.
설정·수동 차트 공급·요구사항은 [CNI·CSI 안내](docs/CNI-CSI.md), 웹 콘솔 검증은
[터미널랩 안내](docs/TERMINAL-LAB.md)를 참고하세요.

[실제 화면을 포함한 단계별 사용 안내](docs/TERMINAL-LAB-WALKTHROUGH.md)에서
랩 준비·명령 실행 방법과 예상 출력 예시를 확인할 수 있습니다.

## 준비

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
ansible-galaxy collection install -r requirements.yaml
```

`inventory/kubernetes.yaml`의 호스트 주소, `nodename`, `k8s_ip4`와
`inventory/group_vars/kubernetes/default`의 네트워크·버전을 환경에 맞게 설정하세요.
`kubernetes` 부모 그룹에서 control plane, worker, LB로 변수가 상속됩니다.
`k8s_ip4`는 이미 설정된 내부 NIC의 IPv4와 일치해야 합니다. 설치 중 NIC를
재구성하거나 sudo 정책, SSH 키, 기존 `/etc/hosts` 내용을 덮어쓰지 않습니다.
Calico 사용 시 NetworkManager가 Calico 가상 인터페이스에 개입하지 않도록 예외를 설정합니다.

SSH 키 인증이 기본이며 비밀번호를 저장소에 넣지 않습니다. 사용자 이름은
`ansible_user`, 키 경로는 `--private-key`로 지정할 수 있습니다. 비밀번호가 필요하면
`--ask-pass`, sudo 비밀번호는 `--ask-become-pass` 또는 Ansible Vault를 사용하세요.
SSH 호스트 키 검증은 활성화되어 있으므로 신뢰하는 호스트 키를 미리 등록하세요.

단일 control plane은 `k8s_proxy_mode_enable: false`로 설정합니다. 다중 control plane은
최소 3대의 control plane과 안정적인 API endpoint가 필요합니다.

- `haproxy`: 별도 `lb` 호스트를 사용하고 `k8s_api_domain`을 LB의 실제 내부 주소로
  DNS에 등록하세요. 샘플 LB는 10.10.10.250입니다. LB와 control plane은 분리합니다.
- `keepalived`: `k8s_vip_address`를 비어 있는 같은 L2 네트워크 주소로 지정하고
  API DNS를 VIP로 연결하세요. `keepalived_node`, `keepalived_pri`를 각 노드에
  설정합니다. API 상태 검사에 따라 VIP가 이동합니다. 네트워크에서 VRRP를 허용해야 합니다.

Pod CIDR, Service CIDR, 노드 주소는 겹치면 안 됩니다. Calico 기본 IPAM 블록은 /26이며
Pod CIDR은 /26 또는 더 넓어야 합니다. NAT·라우팅·방화벽에서 API 6443/TCP,
control plane 간 etcd 2379~2380/TCP, kubelet 10250/TCP, 노드 간 VXLAN
(Calico 4789/UDP, Flannel·Cilium 8472/UDP)을 필요한 노드 사이에 허용하세요.
NodePort를 사용할 때만 해당 포트 범위도 허용합니다.

호스트 방화벽을 자동으로 끄거나 전체 노드 대역을 무조건 허용하지 않습니다.
Calico와 충돌하는 활성 firewalld가 있으면 설치 전에 중단합니다. 경계 방화벽이나
Calico 호스트 정책으로 보호할 범위를 검토한 뒤 운영자가 정책을 적용해야 합니다.
SELinux는 기본 enforcing이며, permissive가 필요한 환경에서는 명시적으로 변경하세요.
SELinux 활성화에 재부팅이 필요하면 재부팅 후 다시 실행합니다.

CRI-O 패키지는 Kubernetes와 같은 minor 스트림의 서명된 저장소를 사용합니다.
containerd는 Docker CE의 서명된 RPM 저장소를 사용합니다. 선택한 OS·아키텍처에서
지정한 패키지 버전이 제공되는지 사전 확인하세요. 버전을 변경할 때는 Kubernetes,
런타임, CNI의 호환성도 함께 확인해야 합니다. Calico 버전을 바꾸면
`calico_manifests`의 파일 이름과 SHA-256도 공식 매니페스트에 맞춰 갱신하세요.

## 검증과 설치

[이중 LB HA·namespace KAM·GitHub/Gitea 운영 안내](docs/HA-KAM-GIT.md)를 제공합니다.
KAM은 명시적으로 설치하는 CRD/controller와 `kubectl kam` 플러그인이며 기본 설치에
관리자 권한 애드온을 자동 추가하지 않습니다.

```bash
bash scripts/validate.sh                         # 소스·문법·회귀 테스트
RUN_CLI_INTEGRATION=1 bash scripts/validate.sh   # 로컬 HTTPS/수동 배치 통합 검증
RUN_CHART_VALIDATION=1 bash scripts/validate.sh  # 공식 Cilium·CSI 차트 검증
ansible-inventory --graph
bash deploy-k8s.sh --list-hosts
bash deploy-k8s.sh --check                       # 준비 작업 예상 변경 확인
bash deploy-k8s.sh --private-key ~/.ssh/k8s_id_rsa
```

`--check`는 kubeadm 초기화·join·kubectl 적용을 생략합니다. 신규 클러스터 전체 설치의
성공을 보장하는 검증은 아닙니다. 래퍼는 실행 위치와 무관하게 프로젝트의 ansible.cfg를
사용하며 전달한 Ansible 옵션을 그대로 넘깁니다. WSL의 공유 마운트에서 직접
`ansible-playbook`을 쓸 때는 `export ANSIBLE_CONFIG="$PWD/ansible.cfg"`를 설정하세요.

런타임은 선택한 서비스만 설치합니다. kubeadm 초기화 실패 시 자동 reset하지 않으므로
오류를 확인하고 복구할 수 있습니다. 이미 설치된 노드는 초기화·join을 건너뜁니다.
join 토큰과 인증서 키는 실행 시 생성하며 로그에 출력하지 않고, join 설정 파일은
성공·실패 모두 정리합니다. API 감사 로그는 Metadata 수준으로 기본 활성화됩니다.
기본 설치 후 인벤토리의 각 노드가 Ready인지 확인하고 명시적으로 선택한 CSI를 설치합니다.

kubelet serving 인증서는 `serverTLSBootstrap`을 사용합니다. Metrics Server 등에서
kubelet HTTPS를 사용하기 전 CSR의 노드 이름과 주소를 검증하고 승인하세요.
자동으로 모든 CSR을 승인하거나 TLS 검증을 끄지 않습니다.

## CLI 도구 설치와 수동 배치

```bash
# 기본: clusteradm + virtctl, 버전·SHA-256을 고정한 자동 다운로드
ansible-playbook playbooks/k8s-tools.yaml --limit 192.168.10.10

# 컨트롤러의 artifacts/에 원본 릴리스 파일을 배치한 뒤 설치
ansible-playbook playbooks/k8s-tools.yaml --limit 192.168.10.10 \
  -e @examples/tools-controller.yaml

# 대상 서버의 /var/cache/duststack/incoming/에 미리 배치한 파일 사용
ansible-playbook playbooks/k8s-tools.yaml --limit 192.168.10.10 \
  -e @examples/tools-target.yaml

# Helm CLI만 설치
ansible-playbook playbooks/k8s-tools.yaml --limit 192.168.10.10 \
  -e '{"cli_tools":["helm"]}'
```

수동 파일은 `도구/버전/linux-아키텍처/공식 파일명` 구조로 배치합니다. 예를 들어
컨트롤러의 clusteradm은 `artifacts/clusteradm/v1.4.0/linux-amd64/clusteradm_linux_amd64.tar.gz`
입니다. tar.gz는 압축을 풀지 않은 원본을 배치합니다. 파일이 없거나 비어 있거나
체크섬이 다르면 기존 실행 파일을 교체하기 전에 중단합니다. 세 방식 모두 검증 후
기본 `/usr/local/bin/`에 0755로 설치하며 OCM·KubeVirt 리소스나 Helm 차트는 적용하지 않습니다.

전체 경로, 아키텍처, 사내 미러와 버전 변경 방법은 [docs/TOOLS.md](docs/TOOLS.md)에 있습니다.
`artifacts/`와 `.tools/`는 로컬 입력·검증 캐시이며 Git에 포함하지 않습니다.

## 제거

```bash
# 백업과 drain 후, 제거할 대상을 --limit로 명확하게 지정합니다.
bash remove-k8s.sh --limit 192.168.10.40 -e k8s_confirm_reset=true
```

`--limit`에는 인벤토리 호스트 키 또는 그룹을 사용하세요. 샘플 인벤토리의 호스트 키는
IP 주소이므로 예를 들어 `--limit 192.168.10.40`을 지정합니다.
명시적인 `k8s_confirm_reset=true`가 없으면 reset 전에 중단합니다.
reset은 로컬 etcd·인증서 등 클러스터 상태를 잃게 할 수 있습니다. CNI 구성과 관리자
kubeconfig도 제거합니다. 컨테이너 런타임, CNI 인터페이스, iptables/IPVS 규칙,
워크로드 데이터 볼륨은 완전히 정리하지 않으므로 재사용 전에 별도로 점검하세요.

## 검증 범위

회귀 테스트는 Ansible 2.21 템플릿 엔진으로 단일/HA, CRI-O/containerd,
control plane/worker join, CNI CIDR·NIC·호환성, 기존 버전·CNI 변경 차단,
CSI 데이터 보존·장치 가드와 인벤토리 생성을 확인합니다.
`KUBEADM_BINARY`에 kubeadm 1.37.2 경로를 지정하면 실제 스키마 검증도 수행합니다.
소스 검사에서 바이너리 재유입과 마크다운 로컬 링크 오류를 차단합니다.
CLI 통합 테스트는 로컬 HTTPS 서버와 임시 설치 경로로 다운로드·컨트롤러/대상 수동 배치,
재실행, 잘못된 파일의 거부를 확인합니다. `openssl`, `tar`, `gzip`이 필요합니다.
WSL의 Windows 공유 드라이브는 POSIX 권한과 원자적 rename 검증에 맞지 않을 수 있으므로
`CLI_TEST_TEMP_DIR=/tmp RUN_CLI_INTEGRATION=1 bash scripts/validate.sh`를 사용하세요.
CI에서도 소스·문법·회귀·CLI 통합 검증과 공식 차트 SHA-256·lint·렌더링을 실행합니다.
2026-11-01 전용 VM 4대에서는 Cilium 통신·NetworkPolicy, NFS RWX와 RBD의 교차 노드
재연결 입출력까지 12개 검사를 통과했습니다. 구형 CPU용 CSI와 AES 클라이언트 키의
호환성 경고를 보존한 `PASS_WITH_WARNINGS` 결과입니다.
[실제 화면과 원문 결과](docs/validation/README.md)를 확인하세요. HA failover·백업 복구와
표준 최신 CSI 조합의 실증은 별도로 필요합니다.

## 공식 참고

- [Kubernetes 1.37.2](https://github.com/kubernetes/kubernetes/releases/tag/v1.37.2)
- [kubeadm v1beta4](https://kubernetes.io/docs/reference/config-api/kubeadm-config.v1beta4/)
- [CRI-O 패키지 저장소](https://github.com/cri-o/packaging)
- [containerd 2.x 설정](https://github.com/containerd/containerd/blob/main/docs/cri/config.md)
- [Calico 설치](https://docs.tigera.io/calico/latest/getting-started/kubernetes/quickstart)
- [Calico 시스템 요구사항](https://docs.tigera.io/calico/latest/getting-started/kubernetes/requirements)
- [kubeadm 업그레이드](https://kubernetes.io/docs/tasks/administer-cluster/kubeadm/kubeadm-upgrade/)

## License

GNU GPL v2. 저장소의 LICENSE를 참고하세요.
