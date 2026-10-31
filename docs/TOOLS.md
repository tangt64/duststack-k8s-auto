# CLI 실행 파일 공급과 설치

기준일: 2026-10-31. 저장소의 `clusteradm` 2개와 `virtctl-v0.54.0` 실행 파일을
제거했습니다. 바이너리 복구 대신 `common/cli-tool` 역할이 외부 릴리스 파일을 검증해
설치합니다. 기존 Git 커밋의 바이너리 이력은 남습니다. 이력 재작성은 수행하지 않습니다.

## 설치 대상과 범위

| 도구 | 고정 버전 | 원본 파일 | 압축 내부 실행 파일 |
| --- | --- | --- | --- |
| clusteradm | v1.4.0 | clusteradm_linux_amd64.tar.gz | clusteradm |
| virtctl | v1.9.1 | virtctl-v1.9.1-linux-amd64 | 원본 자체 |
| helm | v4.3.1 | helm-v4.3.1-linux-amd64.tar.gz | linux-amd64/helm |

Linux amd64/arm64를 지원합니다. `x86_64`는 `amd64`, `aarch64`는 `arm64`로
매핑하고 다른 아키텍처는 중단합니다. arm64의 파일명과 압축 내부 경로는 표의
`amd64`를 `arm64`로 바꿉니다. 압축 도구는 대상 서버에 `tar`, `gzip`이 필요합니다.

CLI 설치에는 클러스터 API 접근이 필요하지 않습니다. 기존 OCM hub/spoke 역할과
KubeVirt·Helm 역할은 같은 외부 공급 경로를 사용합니다. 과거 공유 `/tmp` 파일의
토큰 명령 실행, OCM init/join, 구형 KubeVirt 매니페스트, Tiller RBAC 적용은 제거했습니다.
`ocm_hub`, `ocm_spoke`, `enabled_virtual`로 레거시 서버 배포를 요청하면 중단합니다.

`virtctl`은 실제 KubeVirt 서버 버전과 호환되는 버전을 선택해야 합니다. Helm 4 CLI를
설치한다고 과거 Helm 2 명령·차트가 호환되는 것은 아닙니다. OCM bundle과 클라이언트
호환성도 리소스 배포 전에 별도로 검증하세요.

## 공통 실행 방법

[README](../README.md)의 Python·Ansible·컬렉션 준비 후 프로젝트 루트에서 실행합니다.
WSL 공유 마운트에서는 설정 파일을 명시하세요.

```bash
export ANSIBLE_CONFIG="$PWD/ansible.cfg"
ansible-playbook playbooks/k8s-tools.yaml --limit 192.168.10.10
```

기본 대상 그룹은 `k8s_master:k8s_hub:k8s_spoke:console`, 기본 도구는
`clusteradm`, `virtctl`입니다. `--limit`에는 인벤토리의 실제 호스트 키를 사용하세요.
도구 목록은 JSON extra-vars 또는 YAML 파일로 지정합니다.

```bash
ansible-playbook playbooks/k8s-tools.yaml --limit 192.168.10.10 \
  -e '{"cli_tools":["clusteradm","virtctl","helm"]}'
```

기본 설치 위치는 `/usr/local/bin/<도구>`이고, root 소유·0755를 적용합니다.
다른 전용 경로는 `cli_tool_install_dir`로 설정합니다. 컨트롤러는 파일 전송용으로만
사용하며, 설치 파일은 대상 서버용 Linux 아키텍처에 맞춰야 합니다.

## 방식 1: 자동 다운로드

`cli_tool_source: download`가 기본입니다. **대상 서버**가 공식 HTTPS URL에서
정확한 버전 파일을 받아 고정된 SHA-256과 비교합니다. 실행할 때마다 latest를
조회하지 않습니다. 인증서 검증을 끄지 않습니다.

캐시는 다음과 같습니다.

```text
/var/cache/duststack/tools/
  clusteradm/v1.4.0/linux-amd64/clusteradm_linux_amd64.tar.gz
  virtctl/v1.9.1/linux-amd64/virtctl-v1.9.1-linux-amd64
  helm/v4.3.1/linux-amd64/helm-v4.3.1-linux-amd64.tar.gz
```

캐시 파일은 root 소유·0600, 개별 캐시 디렉터리는 0700입니다. 압축 해제는 임시
디렉터리에서 수행하고 성공·실패 모두 정리합니다. 최종 실행 파일 교체는 검증 후
Ansible copy의 원자적 쓰기로 수행합니다. 같은 내용이면 최종 파일은 다시 쓰지 않습니다.
캐시 파일은 재사용하며 보존 기간·정리는 운영 정책으로 정하세요.

## 방식 2: 컨트롤러에 수동 배치

`cli_tool_source: controller`를 사용합니다. 기본 루트는 프로젝트의 `artifacts/`입니다.
공식 릴리스에서 받은 **원본 파일**을 아래처럼 배치하세요. tar.gz를 미리 풀지 않습니다.

```text
artifacts/
  clusteradm/v1.4.0/linux-amd64/clusteradm_linux_amd64.tar.gz
  virtctl/v1.9.1/linux-amd64/virtctl-v1.9.1-linux-amd64
  helm/v4.3.1/linux-amd64/helm-v4.3.1-linux-amd64.tar.gz
```

```bash
ansible-playbook playbooks/k8s-tools.yaml --limit 192.168.10.10 \
  -e @examples/tools-controller.yaml
```

컨트롤러의 다른 절대 경로는 `cli_tool_local_dir: /srv/duststack/artifacts`로 지정합니다.
컨트롤러에서 파일 존재·크기·일반 파일 여부·SHA-256을 확인한 뒤 대상 서버로 복사하고,
대상 캐시에서 체크섬을 다시 확인합니다. 대상 서버에 인터넷이 없어도 동작합니다.

## 방식 3: 대상 서버에 수동 배치

`cli_tool_source: target`을 사용합니다. 각 대상 서버에서 기본 루트
`/var/cache/duststack/incoming` 아래에 같은 구조로 배치하세요.

```text
/var/cache/duststack/incoming/
  clusteradm/v1.4.0/linux-amd64/clusteradm_linux_amd64.tar.gz
  virtctl/v1.9.1/linux-amd64/virtctl-v1.9.1-linux-amd64
```

```bash
ansible-playbook playbooks/k8s-tools.yaml --limit 192.168.10.10 \
  -e @examples/tools-target.yaml
```

루트는 `cli_tool_staging_dir`로 바꿀 수 있습니다. 파일·디렉터리를 Ansible의 sudo
사용자가 읽을 수 있어야 합니다. 대상 서버에서 SHA-256을 검증하고 캐시로 복사합니다.
이 방식도 도구 공급에 인터넷을 사용하지 않습니다. Kubernetes RPM, 컨테이너 이미지,
CNI 매니페스트의 공급까지 오프라인으로 전환하는 기능은 별도입니다.

## 버전·사내 미러 변경

릴리스 잠금 정보는 `roles/common/cli-tool/defaults/main.yaml`의 `cli_tool_catalog`입니다.
버전·파일명·URL·압축 내부 경로·아키텍처별 SHA-256을 **함께** 바꾸세요.
다른 버전을 같은 디렉터리에 넣거나 체크섬 검증을 생략하지 않습니다.

사내 미러는 같은 바이트를 제공한다면 공식 체크섬을 그대로 사용할 수 있습니다.
extra-vars YAML에서 필요한 도구의 완전한 항목을 지정하세요. 예를 들어 다음 설정은
clusteradm amd64만 선택하고 같은 릴리스 파일을 사내 HTTPS 미러에서 받습니다.
URL은 실제 미러 주소로 바꿔야 합니다.

```yaml
cli_tools: [clusteradm]
cli_tool_source: download
cli_tool_catalog:
  clusteradm:
    version: v1.4.0
    asset: clusteradm_linux_amd64.tar.gz
    url: https://mirror.example.com/tools/v1.4.0/clusteradm_linux_amd64.tar.gz
    archive_member: clusteradm
    sha256:
      amd64: aa94241caf353a515a0778e0ce608b4c68ced9b3e7f6fb5fe23f48393926153b
```

압축 없는 실행 파일은 `archive_member: ''`를 사용합니다. 체크섬은 신뢰하는 공식
릴리스 메타데이터나 공식 체크섬 파일에서 확보하세요. 파일이 없거나 0바이트이거나
체크섬이 다르면 설치를 중단하며, 기존 실행 파일은 교체하지 않습니다.

`--check`는 다운로드의 경우 네트워크 HEAD 요청을 할 수 있습니다. 수동 배치 모드에서는
실제 파일이 존재해야 합니다. 압축 해제와 최종 실행 파일 설치는 생략하므로 실행 가능성이나
클러스터 호환성 검증을 대신하지는 않습니다.

## 저장소 정책과 검증

`artifacts/`, `.tools/`, 가상환경은 Git에 넣지 않습니다. 외부 산출물은 수동 파일 위치나
캐시에만 보관하세요. `.gitignore`와 `scripts/check_source_tree.py`가 바이너리 재유입을
막습니다. `git add -f`로 예외를 만들지 말고, CI 오류를 해결하세요.

```bash
bash scripts/validate.sh
RUN_CLI_INTEGRATION=1 bash scripts/validate.sh
```

CLI 통합 테스트는 로컬 HTTPS 서버·신뢰하는 임시 CA·작은 테스트 파일을 기본 `.tools/`의
자동 정리되는 임시 디렉터리에서 만들어 다운로드, 두 수동 방식, tar/raw 설치, 같은 파일 재설치, 누락·빈 파일·변조 파일과
메타데이터 거부를 확인합니다. 실제 `/usr/local/bin`, 운영 서버, 클러스터는 변경하지
않습니다. 통합 테스트에 `openssl`, `tar`, `gzip`이 필요합니다.

WSL의 `/mnt/c`, `/mnt/e` 같은 Windows 공유 드라이브는 POSIX 권한과 원자적 rename
동작이 Linux 파일시스템과 다를 수 있습니다. 로컬 통합 테스트는 Linux 임시 경로로
지정하세요. 테스트 디렉터리는 실행 후 자동 정리됩니다.

```bash
CLI_TEST_TEMP_DIR=/tmp RUN_CLI_INTEGRATION=1 bash scripts/validate.sh
```

실제 대상 서버의 설치·캐시 경로도 POSIX 권한과 원자적 쓰기를 지원하는 파일시스템을
사용하세요. 파일시스템 제약을 피하려고 `unsafe_writes`를 활성화하지 않습니다.

## 공식 출처

- [clusteradm v1.4.0](https://github.com/open-cluster-management-io/clusteradm/releases/tag/v1.4.0)
- [KubeVirt/virtctl v1.9.1](https://github.com/kubevirt/kubevirt/releases/tag/v1.9.1)
- [Helm v4.3.1](https://github.com/helm/helm/releases/tag/v4.3.1)
- [Helm 공식 배포](https://get.helm.sh/)
- [OCM 설치 안내](https://open-cluster-management.io/docs/getting-started/installation/start-the-control-plane/)


## CNI·CSI Helm 차트

Cilium·NFS CSI·Rook의 선택 설치는 Helm CLI를 위와 같은 공급 역할로 준비합니다.
차트도 고정 버전·SHA-256 검증과 다운로드/수동 배치를 지원합니다. CLI 도구 설치
플레이북 자체는 차트를 배포하지 않습니다. 경로와 선택 설치는 [CNI·CSI 안내](CNI-CSI.md)를
참고하세요. `artifacts/charts/`의 원본 `.tgz`는 Git에 넣지 않습니다.
