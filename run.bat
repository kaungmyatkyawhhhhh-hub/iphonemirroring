@echo off
rem Runs iMirror from source. First run creates a virtual environment.
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe (
    py -3 -m venv .venv || python -m venv .venv || goto :nopython
    .venv\Scripts\python -m pip install --upgrade pip
    .venv\Scripts\python -m pip install -r requirements.txt || goto :eof
)
start "" .venv\Scripts\pythonw.exe -m imirror
goto :eof

:nopython
echo Python 3.10+ is required: https://www.python.org/downloads/windows/
pause
