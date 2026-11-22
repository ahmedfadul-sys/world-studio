@echo off
rem Windows: run from the repo root after creating .venv (python -m venv .venv ^&^& .venv\Scripts\pip install -r requirements.txt)
cd /d %~dp0..\backend
if "%BIM_DATA_DIR%"=="" set BIM_DATA_DIR=%cd%\..\data
..\.venv\Scripts\python.exe -m uvicorn bimgame.api.app:app --workers 1 --host 127.0.0.1 --port 8000
