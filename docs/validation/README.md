# 터미널랩 실제 실행 기록

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
