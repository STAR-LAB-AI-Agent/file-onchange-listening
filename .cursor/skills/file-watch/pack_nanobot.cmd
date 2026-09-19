@echo off
setlocal
cd /d "%~dp0"

where python >nul 2>&1
if %errorlevel%==0 (
  python scripts\pack_nanobot.py %*
) else (
  py -3 scripts\pack_nanobot.py %*
)
if errorlevel 1 (
  echo.
  echo nanobot 打包失败。
  pause
  exit /b 1
)
echo.
echo 打包完成。.skill 在 dist\ 目录。
pause
