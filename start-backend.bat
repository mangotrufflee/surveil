@echo off
REM Start the FastAPI backend (python backend\run.py) on http://127.0.0.1:8000
setlocal
cd /d "%~dp0backend"
if not exist ".venv\Scripts\python.exe" (
  echo Creating virtual environment...
  python -m venv .venv || exit /b 1
  .venv\Scripts\python.exe -m pip install --upgrade pip || exit /b 1
  .venv\Scripts\python.exe -m pip install -r requirements.txt || exit /b 1
)
echo Starting backend on http://127.0.0.1:8000  (docs at /docs)
.venv\Scripts\python.exe run.py
