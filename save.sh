#!/usr/bin/env bash
# MARBLE fork 協作用存檔腳本：確認變更 → commit → pull --rebase → push 到 origin（我們的 fork）
#
# 每個人在「自己的 clone」裡執行（例如 ~/yenhua/workflow-experiment/MARBLE），不要在別人的資料夾跑。
# 只推工作分支（例如 local-vllm）；main 用來對齊上游 ulab-uiuc/MARBLE，不從這裡推。
# 因為 poc 是共用帳號，git 身份 / 憑證一律設在 repo-local（.git/ 底下，不會進版控），
# 第一次執行時輸入自己的 GitHub 帳號 + Personal Access Token，之後會自動記住。
#
# 用法：
#   ./save.sh "你的 commit 訊息"     # 有變更時必須給訊息，讓協作者看得懂你改了什麼
#   ./save.sh                        # 沒有變更時可省略，只會同步（pull + push 尚未推送的 commit）

set -euo pipefail
cd "$(git -C "$(dirname "${BASH_SOURCE[0]}")" rev-parse --show-toplevel)"

CRED_FILE="$(git rev-parse --absolute-git-dir)/git-credentials"

# --- 第一次執行時設定身份（僅 repo-local，不動共用的 global 設定） ---
if [[ -z "$(git config --local user.name 2>/dev/null || true)" ]]; then
  read -rp "第一次使用，請輸入你的 git user.name: " GIT_NAME
  git config --local user.name "$GIT_NAME"
fi
if [[ -z "$(git config --local user.email 2>/dev/null || true)" ]]; then
  read -rp "請輸入你的 git user.email: " GIT_EMAIL
  git config --local user.email "$GIT_EMAIL"
fi

# --- 設定憑證快取（只做一次；PAT 存在 .git/ 內，不會進版控） ---
if [[ "$(git config --local credential.helper 2>/dev/null || true)" != "store --file=$CRED_FILE" ]]; then
  git config --local credential.helper "store --file=$CRED_FILE"
  echo "已設定憑證快取於 $CRED_FILE"
  echo "（第一次 push 時 git 會要你輸入「你自己的」GitHub 帳號 + Personal Access Token，"
  echo " 輸入一次之後就會被記住。還沒有 PAT 的話，去 https://github.com/settings/tokens 生一個，勾 repo 權限。）"
fi

# --- github.com 專屬 helper 覆蓋（每次都確保，防止被 global 的 gh helper 蓋掉而用到別人的身份） ---
GH_KEY='credential.https://github.com.helper'
if [[ "$(git config --local --get-all "$GH_KEY" 2>/dev/null | tail -1)" != "store --file=$CRED_FILE" ]]; then
  git config --local --replace-all "$GH_KEY" ''
  git config --local --add "$GH_KEY" "store --file=$CRED_FILE"
fi

echo "身份：$(git config user.name) <$(git config user.email)>"

# --- 有變更就：列出來確認 → commit ---
# 已經 git add 過（staged）→ 只 commit 那些；沒有 staged → 全部 add 再 commit
MSG="${1:-}"
if ! git diff --cached --quiet; then
  if [[ -z "$MSG" ]]; then
    echo "有已 git add 的變更，請附上 commit 訊息：./save.sh \"改了什麼\"" >&2
    git status --short
    exit 1
  fi
  echo "以下「已 git add」的變更將被 commit："
  git diff --cached --name-status
  if [[ -n "$(git status --porcelain | grep -v '^[MADRC] ')" ]]; then
    echo "（其他未 git add 的變更不會 commit，保留在本機）"
  fi
  read -rp "確定要 commit 嗎？[y/N] " ANS
  [[ "$ANS" == [yY] ]] || { echo "已取消。"; exit 1; }
  git commit -m "$MSG"
elif [[ -n "$(git status --porcelain)" ]]; then
  if [[ -z "$MSG" ]]; then
    if [[ -n "$(git status --porcelain --untracked-files=no)" ]]; then
      echo "有未存檔的變更，請附上 commit 訊息：./save.sh \"改了什麼\"" >&2
      git status --short
      exit 1
    fi
    echo "只有未追蹤的新檔案，略過 commit（要存的話先 git add 或附上訊息）："
    git status --short
  else
    echo "以下變更將被 commit："
    git status --short
    read -rp "確定要全部 commit 嗎？[y/N] " ANS
    if [[ "$ANS" != [yY] ]]; then
      echo "已取消。想只存部分檔案，先 git add 想要的檔案，再執行 ./save.sh \"訊息\"（只會 commit 已 add 的）。"
      exit 1
    fi
    git add -A
    git commit -m "$MSG"
  fi
else
  echo "沒有未存檔的變更，略過 commit。"
fi

# --- 先拉協作者的更新（rebase 到最新之上），再推 ---
BRANCH="$(git branch --show-current)"
if [[ -z "$BRANCH" || "$BRANCH" == "main" ]]; then
  echo "目前在 '${BRANCH:-detached HEAD}'，main 只用來對齊上游，請先切到工作分支：git switch local-vllm" >&2
  exit 1
fi
echo "從 origin/${BRANCH} 拉取協作者的更新 ..."
if ! git pull --rebase origin "$BRANCH"; then
  echo >&2
  echo "⚠ 和協作者的修改有衝突，rebase 停在一半。處理方式：" >&2
  echo "   1. git status 看哪些檔案衝突，打開手動修好" >&2
  echo "   2. git add <修好的檔案> && git rebase --continue" >&2
  echo "   3. 再執行一次 ./save.sh 推上去" >&2
  echo "   （想放棄這次同步、回到 pull 之前：git rebase --abort）" >&2
  exit 1
fi

echo "推送到 origin/${BRANCH} ..."
git push origin "$BRANCH"

echo "完成。"
