# 문서용 실제 화면 기록

사용자가 요청한 터미널랩 사용 안내용 JPEG 화면만 저장합니다.
화면은 브라우저에서 해당 영역을 직접 촬영하며 인증정보와 계정 잔액은 포함하지 않습니다.
설치 실행 파일과 차트 아카이브는 이 디렉터리에도 넣지 않습니다.

| 파일 | 촬영일 | 실제로 확인한 범위 |
| --- | --- | --- |
| 01-lab-vms.jpg | 2026-11-01 | 포털에 새 전용 VM 4대가 실행 중으로 표시됨. Node Ready·CNI·PVC 통과와 구분 |
| 02-controller-ready.jpg | 2026-11-01 | 새 control plane SSH에서 Python 3.12.14·Ansible 2.21.5·4 vCPU·7936 MiB·sudo 확인. 소스 c8ab1b7, Kubernetes 설치 전 |
| 03-source-validation.jpg | 2026-11-01 | b558839의 전용 controller 소스 검증. 회귀 31개 통과·스키마 1개 생략, CLI 공급·공식 차트 통과. Kubernetes/PVC I/O는 미수행 |
| 04-cilium-connectivity.jpg | 2026-11-01 | bdc2c83의 실제 Cilium agent·교차 노드 HTTP·ClusterIP/DNS·정책 차단/허용 통과. Cilium/NFS 부분 실증 |
| 05-nfs-pvc-io.jpg | 2026-11-01 | bdc2c83의 실제 NFS RWX·4 MiB 체크섬·교차 노드 재연결 입출력 통과. Rook은 이 부분 실행에 미포함 |
| 06-rook-pvc-io.jpg | 2026-11-01 | dc49538의 실제 전체 12개 검사 PASS_WITH_WARNINGS. RBD 4 MiB 체크섬·worker2 재연결 입출력, CSI AES 2세대, MGR/OSD·서비스 티켓 AES256K 유지, 재부팅 전 NFS 데이터 보존 확인 |
| 07-gitea-actions.jpg | 2026-11-01 | 6791495의 Gitea Actions 실행 2 재실행 성공. 공식 runner 5.2.0·rootless Podman에서 실제 API/CLI/차트 검증. VM의 HA 실증과 구분 |
| 08-ha-vip-failover.jpg | 2026-11-01 | 실제 HA 결과 파일과 촬영 시점 API·노드 상태. VIP 이동 10.01초, probe 21회 중 7회 실패 후 복구, HAProxy 복원, 노드 5대 Ready |
| 09-kam-live-cluster.jpg | 2026-11-01 | 실제 KAM 결과와 촬영 시점 controller 2개 분산 배치. 리더 인수 90.37초, CR 삭제·만료 회수, 남은 Grant 없음과 회수된 subject의 can-i=no |
| 10-ha-vm-power-loss.jpg | 2026-11-01 | LB01 HARD 재부팅의 실제 boot ID 변경, LB02 VIP 인수와 API 복구, readyz 2/91·쓰기 1/91 실패와 sentinel 보존 |
| 11-etcd-quorum.jpg | 2026-11-01 | 실제 양쪽 peer TCP 불가·etcd health/쓰기 실패 표본, 복구 후 sentinel·3-member 유지와 노드 Ready |
| 12-kam-fast-handover.jpg | 2026-11-01 | 리더 Pod 삭제 3회 인수 2.60·2.66·2.70초, 두 worker Ready, namespace·상승 거부·삭제/만료 회수 통과, 남은 Grant 없음 |
| 13-kiki-kam-repository.jpg | 2026-11-01 | 기존 3개 커밋과 새 c2b708e를 유지한 Gitea kiki-kam 저장소. CI 노란 표시는 runner 대기 상태이며 성공 증거가 아님 |
| 14-kiki-kam-actions.jpg | 2026-11-01 | 최종 기능 커밋 e383003의 Gitea KAM Actions 실행 3 전체 성공. Go race·controller 실제 API·비밀번호 실제 API 11개 검사 통과 |

이전 RBD 실패 화면은 [당시 커밋](https://github.com/tangt64/duststack-k8s-auto/blob/dc49538c95b74142796ed1b4942c2a83cb0ca658/docs/screenshots/06-rook-pvc-io.jpg)에
남아 있습니다. 현재 06번 사진은 승인한 키 호환 변경 후 실제 통과 화면입니다.

미수행 단계의 성공 화면을 합성하지 않습니다. 예상 출력은
[사용 안내](../TERMINAL-LAB-WALKTHROUGH.md)의 예시 코드 블록으로 표시합니다.
실제 실증 결과가 나오는 단계부터 사진과 기록을 추가합니다.

소스 검사는 `scripts/check_source_tree.py`에 명시한 파일 경로만 JPEG 크기·프레임 규격을 확인해 허용합니다.
이미지 파일을 추가하거나 교체할 때 원본 화면과 문서의 설명을 함께 검토하세요.
