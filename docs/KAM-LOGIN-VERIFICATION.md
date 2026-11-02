# 임의 사용자 로그인·미인증 접근 차단 검증

2026-11-02, 실제 HTTPS KAM 인증 서버 2개와 격리된 Kubernetes 1.37.0 API·etcd에서 확인했습니다. 로컬 YAML 경로와 Helm 설치 경로를 모두 통과했습니다. 실행 코드는 고정 KAM `860a6b0d6fdc0d2e67725268646fa50970e4c255`와 같으며 이번 변경은 통합 테스트와 문서입니다. 유료 VM은 재가동하지 않았고, Pod scheduling·image pull은 이번 검사의 범위가 아닙니다.

관리자로 임의 ID `probe-f711ab46`와 무작위 비밀번호를 생성했습니다. 비밀번호는 stdin 또는 검증한 TLS 연결로만 전달하며 원문·명령행·문서에 저장하지 않았습니다. 로그인 성공 뒤 `whoami`의 UID가 생성 결과와 일치했습니다. **로그인은 성공하지만 grant 전 Pod 조회는 Forbidden이며, `dev` namespace에 grant 후 성공**했습니다. 일반 사용자의 사용자 관리 작업은 거부됐습니다.

| 시나리오 | 실제 결과 |
| --- | --- |
| 미로그인 사용자 정보 조회 | HTTP 401 · 차단 |
| 미로그인 사용자 목록 조회 | HTTP 401 · 차단 |
| 미로그인 사용자 생성 요청 | HTTP 401 · 차단 |
| 미로그인 namespace Pod 조회 | HTTP 403 · 차단 |
| 미로그인 계정 Secret 조회 | HTTP 403 · 차단 |
| 잘못된 비밀번호 | HTTP 401 · 차단 |
| 존재하지 않는 ID | HTTP 401 · 차단 |
| 위조 토큰으로 사용자 정보 조회 | HTTP 401 · 차단 |
| 위조 토큰으로 Pod 조회 | HTTP 401 · 차단 |
| 비활성 사용자 로그인 | HTTP 401 · 차단 |

실패한 CLI 로그인은 0이 아닌 종료 코드와 HTTP 401을 반환했고 kubeconfig를 생성하지 않았습니다. 미인증 요청은 관리자 인증서·토큰 없이 새 HTTPS 연결로 보냈고, 사용자 CLI는 별도 kubeconfig를 명시했습니다. 기본 관리자 환경으로 요청이 대신 성공하는 경우를 배제합니다. TLS 검증을 끄거나 impersonation을 사용하지 않았습니다.

401은 인증 실패이고, 403은 해당 요청에 대한 권한 거부입니다. Kubernetes가 anonymous identity를 사용하는 경우에도 보호 namespace의 Pod·계정 Secret에는 접근하지 못했습니다. `/healthz` 등 공개 상태 확인 경로를 모두 차단했다는 의미는 아닙니다. 정상 로그인해도 부여받지 않은 namespace·Secret·사용자 관리 권한은 생기지 않습니다.

기존 통합 검사에서 비밀번호 변경·logout·계정 비활성화의 기존 세션 회수, 권한 만료, 계정 삭제 후 같은 ID 재생성 시 이전 권한 미승계도 다시 통과했습니다. 테스트 사용자는 logout·삭제했으며 격리 API·etcd와 임시 인증서·세션 파일은 테스트 종료 시 정리했습니다. Helm 경로의 총 15개 검사와 상태 보존도 통과했습니다.

검증 명령은 `RUN_CHART_VALIDATION=1 bash tests/validate.sh`입니다. 원문은 [로그인·차단 검증 JSON](validation/kam-login-denial-2026-11-02.json), 재현 코드는 [실제 API 통합 테스트](https://github.com/tangt64/KAM/blob/7500763c6b6e0e7f8da4e6556ff42a9c9ad9b87b/tests/run_auth_api.py)입니다.

검증 테스트·문서의 KAM commit: `7500763c6b6e0e7f8da4e6556ff42a9c9ad9b87b`. duststack의 고정 소스는 실행 코드가 동일한 `860a6b0`을 유지합니다.
