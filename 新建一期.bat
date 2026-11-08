@echo off
chcp 65001 >nul
setlocal
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
cd /d "%~dp0"

set "TARGET=%~1"
if not defined TARGET goto ask
goto clean

:ask
set /p TARGET=把音频文件夹（或音频文件）拖进来：
if not defined TARGET goto empty

:clean
for %%A in ("%TARGET%") do set "TARGET=%%~fA"
if not exist "%TARGET%" goto missing
goto run

:empty
echo 没有输入。
pause
exit /b 2

:missing
echo 找不到：%TARGET%
pause
exit /b 2

:run
echo.
echo 建期：%TARGET%
echo.
where python >nul 2>nul
if errorlevel 1 (
    py -3 "%~dp0tools/new_episode.py" "%TARGET%"
) else (
    python "%~dp0tools/new_episode.py" "%TARGET%"
)
echo.
echo 结束。按任意键关闭。
pause
