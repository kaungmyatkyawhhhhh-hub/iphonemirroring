@echo off
rem Builds dist\iMirror\iMirror.exe with PyInstaller.
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe py -3 -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt pyinstaller || goto :eof
.venv\Scripts\pyinstaller --noconfirm --windowed --name iMirror --paths . imirror\__main__.py || goto :eof
echo.
echo Built dist\iMirror\iMirror.exe
