# CNI·CSI 선택과 설치

기준일: 2026-11-01. 네트워크는 하나의 CNI를 선택합니다. 스토리지는 NFS CSI와
Rook/Ceph RBD를 기본 선택지로 제공하며 `k8s_csi_providers: []`로 시작합니다.
NFS 주소나 Ceph 디스크가 없는데 자동으로 설치하지 않습니다.

## 선택 기준

| 구성 | 제공 조합 | 용도와 조건 |
| --- | --- | --- |
| Calico | Kubernetes 1.37.2 / Calico 3.33.0 | 기본 CNI, 네트워크 정책, VXLAN |
| Flannel | Kubernetes 1.37.2 / Flannel 0.28.10 | 간단한 통신 실습, NetworkPolicy 강제 기능은 별도 필요 |
| Cilium | Kubernetes 1.36.6 / Cilium 1.20.4 | eBPF·정책·Hubble 관측, kube-proxy 유지 |
| NFS CSI | driver/chart 4.13.6 | 기존 NFSv4.1 export 필요, 공유 파일/RWX |
| Rook/Ceph | Rook 1.21.1 / Ceph 20.2.4 | 3개 이상 스토리지 worker, 복제 3, 전용 빈 디스크, RBD/RWO |

Cilium 1.20 공식 호환성 표는 Kubernetes 1.36까지 명시합니다. 따라서 Cilium 설정
프로필은 1.36.6과 CRI-O 1.36.7을 사용합니다. 기본 1.37 설정에서 Cilium을 바로
선택하면 중단합니다. `cilium_allow_untested_kubernetes: true`는 미검증 조합을
명시적으로 실험할 때만 사용하며 운영 지원 완료를 의미하지 않습니다.
`cilium_kube_proxy_replacement`는 현재 false로만 사용합니다.

## Cilium

기존 인벤토리를 쓴다면 프로필을 extra-vars로 함께 전달합니다.

```bash
bash setup-k8s.sh plan -i inventory/kubernetes.yaml -e @profiles/cilium.yaml
bash setup-k8s.sh install -i inventory/kubernetes.yaml -e @profiles/cilium.yaml
```

신규 랩 인벤토리는 [간편 설정 안내](SETUP.md)의 생성기를 사용하는 편이 쉽습니다.
`profiles/cilium.yaml`을 기존 1.37 클러스터의 다운그레이드에 사용하면 안 됩니다.
이미 설치된 kubelet·API 서버·런타임 버전, Pod/Service CIDR, API endpoint, 현재 CNI를
검사하고 불일치를 차단합니다. CNI 교체는 전용 마이그레이션이나 새 클러스터로 진행하세요.

Cilium은 kubeadm이 할당하는 노드 Pod CIDR을 쓰는 `ipam.mode: kubernetes`,
VXLAN 터널, 명시한 `k8s_interface`, IPv4로 구성합니다. Hubble agent 관측은 활성화하고
Relay·UI는 공개하지 않습니다. Hubble 외부 노출·인증·TLS는 별도 설계가 필요합니다.
노드 간 UDP 8472, API/kubelet 통신과 환경별 Cilium health 통신을 허용해야 합니다.
커널 버전만으로 eBPF 지원을 보장하지 않으므로 BPF/BTF·cgroup·터널 관련 커널 옵션도 확인하세요.

## NFS CSI

드라이버는 NFS 서버를 생성하지 않습니다. 먼저 노드에서 접근할 수 있는 export를
준비하고 읽기·쓰기 권한, root squash, UID/GID, 백업·서버 HA를 검토하세요.

```yaml
k8s_csi_providers: [nfs]
nfs_server: 192.0.2.50       # 실제 주소로 변경
nfs_share: /exports/kubernetes
k8s_default_storage_class: nfs-csi
```

```bash
bash setup-k8s.sh storage -i inventory/kubernetes.yaml -e @inventory/local-nfs.yaml
```

모든 Kubernetes 노드에 `nfs-utils`를 준비하고 driver를 설치한 뒤 `nfs-csi`를 생성합니다.
기본 mount 옵션은 `nfsvers=4.1`, `hard`입니다. 서버의 버전과 네트워크 정책에 맞춰
`nfs_mount_options`를 조정하세요. TCP 2049 접근이 필요합니다.
PVC별 하위 경로는 namespace·PVC·PV 이름을 포함해 충돌을 줄입니다.
`reclaimPolicy: Retain`, `onDelete: retain`으로 기본 데이터를 보존합니다.
PVC 용량 요청이나 확장 표시가 NFS 서버의 실제 디스크 quota 강제를 의미하지는 않습니다.
Snapshot controller/CRD는 자동으로 추가하지 않습니다.

## Rook/Ceph RBD

각 스토리지 worker는 최소 4 vCPU, 8 GiB RAM과 20 GiB 이상의 전용 빈 디스크가
필요합니다. 실습에는 50 GiB 이상을 권장합니다. 실제 부하에 맞춰 OSD 메모리·CPU·용량,
복제 3의 사용 가능 용량, 노드 간 지연, 장애 도메인을 별도로 산정하세요.

인벤토리의 기존 worker를 `k8s_storage_ceph`에도 등록합니다.

```yaml
k8s_storage_ceph:
  hosts:
    storage1:
      rook_devices: [sdb]
    storage2:
      rook_devices: [sdb]
    storage3:
      rook_devices: [sdb]
```

각 호스트에는 기존 `k8s_node` 멤버십과 고유 `nodename`이 있어야 합니다.
설정 파일은 다음과 같습니다.

```yaml
k8s_csi_providers: [rook]
rook_confirm_devices: true
k8s_default_storage_class: rook-ceph-block
```

`rook_confirm_devices`는 지정 디스크를 Ceph가 사용한다는 명시적 확인입니다.
플레이북은 디스크 basename만 허용하고 블록 장치 여부, 파티션·파일시스템·마운트·서명,
최소 크기를 읽기 전용으로 검사합니다. 검사는 포맷 명령이나 `wipefs` 삭제를 실행하지
않습니다. 검사 후 실제 Ceph 구성은 지정한 빈 디스크를 사용합니다.

`useAllNodes: false`, `useAllDevices: false`이며 선택한 장치만 CephCluster에 넣습니다.
3 MON, 2 MGR, host 단위 3복제 풀, RBD StorageClass를 구성합니다. 파괴적 cleanup
confirmation은 비워 두며 CephCluster나 PV를 자동 삭제하지 않습니다.
기존 CephCluster의 디스크·Ceph 이미지·data directory가 다르면 재구성을 차단합니다.
이미 사용 중인 정상 Ceph 디스크에는 신규 빈 디스크 검사를 다시 적용하지 않습니다.

SELinux Enforcing 환경에서는 Ceph hostPath의 데이터 라벨도 준비합니다. 관리 경로는
`/var/lib/rook` 또는 `/var/lib/rook-NAME` 형태의 전용 디렉터리로 제한하며 symlink와
상위 디렉터리·경로 이탈을 거부합니다. 해당 경로에만 영구 `container_file_t:s0` 규칙을
등록하고 다른 파일시스템을 넘지 않도록 `restorecon -x`로 적용합니다. 기존에 다른
경로를 쓰는 클러스터는 자동 이동하지 않으며 별도 검토가 필요합니다.
MON을 추가 privileged 모드로 올리지 않고 `hostpathRequiresPrivileged: false`를
유지합니다. OSD에는 원래 필요한 장치 접근 권한이 별도로 사용됩니다.
장치 hotplug에 따른 자동 orchestration도 끄고 명시한 디스크만 사용합니다.

MON의 `chown-container-data-dir` 초기화가 AVC로 실패한 기존 설치에서는 다음 명령으로
같은 경로 라벨 준비만 다시 실행할 수 있습니다. 디스크 포맷·데이터 정리는 수행하지 않습니다.

```bash
ansible-playbook -i inventory/local-live/hosts.yaml playbooks/k8s-storage-hosts.yaml
```

[컨테이너 SELinux 파일 유형](https://github.com/containers/container-selinux/blob/main/container_selinux.8)

`rook-ceph-block`은 `Retain`, `WaitForFirstConsumer`를 사용합니다. PVC만 생성하면
소비 Pod가 생길 때까지 Pending일 수 있으므로 PVC와 테스트 Pod를 함께 생성하세요.
Rook operator 차트에 포함된 Ceph CSI operator도 설치합니다. CephFS/RWX, RGW,
외부 Ceph, snapshot, 암호화·KMS는 후속 확장 항목입니다.

Rook 1.21은 CSI operator 외에 관리자가 만드는 `OperatorConfig`와 RBD `Driver`도
필요합니다. 설치 역할은 두 리소스를 명시적으로 생성하고, driver 이름이 StorageClass
provisioner와 같도록 유지합니다. 실제 CRD의 server dry-run, controller·node plugin
rollout, 모든 worker의 CSINode 등록을 확인한 뒤 StorageClass를 제공합니다.
SELinux 설정은 node plugin에 읽기 전용으로 연결하고 snapshot 기능은 켜지 않습니다.
operator·CephCluster Ready만으로 RBD CSI 준비가 완료됐다고 판정하지 않습니다.
[공식 Rook 1.21.1 구성](https://github.com/rook/rook/blob/v1.21.1/deploy/examples/operator.yaml)

RBD controller·node plugin 계정과 권한도 설치 역할이 먼저 준비합니다. 번들 CSI
operator v1.1.0의 공식 RBAC에서 RBD 리소스만 사용하며, Driver에 계정 이름을 명시합니다.
클러스터 범위 Role/Binding에는 Rook namespace를 붙여 다른 설치와 충돌을 방지합니다.
이 드라이버에는 Secret·PV/PVC·VolumeAttachment 등 업스트림 클러스터 권한이 필요합니다.
[RBAC 원본](https://github.com/ceph/ceph-csi-operator/blob/v1.1.0/deploy/multifile/csi-rbac.yaml)

### CephX와 구형 커널 호환성

Ceph 20.2.4의 새 AES256K 키는 커널 RBD/CephFS 클라이언트에서 Linux 7.0+ 또는
해당 기능을 backport한 커널이 필요합니다. 버전 숫자만으로 RHEL 계열의 backport를
추정하지 마세요. Rook은 새 클러스터의 핵심 daemon·서비스 티켓을 AES256K로
설정하면서 구형 클라이언트용 AES 호환성을 남길 수 있습니다. 따라서 `Ready`와
`HEALTH_OK`는 서로 다른 조건이며 키 호환성 경고가 남을 수 있습니다.
기존 CSI 키를 임의로 회전하거나 허용 cipher를 일괄 제한하면 mount가 끊길 수 있습니다.
[공식 키·커널 호환성 안내](https://rook.io/docs/rook/latest-release/Storage-Configuration/Advanced/cephx-key-rotation/)

실증 실행기는 기본적으로 `HEALTH_OK`를 요구합니다. 위 호환성을 확인한 전용 랩에서는
`--allow-ceph-legacy-client-key-warnings`를 명시할 수 있습니다. 이때에도 MGR/OSD의
AES256K 키 메타데이터와 MON의 AES256K 서비스 티켓을 검증하며, 시계 차이·OSD·PG·
서비스 키 오류나 알 수 없는 경고는 통과시키지 않습니다. 허용한 경고는 JSON에 그대로
기록하고 전체 성공 표시도 `PASS_WITH_WARNINGS`/`passed_with_warnings`로 구분합니다.
Ceph의 경고 자체를 mute하지 않습니다.

## 기본 StorageClass와 데이터 정책

NFS와 Rook을 함께 선택할 수 있지만 `k8s_default_storage_class`에는 하나만 지정합니다.
기존 다른 기본 클래스가 있으면 자동 해제·교체하지 않고 중단합니다. 기본 클래스를
바꿔도 이미 Bound인 PVC나 그 데이터가 자동 이동하지 않습니다.

Retain은 데이터 보존에 유리하지만 삭제한 PVC의 PV·NFS 디렉터리·Ceph 이미지가
남을 수 있습니다. 소유자 확인·백업·보관 기간과 수동 정리 절차가 필요합니다.
설정에서 provider를 빼거나 Kubernetes reset을 해도 CSI 데이터 전체가 정리되지 않습니다.
드라이버·클러스터 uninstall과 데이터 삭제는 별도 작업으로 설계하세요.

## 차트 공급과 업그레이드

`inventory/group_vars/kubernetes/addons`에 공식 차트 URL·버전·SHA-256을 고정합니다.
`common/helm-release`는 [CLI 공급 역할](TOOLS.md)로 Helm을 준비하고 차트를 검증해 설치합니다.
기본은 다운로드이며 수동 공급도 지원합니다.

| 설정 | 공급 위치 |
| --- | --- |
| addon_chart_source: download | 대상 서버가 공식 HTTPS URL에서 다운로드 |
| addon_chart_source: controller | 컨트롤러 artifacts/charts/차트ID/공식파일명 |
| addon_chart_source: target | 대상 /var/cache/duststack/incoming/charts/차트ID/공식파일명 |

차트 ID는 `cilium`, `nfs`, `rook`입니다. 예를 들어 NFS 컨트롤러 파일은
`artifacts/charts/nfs/csi-driver-nfs-4.13.6.tgz`입니다. Helm 실행 파일의 수동 공급도
필요하면 `cli_tool_source`를 함께 설정하세요. 컨테이너 이미지까지 오프라인으로
공급하는 기능은 별도이며 인터넷 차단 환경에서는 레지스트리 미러가 필요합니다.

이미 설치된 Helm release의 차트 버전이 다르면 자동 업그레이드하지 않습니다.
`addon_allow_chart_upgrade: true`는 공식 절차·백업·검증 후 사용하세요. Helm rollback이
Ceph 데이터나 CRD 변경을 모두 복구한다고 가정해서는 안 됩니다.

## 검증과 공식 출처

```bash
RUN_CHART_VALIDATION=1 bash scripts/validate.sh
```

실제 공식 차트의 SHA-256, Helm lint, values/schema와 렌더링 결과를 검사합니다.
이 검증은 API 서버·스토리지에 접속하지 않으므로 실제 CNI 통신·PVC I/O 성공과 다릅니다.
터미널랩 검증은 [TERMINAL-LAB.md](TERMINAL-LAB.md)를 참고하세요.

- [Cilium 호환성](https://docs.cilium.io/en/stable/network/kubernetes/compatibility/)
- [Cilium Helm 설치](https://docs.cilium.io/en/stable/installation/k8s-install-helm/)
- [Rook 요구사항](https://rook.io/docs/rook/latest-release/Getting-Started/Prerequisites/prerequisites/)
- [Rook 1.21.1](https://github.com/rook/rook/releases/tag/v1.21.1)
- [NFS CSI 4.13.6](https://github.com/kubernetes-csi/csi-driver-nfs/releases/tag/v4.13.6)
- [StorageClass](https://kubernetes.io/docs/concepts/storage/storage-classes/)
