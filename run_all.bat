@echo off
REM One command from an empty folder (Windows): venv + pinned deps + install + tests + full factory run.
python -m venv .venv || exit /b 1
call .venv\Scripts\activate.bat || exit /b 1
pip install -r requirements.txt || exit /b 1
pip install -e . || exit /b 1
python -m unittest discover -s tests -t . || exit /b 1
if "%NYC311_CONFIG%"=="" (set CFG=config/default.json) else (set CFG=%NYC311_CONFIG%)
nyc311 --config %CFG% -v run
