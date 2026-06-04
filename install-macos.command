#!/bin/bash
# 배달의민족 한나체 한글완성판 — macOS 설치 스크립트
# 하는 일: ① 폰트를 사용자 폰트 폴더에 복사 ② 폰트 캐시 비우기 (그게 전부입니다)
set -e
cd "$(dirname "$0")"

FONT=$(ls *Hangul11172*.ttf 2>/dev/null | head -1)
if [ -z "$FONT" ]; then
  echo "같은 폴더에서 폰트 파일(*Hangul11172*.ttf)을 찾지 못했습니다."
  read -p "엔터를 누르면 닫힙니다." _; exit 1
fi

cp "$FONT" ~/Library/Fonts/
echo "폰트 복사 완료: ~/Library/Fonts/$FONT"

echo "폰트 캐시를 비웁니다. (Mac 로그인 비밀번호를 입력하세요 — 입력해도 화면에 안 보이는 게 정상)"
sudo atsutil databases -remove || echo "캐시 삭제를 건너뛰었습니다. 적용이 안 되면 Mac을 재부팅하세요."

echo ""
echo "설치 완료! 사용 중이던 앱(메모 등)을 완전히 종료 후 다시 열면 적용됩니다."
read -p "엔터를 누르면 닫힙니다." _
