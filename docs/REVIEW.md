# 최신화 및 개선 검토

검토 기준일: 2026-11-01. 범위는 설치 플레이북에서 실행되는 코드와 저장소의
레거시 확장·외부 실행 파일 공급에 대한 정적 검토입니다. 운영 환경 침투 테스트나 전체 보안 감사 결과는 아닙니다.

## 반영한 수정

| 문제 | 변경 |
| --- | --- |
| Kubernetes 1.28, kubeadm v1beta3, 폐기된 감사 정책 API | 1.37.2 / v1beta4 / audit.k8s.io/v1 적용 |
| group_vars/all이 경로 문자열이고 kubernetes 부모 그룹 부재 | 유효한 YAML과 부모 그룹 상속으로 수정 |
| 기본 비밀번호·고정 bootstrap 토큰·인증서 키 | 기본 비밀번호 제거, 실행 시 join 정보 생성·no_log·0600·항상 정리 |
| CRI-O가 매 실행마다 삭제되고 Kubernetes 패키지도 삭제 후 재설치 | 지정 버전 설치, 기존 클러스터/런타임 버전 변경 차단 |
| containerd에서 command에 리다이렉션을 전달하고 실제 master는 CRI-O로 고정 | containerd 2.x config v3, systemd cgroup, 명시적 CRI socket |
| 초기화 실패가 자동 reset으로 이어짐 | 자동 reset 제거, 재실행 시 기존 노드 확인, 별도 reset에 명시적 플래그 요구 |
| API endpoint가 노드별 주소/VIP로 불일치 | 단일/HA 공통 endpoint, 내부 주소로 HAProxy 백엔드 구성 |
| keepalived priority에 상태 문자열 사용, 서비스 상태 미확인 | 숫자 priority, 인증서를 검증하는 API 상태 검사 |
| manifests 디렉터리가 0644여서 탐색 불가 | 디렉터리 0755, 비밀 파일 0600 |
| firewall 전체 중단, 노드 대역 전체 허용, 자동 NOPASSWD sudo 설치 | 자동 정책 변경 제거, Calico 충돌은 사전 차단 |
| 노드 전체에 worker 라벨, 실패 무시 | 실제 worker만 라벨, 노드별 Ready 대기, 실패 전파 |
| NetworkManager가 Calico 인터페이스를 관리할 가능성 | Calico 가상 인터페이스만 unmanaged로 지정하고 설정 reload |
| 오래된 Calico operator와 CRD 준비 경쟁 | 3.33.0 SHA-256 검증, CRD 먼저 적용·Established 대기 |
| Flannel CIDR·NIC·이미지와 인벤토리 불일치 | 0.28.10 공식 매니페스트 기반 템플릿 |
| 래퍼가 인자를 버리고 호출 디렉터리에 의존 | 엄격 모드, 경로 고정, 옵션 전달, LF 개행 |
| 최신 Ansible의 사실 변수·조건식 변경 | facts 명시 접근, 실제 bool 조건, 2.21.5 검사와 회귀 테스트·CI 추가 |

## 실행 파일 공급 정비

소스에 포함되었던 `clusteradm` 2개와 `virtctl` 1개를 제거했습니다. 손상된 바이너리를
되살리지 않고 버전·아키텍처·SHA-256이 고정된 공통 설치 역할로 교체했습니다.
자동 HTTPS 다운로드, 컨트롤러 수동 배치, 대상 서버 수동 배치를 같은 검증 절차로
처리합니다. 누락·빈 파일·체크섬 오류는 기존 실행 파일 교체 전에 거부합니다.

OCM의 공유 `/tmp` join 파일 조회·실행과 중복 init 구현을 제거했습니다. OCM·KubeVirt
기존 역할은 CLI만 공급하고 서버 리소스 배포는 차단합니다. Helm 역할도 원격 설치
셸 스크립트와 Tiller RBAC 대신 같은 역할로 CLI만 설치합니다. 사용하지 않는 Helm
다운로더를 제거하고 KubeVirt CLI 역할의 런타임 설치 의존성도 제거했습니다. 구체적 경로·절차는
[TOOLS.md](TOOLS.md)에 있습니다. CLI 기본 버전은 clusteradm 1.4.0, virtctl 1.9.1,
Helm 4.3.1이며, 서버 리소스 지원 버전과는 별도로 검증해야 합니다.

소스 트리의 바이너리와 마크다운 로컬 링크 오류를 검사하는 스크립트와 CI 검사를
추가했습니다. 로컬 CLI 통합 검증은 HTTPS·수동 배치·재실행·잘못된 파일 거부를
임시 디렉터리에서 실행하며 운영 클러스터를 사용하지 않습니다. WSL 공유 드라이브의
권한·rename 제약은 `CLI_TEST_TEMP_DIR=/tmp`로 Linux 파일시스템에서 검증합니다.

## CNI·CSI와 설치 편의 개선

Cilium 1.20.4를 추가했습니다. 공식 Kubernetes 호환성에 맞춘 1.36.6/CRI-O 1.36.7
프로필을 제공하고 미검증 1.37 조합은 기본 거부합니다. 기존 CNI, Pod/Service CIDR,
API endpoint 변경을 호스트 준비 전에 차단합니다. 기본 Calico/1.37.2는 유지합니다.

NFS CSI 4.13.6과 Rook 1.21.1/Ceph 20.2.4 RBD를 선택 설치합니다. 다른 기본
StorageClass와 충돌하면 중단하고 Retain 정책을 사용합니다. Rook은 전용 worker
3대·복제 3·명시한 빈 장치만 허용하며 4 vCPU/8 GiB, 파티션·서명·마운트와 용량을
검사합니다. 기존 Ceph 이미지·디스크·data directory 변경도 자동 적용하지 않습니다.

Helm 차트도 공식 버전·SHA-256 고정과 다운로드/컨트롤러/대상 수동 공급을 지원합니다.
차트 아카이브는 저장소에 넣지 않습니다. 실제 고정 차트의 lint·schema·렌더링 검증을
CI에 연결했습니다. Cilium 25개, NFS 9개, Rook 88개 리소스 렌더링을 확인했습니다.

`setup-k8s.sh`로 의존성 준비·설정 생성·계획·설치·CSI·도구 진입점을 통합했습니다.
생성기는 CNI별 버전 조합, 노드/IP/CIDR 및 스토리지 입력을 검사하며 기존 파일을
덮어쓰지 않습니다. 자세한 설정은 [SETUP.md](SETUP.md), 선택 기준은
[CNI-CSI.md](CNI-CSI.md), 웹 터미널 검증은 [TERMINAL-LAB.md](TERMINAL-LAB.md)에 있습니다.

## 우선 보강할 항목

### 높음: 운영 업그레이드·복구와 통합 검증

현재 변경은 신규 설치 경로를 최신화합니다. Kubernetes 1.28에서 1.37로 직접 이동하는
업그레이드 자동화는 제공하지 않습니다. etcd 스냅샷과 복원 리허설, control plane부터
하나씩 minor 업그레이드, drain/uncordon, PDB, 런타임·CNI 호환성 검증이 필요합니다.
별도 Rocky 9/10 VM에서 단일/3-control-plane × CRI-O/containerd × Calico/Flannel
설치, 같은 버전 재실행, 재부팅, DNS/Pod 통신, API VIP/LB failover를 검증하세요.
현재 로컬 회귀 테스트 통과가 이 통합 검증을 대신하지는 않습니다.
또한 기존 클러스터의 CNI 버전·Pod/Service CIDR·API endpoint 변경까지 자동으로
마이그레이션하지 않습니다. 현재 kubeadm 설정과 알려진 CNI DaemonSet을 읽어
CIDR·endpoint·CNI 종류 불일치를 차단하지만 CNI 자체 버전·이미지 및 전체 네트워크
설정 변경을 통제하는 별도 운영 절차는 계속 필요합니다.

### 높음: API 로드밸런서의 단일 장애점

현재 HAProxy 샘플은 LB 한 대입니다. control plane이 3대여도 LB 장애로 API 접속이
끊길 수 있습니다. 이중 LB와 VIP 또는 외부 HA 로드밸런서를 구성하고 장애 전환,
API 장시간 연결, DNS 변경을 검증해야 합니다. 현재 코드에 LB 이중화가 자동 포함된
것으로 간주해서는 안 됩니다.

### 높음: 레거시 자격 증명과 관리자 권한

`roles/virtualizations/ovirt-builder/tasks/main.yaml`의 평문 초기 비밀번호,
`roles/virtualizations/virt-k8s/files/*.ks`와 `roles/baremetal/virt-vms/files/*.ks`의
기존 계정 설정, 배포용 공개 키를 실환경에서 재사용하지 마세요. Vault와 일회용 초기
계정을 사용하고 기존에 배포된 자격 증명은 교체하세요.
`roles/extension/dashboard/files/dashboard-rbac.yaml`과 Helm의 `rbac-config.yaml`은
cluster-admin 권한을 포함합니다. 서비스 계정별 최소 권한과 짧은 수명의 토큰으로
재설계하기 전에는 수동 적용하지 마세요. 이 파일들은 현재 설치 경로에서 제외됩니다.

### 높음: 레거시 TLS·Metrics Server

`roles/kubernetes/k8s-tls/tasks/kubeconfig.yaml`은 TLS 서버 검증을 끄고,
`roles/extension/autoscale/templates/install-metric-server.yaml`과
`roles/kubernetes/k8s-post-config/files/metrics.yaml`은 kubelet 인증서 검증을 생략합니다.
레거시 수동 인증서 역할 대신 kubeadm PKI를 사용하고, kubelet serving CSR의 SAN과
노드 신원을 검증한 뒤 승인하는 절차를 마련하세요. Metrics Server의 최신 버전과
RBAC를 확인하고 신뢰 CA 기반 연결로 재구성해야 합니다. 현재 설치에는 포함되지 않습니다.

### 높음: 워크로드·호스트 네트워크 정책

기본 설치만으로 워크로드 격리가 완성되지는 않습니다. namespace별 default-deny와
DNS·필수 서비스 허용 정책, API/etcd 관리 대역 제한을 적용하세요. Calico의
HostEndpoint/GlobalNetworkPolicy는 SSH 잠금 사고를 막도록 테스트 후 적용해야 합니다.
Flannel 단독으로는 Kubernetes NetworkPolicy를 강제하지 않으므로 해당 요구가 있으면
Calico 등 정책 엔진을 사용하세요. 호스트 방화벽 정책은 자동 생성하지 않습니다.

### 중간: 애드온 및 VM 프로비저닝 재구축

남아 있는 KubeVirt 0.54 계열 매니페스트와 Helm v2/Tiller 참고 자료,
구형 Dashboard/Ingress API와 과거 Rook/Ceph 매니페스트는 각각 버전·지원 매트릭스를
확인해야 합니다. 신규 CSI는 `roles/storage/`만 사용하며 과거 Ceph 역할은 자동 연결하지
않습니다. 다른 레거시 애드온도 별도 역할로 교체하고 최신 버전 번호만 치환해서 적용하지 마세요.
`inventory/group_vars/classroom/kubernetes`와 kickstart는 CentOS 7 기반이므로
지원 중인 OS 이미지, HTTPS 저장소, cloud-init 등으로 바꾸고 VM 파괴 없이 검증하세요.
프로비저닝·snapshot 스크립트는 최신 설치 경로와 별개인 레거시입니다.

### 중간: 감사·비밀·공급망·운영 관측

감사 로그는 현재 노드 로컬 Metadata 수준입니다. 중앙 전송, 보존 기간, 용량 경보를
설계하세요. etcd Secrets 저장 암호화와 외부 KMS, 백업 암호화, 키 교체 절차도
추가해야 합니다. Kubernetes 패키지와 런타임은 버전을 고정하고 저장소 GPG 검증을
사용합니다. Calico 매니페스트와 CLI 릴리스 파일은 SHA-256을 고정합니다. 컨테이너 이미지 digest,
공식 서명/출처 검증, 사내 미러 정책까지 추가하면 재현성과 공급망 통제가 강화됩니다.
인벤토리의 Calico 버전과 체크섬, CLI catalog의 버전·파일명·URL·체크섬은 함께
갱신해야 합니다. 해시는 내용 일치를 확인하며 게시자 신원 검증까지 제공하지는
않습니다. 공식 서명·출처 검증과 검토된 사내 미러 승격 절차를 추가하세요.
CLI 캐시 보존 기간·용량 제한과 이전 버전 롤백 절차도 운영 정책으로 마련해야 합니다.
CI 액션도 추가로 commit SHA에 고정하고 Dependabot/Renovate와 릴리스별
테스트 클러스터 검증을 연결하세요. API/etcd/노드 상태, 인증서 만료, 시간 동기화,
백업 성공에 대한 관측과 경보가 필요합니다.

## 검증 근거와 한계

Ansible 2.21.5에서 설치/reset/도구 설치/KubeVirt 가드, 동적 join과 CLI 역할의
문법을 검사합니다. 소스 바이너리 재유입과 마크다운 링크도 검사합니다.
로컬 회귀 테스트 25개가 통과했습니다(실제 kubeadm 스키마 검증 포함).
회귀 테스트는 실제 Ansible 템플릿 엔진으로 초기화·join 설정을 렌더링하고
단일/HA·런타임·감사 옵션, CNI CIDR/NIC, 버전 보호 조건을 확인합니다.
실제 kubeadm 1.37.2 바이너리가 있으면 config validate도 실행합니다.
CLI 통합 테스트는 로컬 HTTPS 다운로드, 컨트롤러·대상 수동 배치, tar/raw 설치,
최종 파일 재실행 시 불필요한 변경 방지, 누락·빈 파일·변조 입력 거부를 확인합니다.
실제 원격 설치·서비스 재시작·네트워크 전환·기존 클러스터 업그레이드는 수행하지 않았습니다.


### 남은 CSI·편의 기능 과제

NFS 서버 HA·quota·백업, CephFS/RWX·snapshot·암호화/KMS, Ceph 업그레이드 및 장애
복구 리허설을 다음 우선순위로 권장합니다. Retain PV의 소유자·잔여 데이터 수명주기와
용량/health 경보도 운영 절차가 필요합니다. Terminal Lab의 노드 선택·사양/디스크 확인과
인벤토리 생성기를 연결하면 주소와 장치 입력 실수를 줄일 수 있습니다. 현재 포털 자체를
변경한 것은 아니며 다중 control-plane 생성기와 단계별 진단·resume는 후속 과제입니다.


### 2026-11-01 실제 검증 결과

검증 대상: `06d1233f1d56667db5a6f3880b92c4f599ab07c0`
(Cilium과 NFS·Rook CSI 선택 설치 및 간편 설정 추가).

| 환경 | 결과 |
| --- | --- |
| 로컬 Rocky 9 WSL / Ansible 2.21.5 | 소스·링크·Ansible 문법, 회귀 25개 전부 통과. 실제 kubeadm 1.37.2 스키마 포함 |
| 로컬 CLI·차트 | HTTPS/수동 배치·재실행·오류 거부 통합 검증 통과. 공식 Cilium 25/NFS 9/Rook 88개 리소스 lint·렌더링 통과 |
| GitHub Actions | [해당 커밋 실행](https://github.com/tangt64/duststack-k8s-auto/actions/runs/41213609443) success. 회귀 24개 통과·kubeadm 스키마 1개 생략, CLI 통합·3개 차트 통과 |
| Terminal Lab 웹 콘솔 | RHEL 9 계열, 커널 5.14.0-611.11.1.el9_7, Python 3.12.14, 약 4 GiB. 회귀 24개 통과·스키마 1개 생략, CLI 통합·3개 차트 통과. `TERMINAL_LAB_VALIDATION=PASS`, 종료 코드 0 |

터미널랩에서는 검증 전용 홈 디렉터리와 Python 가상환경을 사용했습니다. Python 3.12와
pip은 공식 OS 저장소로 준비했습니다. kubeadm 바이너리가 없는 랩·CI에서는 해당 스키마
검사만 생략했고 로컬에서 별도 통과했습니다. 랩의 결과 파일은
`.tools/terminal-lab-validation.json`, 실행 로그는 `.tools/terminal-lab-check.log`입니다.

이번 터미널랩 검증은 신규 Kubernetes/Cilium/CSI 설치나 PVC mount·입출력을 수행하지
않았습니다. 현재 교육용 랩을 교체하지 않았으며 약 4 GiB 노드는 Rook의 최소 8 GiB
조건에도 미달합니다. 실제 배포의 완료 조건은 [터미널랩 단계 2·3](TERMINAL-LAB.md)에
명시했습니다. CNI 정책·Pod 통신·Ceph health·장애 복구·스토리지 I/O는 전용 신규 랩에서
추가 검증해야 합니다.


### 전용 랩 실증 준비

`playbooks/terminal-lab-nfs.yaml`로 새 실습용 NFS backend를 준비하고,
`scripts/test_live_cluster.py`로 Cilium의 서로 다른 노드 간 통신·서비스/DNS·정책과
NFS/RBD PVC의 실제 체크섬·교차 노드 쓰기·재연결을 검증할 수 있게 했습니다.
기존 namespace 재사용을 거부하고 테스트 데이터는 자동 삭제하지 않습니다.
API/exec 실패를 정책 차단 성공으로 간주하지 않으며 RBD WFFC PVC는 스케줄러를
거치도록 구성합니다. 준비 코드의 로컬 검증과 실제 클러스터의 실행 결과는 별개입니다.
실제 수행 결과가 나오기 전에는 CNI 통신이나 PVC I/O 통과로 기록하지 않습니다.


### 실증 실행기 추가 검토

일부 CSI만 선택한 실행이 전체 `LIVE_CLUSTER_VALIDATION=PASS`로 출력되는 문제를
수정했습니다. 전체/부분 범위, 요청한 provider와 완료한 provider를 JSON에 기록하고
부분 실행은 `PARTIAL_PASS`/`partial_passed`로 구분합니다. Pod 준비·볼륨 재연결은
메타데이터 조회용 30초 요청 타임아웃에 묶이지 않도록 대기별 타임아웃을 적용했습니다.
추가 회귀를 포함한 로컬 테스트 31개와 Ansible 문법 검사가 통과했습니다.

전용 VM 생성과 control plane SSH/sudo 확인은 Kubernetes 설치 검증과 구분합니다.
남은 필수 작업은 네 노드의 전용 NIC/IP/MTU 확인, worker별 전용 빈 디스크 연결과
읽기 전용 검사, 비중복 Pod/Service CIDR를 반영한 신규 설치, 실제 Cilium·NFS·Rook
테스트 실행, 재실행·재부팅 및 데이터 보존 확인입니다. 특히 관리망의 큰 prefix가
기본 클러스터 CIDR을 포함하는 환경에서는 호스트 주소만 비교하지 말고 실제 NIC의
연결 대역과 VPN·기존 클러스터 범위도 함께 검토해야 합니다.

실습 자원의 이름·ID·접속 정보와 예산 관측은 비공개 로컬 기록에 남깁니다. 검사 중
중단돼도 VM·미연결 볼륨은 과금될 수 있습니다. 테스트 종료 시 Retain 데이터의 소유자와
보존 필요성을 확인하고 이 랩에서 만든 VM·디스크·네트워크만 정리하는 절차가 필요합니다.

### 실제 준비 화면과 사용 안내

사용자 요청으로 [단계별 사용 안내](TERMINAL-LAB-WALKTHROUGH.md)에 실제 VM 목록과
control plane 준비 검사 화면을 추가했습니다. 계정 잔액과 인증정보는 촬영 영역에서
제외합니다. 문서용 지정 JPEG만 크기·프레임 제한으로 허용하며 실행 바이너리와 차트
아카이브는 계속 외부 공급합니다. 이 예외에 대한 회귀를 포함해 로컬 테스트 32개가
통과했습니다. 실제 통과하지 않은 Cilium·CSI 단계는 예상 출력 예시로만 표시합니다.

새 8 GiB 전용 control plane에서 `b558839`의 소스 검증을 다시 수행했습니다.
회귀 31개 통과·kubeadm 스키마 1개 생략, CLI 공급 통합 검사와 Cilium 25/NFS 9/
Rook 88개 리소스 차트 검증이 통과했고 종료 코드는 0입니다.
같은 커밋의 [GitHub Actions](https://github.com/tangt64/duststack-k8s-auto/actions/runs/41218524721)도
success입니다. 이 결과는 실제 Kubernetes 배포·Cilium 통신·PVC I/O를 포함하지 않습니다.

전용 랩에서 확인한 넓은 관리망 prefix 사례를 반영해 생성기에 `--pod-cidr`와
`--service-cidr`를 추가했습니다. 입력한 내부 노드 네트워크 전체와의 겹침 및 IPv6·
잘못된 CIDR를 생성 단계에서 거부합니다. 로컬 필수 검증과 회귀 33개가 통과했습니다.
추가 관리 NIC·VPN·라우팅 범위는 실제 호스트에서 별도로 확인해야 합니다.

실제 신규 클러스터에서는 네 노드 Ready와 Cilium agent 네 개 Ready 뒤에도
`kubectl logs`가 `tls: internal error`로 실패했습니다. `serverTLSBootstrap: true`의
Pending serving CSR를 처리하는 단계가 빠져 있었습니다. 후처리에 인벤토리 IP·노드명,
요청자·그룹, 실제 CSR 서명·주체·SAN·용도 검증을 추가하고 별도 갱신 플레이북도
제공합니다. 상시 승인 권한을 만들거나 TLS bootstrap을 해제하지 않습니다.

Rook 실증에서는 `chown-container-data-dir` 초기화가 `container_var_lib_t` 경로의
`setattr` AVC로 실패했습니다. SELinux Enforcing을 유지하며 전용 Rook 디렉터리에만
영구 컨테이너 데이터 라벨을 적용하는 준비 작업을 추가했습니다. symlink·상위 경로를
거부하고 파일시스템 경계를 넘지 않습니다. MON의 privileged 실행은 추가하지 않으며
디스크 hotplug 자동 orchestration도 명시적으로 해제합니다.
이 변경은 로컬 필수 검사·회귀 39개와 Cilium/NFS/Rook 공식 차트의 실제 렌더링을
통과했습니다. 호스트 적용 후의 Ceph Ready·PVC I/O 결과는 별도로 확인합니다.

`bdc2c83`에서 Cilium과 NFS의 실제 부분 실증을 수행했습니다. Cilium agent 4개,
교차 노드 HTTP·서비스/DNS·NetworkPolicy 차단/허용, NFS PVC 4 MiB 체크섬·RWX 공유
쓰기·세 번째 worker 재연결 I/O가 통과했습니다. `partial_passed`, 완료 provider는
`[nfs]`이며 Rook 실증을 포함하지 않습니다. 실제 화면은
[사용 안내](TERMINAL-LAB-WALKTHROUGH.md)에 있습니다.
