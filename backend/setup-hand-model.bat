@echo off
REM One-time setup: vendored hand model -> ONNX runtime model.
REM
REM The hand detector from https://github.com/victordibia/handtracking is a
REM TensorFlow 1.x frozen graph. TF1 cannot be installed on a current Python, so
REM this converts the frozen graph to ONNX once. TensorFlow pins protobuf<5 while
REM ultralytics wants a newer protobuf, so the conversion runs in its own
REM virtualenv and TensorFlow is never present in the runtime environment.
setlocal
cd /d "%~dp0.."

if not exist "vendor\handtracking\hand_inference_graph\frozen_inference_graph.pb" (
  echo Cloning the hand model...
  git clone https://github.com/victordibia/handtracking.git vendor\handtracking || exit /b 1
)

cd backend
if not exist ".venv-tools\Scripts\python.exe" (
  echo Creating the tools virtualenv...
  python -m venv .venv-tools || exit /b 1
)
.venv-tools\Scripts\python.exe -m pip install --upgrade pip
.venv-tools\Scripts\python.exe -m pip install -r requirements-tools.txt || exit /b 1
.venv-tools\Scripts\python.exe tools\convert_hand_model.py || exit /b 1

echo.
echo Done. The ONNX hand model is in backend\models\hand_ssd_mobilenet.onnx
