@echo off
chcp 65001 >nul
title 배달의민족 한나체 한글완성판 설치
echo.
echo  배달의민족 한나체 한글완성판 - Windows 설치
echo  (하는 일: 같은 폴더의 ttf 폰트를 Windows에 설치 등록합니다)
echo.

powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$f = Get-ChildItem -Path $PWD -Filter '*11172*.ttf' | Select-Object -First 1; ^
   if (-not $f) { Write-Host '폰트 파일을 찾지 못했습니다. ttf와 같은 폴더에서 실행하세요.'; exit 1 }; ^
   $sh = New-Object -ComObject Shell.Application; ^
   $sh.Namespace(0x14).CopyHere($f.FullName, 0x10); ^
   Write-Host ('설치 요청 완료: ' + $f.Name)"

echo.
echo  설치 확인 창이 떴다면 [예/설치]를 눌러주세요.
echo  적용이 안 보이면 PC를 한 번 재부팅하세요(폰트 캐시 갱신).
echo.
pause
