@echo off
rem Runs clipbot from this folder's virtual environment. Created for Windows.
if not exist "%~dp0.venv\Scripts\clipbot.exe" (
  echo clipbot is not installed yet. Double-click setup.bat first.
  exit /b 1
)
"%~dp0.venv\Scripts\clipbot.exe" %*
