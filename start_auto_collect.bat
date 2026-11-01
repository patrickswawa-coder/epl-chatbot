@echo off
REM 경기 종료 자동 수집을 별도 창에서 실행합니다. (챗봇과 동시에 켜 두세요)
cd /d "%~dp0"
call .venv\Scripts\activate 2>nul || call ..\.venv\Scripts\activate 2>nul || call ..\..\.venv\Scripts\activate 2>nul
python data_collection\auto_collect.py
pause
