@echo off
REM ============================================================
REM 매일 1회 실행 (윈도우 작업 스케줄러에 등록해서 사용)
REM 이번 시즌 끝난 경기를 Understat에서 받아 DB에 넣고 GitHub에 올린다.
REM GitHub에 올라가면 Streamlit 배포 앱이 자동으로 새 DB를 쓴다.
REM 기록은 data_collection\daily_update.log 에 남는다.
REM ============================================================
chcp 65001 >nul
set PYTHONUTF8=1
cd /d "%~dp0.."
call ..\..\.venv\Scripts\activate.bat 2>nul || call .venv\Scripts\activate.bat 2>nul || call ..\.venv\Scripts\activate.bat 2>nul

set LOG=data_collection\daily_update.log
echo. >> %LOG%
echo ===== %date% %time% ===== >> %LOG%

REM main 브랜치에서만 실행 (다른 브랜치에서 작업 중이면 건드리지 않음)
for /f %%b in ('git rev-parse --abbrev-ref HEAD') do set BR=%%b
if not "%BR%"=="main" (
    echo [건너뜀] 지금 브랜치가 main이 아님: %BR% >> %LOG%
    exit /b 1
)

git pull --rebase --autostash >> %LOG% 2>&1
python data_collection\update_current_season.py >> %LOG% 2>&1
if errorlevel 1 (
    echo [실패] 수집 중 오류. 위 기록 확인 >> %LOG%
    exit /b 1
)

git add football_history.db database\entity_embeddings.npz
git diff --cached --quiet
if not errorlevel 1 (
    echo [완료] 새로 끝난 경기 없음 - 올릴 내용 없음 >> %LOG%
    exit /b 0
)
git commit -m "데이터 자동 갱신 (%date%)" >> %LOG% 2>&1
git push >> %LOG% 2>&1
if errorlevel 1 (
    echo [실패] GitHub 업로드 실패. 인터넷·로그인 확인 >> %LOG%
    exit /b 1
)
echo [완료] 새 경기 반영 후 GitHub 업로드 >> %LOG%
