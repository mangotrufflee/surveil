@echo off
REM Start the Next.js frontend on http://localhost:3000
setlocal
cd /d "%~dp0frontend"
if not exist "node_modules" (
  echo Installing npm dependencies...
  call npm install || exit /b 1
)
echo Starting frontend on http://localhost:3000
call npm run dev
