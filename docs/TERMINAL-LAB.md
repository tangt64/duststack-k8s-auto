# 터미널랩 검증 절차

터미널랩의 본인 전용 랩과 웹 터미널에서 검증합니다. 기존 교육용 랩이나 운영
클러스터의 CNI를 시험 목적으로 교체하지 않습니다. 랩 생성·연장·VM 사양 변경에
발생하는 자원과 비용은 터미널랩 정책을 먼저 확인하세요.

## 단계 1: 설치 없이 소스·공급 경로 검증

검증용 노드에 Python 3.12, git, openssl, tar, gzip이 필요합니다.
사용자 작업 폴더에서 저장소를 받고 의존성을 준비합니다.

```bash
git clone https://github.com/tangt64/duststack-k8s-auto.git duststack-k8s-check
cd duststack-k8s-check
bash setup-k8s.sh deps
bash scripts/terminal-lab-check.sh
```

이 단계는 Kubernetes, CNI, CSI나 CephCluster를 설치하지 않습니다. 소스·Markdown 링크,
Ansible 문법·회귀 테스트, 로컬 HTTPS 다운로드/수동 배치, 공식 Helm chart lint/render를
실행합니다. 결과와 커밋은 `.tools/terminal-lab-validation.json`에 기록합니다.
검증용 파일·아카이브와 가상환경은 Git에 넣지 않습니다.

## 단계 2: 전용 신규 클러스터의 실제 Cilium/NFS 검증

최소 control plane 1대와 worker 2대, 실제 NIC·주소·SSH/sudo와 기존 NFS export를
준비합니다. [간편 설정](SETUP.md)으로 Cilium/NFS 인벤토리를 생성하고 plan·install을
진행합니다. 기존 클러스터가 있다면 별도 신규 랩을 사용하세요.

완료 조건:

1. 인벤토리의 모든 노드가 Ready이고 Cilium DaemonSet이 모두 Ready입니다.
2. 서로 다른 노드의 Pod 간 통신, ClusterIP, CoreDNS 조회를 확인합니다.
3. 기본 deny 정책과 필요한 허용 정책으로 Cilium NetworkPolicy를 검증합니다.
4. NFS CSI driver/DaemonSet을 확인하고 PVC와 소비 Pod를 함께 생성합니다.
5. Pod에서 기록한 파일을 다른 Pod에서도 읽고, 재시작 후 같은 데이터를 확인합니다.
6. PVC 삭제/Retain 동작, PV 소유자와 잔여 NFS 경로를 기록합니다.

단순 chart 렌더링이나 StorageClass 존재만으로 PVC mount/I/O 통과를 기록하지 않습니다.
실습용 namespace·Pod·PVC는 고유 이름과 소유자 표시를 사용하세요. 기존 namespace나
PV를 정리 대상으로 사용하지 말고, Retain PV의 데이터 삭제도 별도로 확인해야 합니다.

## 단계 3: Rook/Ceph 검증

전용 스토리지 worker 3대 이상에 각각 4 vCPU, 8 GiB RAM, 빈 추가 디스크를 준비합니다.
OS 디스크·부트 볼륨·기존 NFS/학습 데이터 디스크를 선택하면 안 됩니다. Rook 예제의
명시적 디스크 목록과 사용 확인을 검토한 뒤 설치하세요.

완료 조건은 MON 3대 quorum, CephCluster Ready·Ceph health, OSD 수와 실제 장치,
3복제 풀, PVC Bound와 Pod 파일 쓰기/재접속/읽기, worker 장애 시 복구 상태입니다.
`WaitForFirstConsumer`이므로 소비 Pod 없는 PVC Pending은 곧바로 실패가 아닙니다.
시험 종료 후 CephCluster 삭제·디스크 wipe를 자동으로 실행하지 않습니다.

## 권장 테스트 매트릭스

| 랩 | 구성 | 주요 확인 |
| --- | --- | --- |
| 기본 | Calico + Kubernetes 1.37.2 | 신규 설치, 같은 설정 재실행, 재부팅 |
| 네트워크 | Cilium + Kubernetes 1.36.6 | eBPF/VXLAN, DNS, 서비스·정책, Ready |
| 파일 | Cilium + NFS CSI | RWX, 다른 노드 간 파일 공유, Retain |
| 블록 | Calico 또는 Cilium + Rook | 빈 디스크 가드, 3복제, RBD I/O, 장애 복구 |
| 거부 | 기존 CNI 변경·다른 기본 SC·사용 디스크 | 적용 전에 중단하고 기존 상태 보존 |

실제 수행 결과와 한계는 [검토 문서](REVIEW.md)에 구분해 기록합니다.


## 수행 기록

2026-11-01 웹 콘솔에서 `06d1233`의 단계 1을 수행했습니다. Ansible 문법·소스 정책,
회귀 24개(추가 kubeadm 스키마 검사 1개는 바이너리 부재로 생략), CLI 통합 검증과
Cilium/NFS/Rook 공식 차트 검증이 통과했고 종료 코드는 0입니다.
약 4 GiB의 기존 교육용 노드를 사용했으며 단계 2·3의 실제 배포와 PVC I/O는 수행하지
않았습니다. 환경·CI 링크·제약은 [검토 기록](REVIEW.md)에 있습니다.
