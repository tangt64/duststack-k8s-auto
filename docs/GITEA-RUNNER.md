# 저장소 전용 Gitea runner

대상은 `https://git.vlab.dustbox.kr/dustbox/duststack-k8s-auto`입니다.
이 저장소의 Actions만 받는 `duststack-repo-wsl`을 WSL Rocky Linux 9의 일반 사용자로
등록했습니다. PC와 WSL이 실행 중일 때만 작업을 처리합니다. 운영 서버의 상시 runner가
필요하면 별도 호스트에 같은 제한을 적용하세요. Git 통신은 HTTPS만 사용합니다.

## 고정한 배포본

| 항목 | 버전 및 무결성 |
| --- | --- |
| 공식 Gitea runner | 5.2.0 Linux amd64 |
| 실행 파일 SHA-256 | `2eb05e7c09701ba194c6a43b8669db7eadf0d5c69b6f59f5710426fd68f82f98` |
| 작업 이미지 | `docker.gitea.com/runner-images@sha256:7f347d8a41e2001d2569231ad619aa3b23f8f98ab531f99e8ffb50e9a4d3ef30` |

[공식 설치 안내](https://docs.gitea.com/runner/installation/binary/)에서 배포한 실행 파일과
체크섬을 대조했습니다. 실행 파일은 `.tools/runner-download/`에만 보관하며 Git에는 넣지 않습니다.
등록 토큰과 `.runner`는 인증정보이므로 로그·문서·명령행 인수에 노출하지 않습니다.
재등록 시 공식 `register --token-file`을 사용하고 일회성 토큰 파일을 제거하세요.

## 격리와 실행 조건

- 등록 범위는 저장소 하나이며 라벨은 `ubuntu-latest`입니다.
- 동시 작업은 1개, 작업 제한 20분, workflow 제한 10분입니다.
- rootless Podman 5.8.2를 사용하고 privileged/호스트 디렉터리 bind를 허용하지 않습니다.
- Podman API는 사용자 전용 Unix 소켓으로만 제공합니다. TCP로 노출하지 않습니다.
- `container.docker_host: "-"`로 작업 컨테이너에 Podman 소켓을 전달하지 않습니다.
- 캐시는 끄고 작업 로그는 72시간 보관합니다. 작업에 장기 Git 자격 증명을 제공하지 않습니다.

상태 디렉터리는 `$HOME/.local/share/duststack-gitea-runner`이며 권한은 0700,
그 안의 `.runner`와 `config.yaml`은 0600입니다. 저장소 밖에 두고 백업 공개를 금지하세요.
워크플로는 GitHub의 checkout/setup-python을 명시한 URL에서 가져오므로 외부 통신이 필요합니다.

## WSL의 컨테이너 DNS 오류

현재 WSL은 `user@1000.service`가 `219/CGROUP`으로 실패합니다. 기본 네트워크에서
aardvark-dns가 사용자 bus에 연결하지 못해 최초 작업이 컨테이너 시작 전에 실패했습니다.
이 환경에서는 runner 전용 bridge를 만들고 컨테이너 이름 DNS를 사용하지 않도록 설정했습니다.
외부 이름 해석과 HTTPS 접속은 실제 작업 이미지에서 확인했습니다.

```bash
podman network create --disable-dns duststack-runner-ci
```

`config.yaml`의 관련 설정은 다음과 같습니다. 기존 설정 전체를 덮어쓰지 말고 병합하세요.

```yaml
container:
  network: duststack-runner-ci
  privileged: false
  valid_volumes: []
  docker_host: "-"
  require_docker: true
  bind_workdir: false
```

이 네트워크는 동시 작업 1개인 해당 runner에서만 사용합니다. service 컨테이너의 이름으로
통신하는 workflow에는 이 구성을 그대로 사용하지 마세요. 정상적인 사용자 systemd 세션이
있는 별도 runner에서 작업별 네트워크와 service DNS를 검증해야 합니다.

## 재시작과 중지

등록된 사용자로 저장소 루트에서 두 터미널을 열어 실행합니다. 등록 파일을 새로 만들거나
등록 토큰을 다시 입력할 필요는 없습니다.

```bash
# 터미널 1: rootless 컨테이너 API
podman system service --time=0 \
  unix://$HOME/.local/share/duststack-gitea-runner/podman.sock

# 터미널 2: 저장소 전용 runner
export DOCKER_HOST=unix://$HOME/.local/share/duststack-gitea-runner/podman.sock
.tools/runner-download/gitea-runner-5.2.0-linux-amd64 daemon \
  --config "$HOME/.local/share/duststack-gitea-runner/config.yaml"
```

중지할 때는 실행 중인 작업을 먼저 마치고 runner 터미널에서 Ctrl+C, 이후 Podman API
터미널에서 Ctrl+C를 누릅니다. 다른 Podman 컨테이너를 일괄 종료하거나 정리하지 마세요.
서버의 저장소 설정 → Actions → Runners에서 온라인 상태와 저장소 범위를 확인합니다.
PC 재부팅 후에는 위 두 프로세스를 다시 시작해야 합니다.
