# 간편 설정과 설치

새 단일 control-plane 랩은 하나의 진입점으로 의존성 준비, 인벤토리 생성,
계획 확인과 설치를 진행합니다. HA 구성은 기존 인벤토리를 사용하세요.

## 빠른 시작

Linux/WSL의 Python 3.12 이상(Ansible 지원 범위 3.12~3.14)이 필요합니다.

```bash
bash setup-k8s.sh deps
bash setup-k8s.sh configure --interactive
bash setup-k8s.sh plan -i inventory/local-lab/hosts.yaml
bash setup-k8s.sh install -i inventory/local-lab/hosts.yaml
```

`deps`는 프로젝트 `.venv`에만 Ansible을 설치합니다. OS의 Python이나 sudo 정책을
자동 변경하지 않습니다. 다른 Python 경로는 `DUSTSTACK_PYTHON`으로 지정합니다.
`configure`는 인벤토리만 생성하며 서버 접속·랩 생성·설치는 수행하지 않습니다.
SSH 사용자·키와 sudo 권한은 사전에 준비하세요.

새 호스트에는 OS 저장소의 chrony를 준비하고 기존 OS/관리자 NTP 설정으로 동기화를
확인합니다. 클러스터 생성 전에 남은 시간 보정량이 10 ms 미만인지 검사합니다.
기존 클러스터에서는 동기화 상태를 검사하며 NTP source를 덮어쓰거나 강제로 시간을
step하지 않습니다. NTP가 없거나 접속할 수 없다면 관리자 정책에 맞춰 먼저 준비하세요.

## 명령으로 재현 가능한 설정 생성

```bash
bash setup-k8s.sh configure \
  --control 'cp1=192.0.2.10@10.10.10.10/24' \
  --worker 'worker1=192.0.2.11@10.10.10.11/24' \
  --worker 'worker2=192.0.2.12@10.10.10.12/24' \
  --interface eth1 --ssh-user rocky --cni cilium \
  --storage nfs --nfs-server 192.0.2.50 --nfs-share /exports/kubernetes
```

주소는 실제 환경으로 바꿔야 합니다. `name=SSH주소@내부IP/prefix` 형식이며,
내부 IP와 NIC는 이미 서버에 설정돼 있어야 합니다. SSH 주소는 관리망이나 jump host에서
접근할 수 있어야 합니다. 생성기는 중복 노드·중복 IP·클러스터 CIDR 겹침, NFS 설정
누락, Rook worker/디스크 부족을 거부합니다. 기존 출력 파일을 덮어쓰지 않습니다.

신규 클러스터의 CIDR는 `--pod-cidr 172.22.0.0/16 --service-cidr 172.23.0.0/16`처럼
직접 지정할 수 있습니다. 생성기는 내부 노드의 IP뿐 아니라 입력한 prefix 전체와
겹치는 범위도 거부합니다. 예를 들어 `10.250.253.84/8`이면 기본 10번대 클러스터
CIDR를 사용할 수 없습니다. 다른 관리 NIC·VPN·라우팅 대역도 직접 확인하세요.
이 옵션은 신규 인벤토리 생성용이며 기존 클러스터 CIDR를 변경하는 절차가 아닙니다.

생성한 `inventory/local-lab/hosts.yaml`에는 기본 변수와 선택 결과를 모두 포함합니다.
부모 인벤토리의 group_vars 경로에 의존하지 않으므로 다른 경로에서도 같은 설정을
읽습니다. 출력 위치는 `--output inventory/local-다른랩/hosts.yaml`로 바꿀 수 있습니다.
`inventory/local*`는 Git에서 제외됩니다. 비밀번호·토큰·개인키는 파일에 쓰지 않습니다.

CNI는 `calico`, `flannel`, `cilium`, CSI는 `none`, `nfs`, `rook`을 선택합니다.
Cilium은 공식 지원 대상인 Kubernetes 1.36.6 조합을 자동 선택합니다. 기본 Calico는
1.37.2를 사용합니다. 기존 클러스터의 업·다운그레이드를 생성기로 자동 처리하지 않습니다.

## Rook 설정 생성

3개 이상의 worker와 `--rook-device worker이름=장치이름`을 각각 지정하세요.
기본 생성 결과는 `rook_confirm_devices: false`입니다. 인벤토리·하드웨어·백업 정책을
검토하고 Ceph 전용 빈 디스크가 맞을 때만 `--confirm-rook-devices`로 생성하거나 해당
변수를 명시적으로 true로 바꾸세요. 이 플래그는 디스크 사용 확인이며 데이터 복구 기능이 아닙니다.

## 작업별 진입점

| 명령 | 수행 작업 |
| --- | --- |
| setup-k8s.sh deps | .venv 및 고정 Ansible 컬렉션 준비 |
| setup-k8s.sh configure | 전체 변수를 포함하는 새 인벤토리 생성 |
| setup-k8s.sh check | 소스·문법·회귀 검사 |
| setup-k8s.sh plan | Ansible check/diff, 실제 초기화·join·Helm 적용 생략 |
| setup-k8s.sh install | 기본 클러스터, CNI와 명시적으로 선택한 CSI 설치 |
| setup-k8s.sh storage | 기존 클러스터에 선택한 CSI 설치 |
| setup-k8s.sh kam | 명시적으로 승인한 namespace KAM CRD/controller 설치 |
| setup-k8s.sh tools | CLI 도구만 설치 |

`-i`, `--private-key`, `--ask-pass`, `--ask-become-pass`, `-e @변수파일` 등 Ansible
옵션을 plan/install/storage/tools에 그대로 전달합니다. `--check`는 전체 신규 설치의
성공을 보장하지 않습니다. 실제 설치 뒤 노드·통신·스토리지를 확인해야 합니다.

## kubelet 서버 인증서

`serverTLSBootstrap: true`에 따라 요청하는 서버 인증서는 Kubernetes가 기본 자동
승인하지 않습니다. 설치 후처리는 인벤토리에 있는 노드의 Pending 요청만 검토합니다.
Node InternalIP, 요청자·그룹, CSR 서명·주체·서버 용도, 정확한 노드 IP와 DNS SAN을
검증하고 외부 IP·다른 노드 DNS·URI/email·CA 확장 요청은 거부합니다. 다른 signer,
이미 처리한 요청과 인벤토리 밖 노드의 요청은 승인하지 않습니다.

기존 설치나 인증서 갱신 때에는 같은 인벤토리로 별도 실행할 수 있습니다.

```bash
ansible-playbook -i inventory/local-lab/hosts.yaml playbooks/k8s-serving-certs.yaml
```

이 작업은 상시 승인 컨트롤러나 광범위한 승인 RBAC를 설치하지 않습니다.
갱신 요청도 같은 절차로 검토해야 하며, 인벤토리 밖 요청은 운영자가 별도로 확인합니다.
승인 누락 시 Node Ready여도 `kubectl logs/exec`에서 TLS 오류가 발생할 수 있습니다.
[Kubernetes 인증서 안내](https://kubernetes.io/docs/tasks/administer-cluster/kubeadm/kubeadm-certs/)


## 추가로 쉽게 만들 수 있는 부분

Terminal Lab의 랩 노드 선택 → CNI/CSI 선택 → 주소·디스크 검증 → plan 출력 →
명시적 설치 → 실습 검증을 하나의 UI로 연결하는 방식을 권장합니다. 현재 제공물은
이 저장소의 CLI와 플레이북이며 Terminal Lab 포털 자체를 수정하지 않습니다.
다중 control plane 생성기, 이미지·RPM 미러 준비, 인증정보 Vault 연계,
단계별 resume·진단 로그 묶음을 다음 확장으로 검토하세요.

[CNI·CSI 설정](CNI-CSI.md) · [터미널랩 검증](TERMINAL-LAB.md) · [기본 설치 안내](../README.md)
