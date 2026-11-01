# 터미널랩 실제 실행 기록

## 최종 전체 실행: 12개 검사 통과, 호환성 경고 보존

2026-11-01 12:12 KST에 소스 `dc49538c95b74142796ed1b4942c2a83cb0ca658`의
전체 검증이 `passed_with_warnings`로 끝났습니다. namespace는
`duststack-e2e-full-20261101-r3`, 완료 provider는 `nfs`, `rook` 모두입니다.
기존 전용 VM 4대를 재시작하고 승인한 CSI 키 정책과 control plane의 저장소 역할을
재적용한 뒤 검증했습니다. 새 소스로 클러스터를 초기화하거나 디스크를 지운 실행은 아닙니다.

- Cilium agent 4개, 교차 노드 HTTP, ClusterIP/CoreDNS, 정책 차단·허용 통과
- NFS 4 MiB 체크섬, worker1·worker2 RWX 공유 쓰기, worker3 재연결 입출력 통과
- Ceph 복제 3, RBD 4 MiB 쓰기, worker1→worker2 재연결 후 체크섬·추가 쓰기 통과
- 실제 재연결 Pod의 UID 1000과 체크섬을 화면 촬영 직전 다시 확인
- 재부팅 전 NFS PVC도 새 읽기 전용 Pod에서 기존 체크섬과 쓰기 내용을 확인

| 항목 | 변경 전 | 변경 후 |
| --- | --- | --- |
| CSI 클라이언트 키 | 1세대, 타입 메타데이터 미명시 | AES 2세대, 이전 1세대 보존 |
| MGR 키 | AES256K 1세대 | AES256K 1세대 유지 |
| OSD 키 | AES256K 1세대 | AES256K 1세대 유지 |
| 실제 MON 서비스 티켓 cipher | AES256K | AES256K 유지 |

원문 파일은 브라우저 터미널에서 읽은 뒤 각각 SHA-256을 확인해 보존했습니다.
인증키 값은 내보내지 않고 메타데이터만 기록했습니다.

| 파일 | SHA-256 |
| --- | --- |
| [전체 통과 JSON](terminal-lab-live-2026-11-01.json) | `791e22fdcdd87fbae726337b8d12821f5db3c87c2437f8332d200703ca3e3b6f` |
| [암호 설정 전후 비교](terminal-lab-crypto-2026-11-01.json) | `1352adcc517c098d806cac2f1ce126360800912f40b95d685ab040d10945c051` |
| [기존 NFS 데이터 보존 검사](terminal-lab-retention-2026-11-01.txt) | `1071c3e0b16970207463177b29f1f1e870d7d1bbc8a925d0ba16669942b815ac` |

### 남아 있는 경고와 한계

CSI 3.16.3의 공식 Kubernetes 검증 범위는 1.32~1.34입니다. 실제 1.36.6 조합은
x86-64-v2 전용 랩의 실험이며 운영 지원 조합으로 판정하지 않습니다.
Ceph도 `HEALTH_WARN`을 유지합니다. 다음 경고를 숨기거나 `HEALTH_OK`로 바꾸지 않았습니다.

- `AUTH_INSECURE_CLIENT_KEY_TYPE`
- `AUTH_INSECURE_KEYS_ALLOWED`
- `AUTH_INSECURE_KEYS_CREATABLE`

기존 `restartPolicy: Never` 검증 Pod는 VM 중지 후 Failed 상태였습니다. 해당 Pod에
대한 후속 exec는 실패했으나, 같은 PVC를 새 읽기 전용 Pod에 연결한 별도 보존 검사는
통과했습니다. Pod 수명과 PVC 데이터 보존을 구분합니다.

### 검증 후 접근 권한 회수

worker 3대의 `authorized_keys`에서 이번 전용 랩의 만료된 임시 공개키만 제거하고
일치하는 키가 0개임을 확인했습니다. controller의 해당 개인키·공개키 파일 2개도
제거했습니다. 기존 키는 유지했고, 만료된 접근 권한을 연장하지 않았습니다.
문서·화면·원문을 올린 `a6b9893`의
[GitHub Actions](https://github.com/tangt64/duststack-k8s-auto/actions/runs/41268893970)에서
소스·문법·회귀·CLI 통합·공식 차트 렌더링 검사가 모두 통과했습니다.

사용자 승인 후 전용 VM 4대, 루트 볼륨 4개와 OSD 볼륨 3개(합계 310 GiB),
전용 보안그룹을 삭제했습니다. 볼륨 목록에는 기존 관리형 클러스터의 볼륨 6개
(180 GiB)만 남았으며 해당 자원은 변경하지 않았습니다.
전용 네트워크·서브넷도 삭제 후 목록에서 사라졌음을 확인했습니다. 기존 `net-infra`,
`k8s-private`와 그 클러스터 자원은 유지했습니다. 승인된 90분 연장 시간 안에 검증과
전용 자원 정리를 끝냈습니다.

내장 브라우저는 볼륨 일괄 삭제의 `prompt()` 입력창을 지원하지 않아 개별 삭제와
실제 목록 재조회로 처리했습니다. 네트워크 삭제는 목록 위의 연결 자원 확인 패널에서
`확인 후 삭제 요청`을 거쳐야 합니다. DHCP 관리 포트는 수동 제거하지 않았습니다.
자원 삭제 요청 알림만으로 완료를 판정하지 말고 VM·볼륨·네트워크 목록과 작업 이력을
함께 확인하세요.

## 첫 전체 실행: RBD 커널 마운트 실패

[실제 원문 JSON](terminal-lab-attempt-2026-11-01.json)은 control plane의 보고서를
브라우저 터미널로 읽고 SHA-256을 대조해 보존한 파일입니다.

- 소스: `d06b61ddd08c359366707640f98acf9abece4dc1`
- 결과: `failed`, 범위 `full`, 성공 검사 10개, 완료 provider는 `nfs`만 해당
- Cilium 통신·정책, NFS 체크섬·RWX·교차 노드 재연결, CSI 준비·Ceph 복제를 확인
- RBD PVC는 Bound였지만 커널이 CSI 키를 거부해 Pod Ready 시간 초과로 종료
- CSI 3.16.3/Kubernetes 1.36.6은 공식 검증 범위 밖의 전용 랩 실험
- JSON SHA-256: `0ac8c7b9d4563f1b2e1769b533781ff433a1033b4661b0d78f387475bf323320`

이 파일은 Rook I/O 통과 보고서가 아닙니다. 실제 마운트 오류와 이후 수정은
[검토 기록](../REVIEW.md), 사용 순서와 화면은
[사용 안내](../TERMINAL-LAB-WALKTHROUGH.md)를 참고하세요. 인증정보나 키 값은 포함하지 않습니다.
