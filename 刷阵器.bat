@echo off
rem S6 GUI launcher. Windows system locale must be Chinese (Simplified), ACP 936.
cd /d "%~dp0"
python -m s6gui
if errorlevel 1 pause
