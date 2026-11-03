# 2026-11-02 KAM 로컬 설치·플레이북 검토

KAM 로컬 설치 패키지를 독립 저장소의 `07f4f03ef2f0005abd995fc415efeb61f2e6662e`로 GitHub·Gitea에 게시하고 `config/kam-source.json`의 commit·아카이브 SHA-256·파일별 해시를 갱신했습니다. 여기서 로컬 설치란 차트 저장소 등록 없이 소스 차트를 직접 사용하는 방식입니다. 배포 아카이브·바이너리는 Git에 추가하지 않습니다.

## 현재 PC에서 사용

```bash
kam_source="$(python scripts/prepare_kam_source.py)"
cd "$kam_source"
# 전체 순서는 docs/LOCAL-INSTALL.md 참고
python deploy/render_install.py -f deploy/values-local.yaml --audience 기존APIaudience --output artifacts/install
helm template kiki-kam ./charts/kiki-kam -n kam-system --include-crds \
  -f deploy/values-local.yaml --set auth.audience=기존APIaudience
```

`auth.image`, API audience, 접속 URL은 실제 환경 값을 명시해야 합니다. 로컬 프로필은 auth 태그와 단일 replica를 명시적으로 허용합니다. 이미지가 노드 CRI 저장소에 있어야 하며 워크스테이션 Podman 저장소와 같다고 가정하지 않습니다. 실제 Secret과 TLS를 values·차트에 넣지 않습니다. CRD는 Helm upgrade/delete 밖에서 검토하며 [Helm 공식 CRD 지침](https://helm.sh/docs/chart_best_practices/custom_resource_definitions/)과 같은 보존 경계를 사용합니다.

Helm은 애플리케이션 리소스만 관리하고, API 서버 연결은 다음 명령으로 분리합니다.

```bash
bash setup-k8s.sh kam-webhook -i inventory/local-lab/hosts.yaml \
  -e kam_confirm_admin=true -e kam_auth_url=https://kam.example.internal:30443 \
  -e kam_auth_tls_dir=/private/kam-pki
```

기본 검증은 고정된 KAM 소스의 차트도 검사합니다. 독립 KAM checkout을 수정하는 개발 작업에서만 다음 override를 사용합니다.

```bash
export KAM_SOURCE_DIR="$(cd ../kiki-kam && pwd)"
RUN_CHART_VALIDATION=1 bash scripts/validate.sh
```

운영의 기본 고정 소스 검증을 자동으로 우회하지 않습니다. Helm으로 설치한 동일 Deployment·RBAC에 `kam-auth`/`kam`을 다시 실행해 소유권을 섞지 않습니다.

## 발견 및 반영한 사항

| 위험 | 기존 동작 | 로컬 변경 |
| --- | --- | --- |
| 높음 | TLS/config 내용만 바뀌면 API static Pod가 그대로라 새 설정 반영을 보장하지 못함 | 전용 bundle SHA-256을 Pod annotation에 넣어 변경을 식별하고 idempotency 유지 |
| 높음 | API manifest만 복구해 mTLS 파일은 새 내용으로 남을 수 있음 | 같은 노드의 manifest·CA·client cert/key·webhook kubeconfig를 하나의 복구 경계로 묶음 |
| 높음 | CA·endpoint 변경 검사가 auth 리소스 적용보다 늦음 | 모든 control plane에서 사전 검사; implicit CA·endpoint migration 거부 |
| 중간 | 기존 listener의 짧은 종료를 polling이 놓치면 정상 재시작도 실패로 판단 | readiness와 새 mirror Pod UID·bundle annotation을 함께 확인 |
| 중간 | Helm 리소스를 Ansible이 다시 관리할 수 있음 | `kam-webhook` 전용 playbook·CLI 진입점 분리 |
| 중간 | bootstrap 비밀번호 파일의 모드·symlink 미검사 | regular file·0400/0600 확인; 내용은 no_log 유지 |
| 중간 | 다른 CPU도 amd64로 간주할 수 있음 | x86_64/aarch64 외 아키텍처 거부 |
| 중간 | 일부 kube-* namespace가 설치 대상 검사를 통과 | 모든 kube-* 거부; 패키지와 Python renderer도 일치 |
| 중간 | check mode·일부 control plane만 limit할 때 선행 facts/실행 확인이 불완전 | auth/webhook은 전체 CP와 실제 검증을 요구하고 해당 모드 거부 |

새 사전 검사는 인증서 chain·purpose·호스트·키 일치·전용 client CN·만료 24시간 이상을 확인합니다. 클러스터 CA를 재사용하지 않습니다. `--syntax-check`와 로컬 chart/YAML render는 사용할 수 있습니다.

## 추가 확인이 필요한 운영 항목

- 새 순차 적용·bundle rollback과 실제 Helm Pod 배포는 [터미널랩 실증](KAM-HELM-LIVE.md)에서 확인했습니다. 원문·실제 화면·정리 결과는 해당 문서에 구분했습니다.
- 최초 webhook 활성화·같은 CA의 leaf 갱신·잘못된 키 사전 거부·CP02 실제 시작 실패 후 rollback·복구 후 재실행을 실제 랩에서 통과했습니다. check/partial-limit 거부는 별도 사전 검사·회귀 범위입니다.
- 같은 CA의 클라이언트 leaf는 지원하지만 CA 교체·endpoint 이동은 이 playbook이 자동 처리하지 않습니다. 기존·신규 trust 동시 수용과 endpoint 가용성을 갖춘 별도 migration이 필요합니다.
- Helm CRD upgrade·기존 Ansible 리소스 소유권 이전·controller 대상 namespace 제거 시 잔여 Grant/Binding 처리도 관리 절차가 필요합니다. Helm uninstall은 자동 권한 회수가 아닙니다.
- 인증 서비스 Pod readiness·worker 분산 배치·CRI-O 이미지 공급·private NodePort TLS 갱신은 실증했습니다. 운영 registry pull 인증·private LB의 mTLS 전달·인증서 만료 알림·etcd Secret 저장 암호화/백업은 사이트별 운영 검토가 필요합니다.
- 기존 CNI/CIDR/API VIP·Rook 디스크 선택·데이터 보존 설정은 변경하지 않았습니다.

## 검증 기록

검사 결과는 이 로컬 작업의 로그와 완료 보고에서 구분합니다. 차트 lint/렌더링·실제 API 수용 및 Helm lifecycle 검사와 실제 Pod/VM 실행 성공을 같은 결과로 표시하지 않습니다.

### 완료한 로컬 검증

- 최종 `bash scripts/validate.sh`에서 **85개 회귀**, 실제 controller API·CLI 통합·공식 차트 4개·고정 KAM 차트 검사를 모두 통과했습니다. GitHub Ubuntu multi-call 실행 경로와 Ansible stderr 판정 회귀도 포함합니다.
- Helm 4.3.1의 lint·실제 render와 Python YAML의 **5개 구성 완전 일치**, 잘못된 설정 12가지와 잘못된 release namespace 거부를 확인했습니다.
- 실제 Kubernetes 1.37.0 API/etcd에서 **Helm install·upgrade·uninstall과 로그인/RBAC 13개 조건 통과**. 계정 Secret 데이터·CRD·namespace 보존을 확인했습니다.
- 실제 Ansible 실행에서 check mode는 TLS/file/API 변경 단계 전에 거부됐습니다. 새 mirror UID·bundle·Ready 조건은 정상 및 이전 UID·잘못된 checksum·Ready=False·annotation 없음의 조건을 평가했습니다.
- 실제 실행 중인 캐시 바이너리를 재검증해도 덮어쓰지 않고, 변조된 다른 캐시 파일은 복구되는 회귀를 추가했습니다.
- [로컬 API 검증 원문·요약](KAM-LOCAL-RESULT.json)과 [실제 Pod·TLS·rollback 실증](KAM-HELM-LIVE.md)을 별도로 보관했습니다. 로컬 API/etcd 결과와 VM의 실제 수행을 구분합니다.
