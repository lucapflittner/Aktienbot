@echo off
rem One scheduled run: ingest -> score -> trade. Output goes to logs\run.log.
rem Set NEWSBOT_PYTHON to your interpreter if "python" isn't the right one, e.g.
rem   setx NEWSBOT_PYTHON "C:\Users\<you>\anaconda3\envs\tf-gpu\python.exe"
cd /d "%~dp0.."
if not exist logs mkdir logs
if "%NEWSBOT_PYTHON%"=="" (set PY=python) else (set PY=%NEWSBOT_PYTHON%)
echo ===== %date% %time% ===== >> logs\run.log
"%PY%" -m newsbot run >> logs\run.log 2>&1
