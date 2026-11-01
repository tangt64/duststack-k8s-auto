#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.."
branch="${1:-$(git branch --show-current)}"
git check-ref-format --branch "$branch" >/dev/null
for remote in origin gitea; do
  git remote get-url "$remote" >/dev/null
done
for remote in origin gitea; do
  if ! git push "$remote" "refs/heads/$branch:refs/heads/$branch"; then
    printf '원격 %s 푸시 실패: 앞서 성공한 원격은 되돌리지 않습니다. 충돌·인증을 해결한 후 재실행하세요.\n' "$remote" >&2
    exit 1
  fi
done
