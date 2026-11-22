@echo off
chcp 65001 >nul
rem يبني الواجهة من جديد ثم يشغّل الأداة على http://localhost:8000
cd /d "%~dp0frontend"
if not exist node_modules call npm install
call npm run build || (echo فشل بناء الواجهة & pause & exit /b 1)
cd /d "%~dp0backend"
if not exist .venv ( python -m venv .venv & call .venv\Scripts\activate & pip install -r requirements.txt ) else call .venv\Scripts\activate
start "" http://localhost:8000
uvicorn app.main:app --port 8000
