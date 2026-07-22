@echo off
title PCA Multiexercicio - Servidor
cd /d "%~dp0"

echo Verificando o projeto...
.venv\Scripts\python.exe manage.py check
if errorlevel 1 (
    echo.
    echo ERRO no check do Django. Veja a mensagem acima.
    pause
    exit /b 1
)

echo Verificando migracoes pendentes...
.venv\Scripts\python.exe manage.py migrate --check >nul 2>&1
if errorlevel 1 (
    echo Aplicando migracoes...
    .venv\Scripts\python.exe manage.py migrate
)

start "" /b cmd /c "timeout /t 3 >nul & start http://127.0.0.1:8000/"

echo.
echo Servidor rodando em http://127.0.0.1:8000/  (Ctrl+C para parar)
echo.
.venv\Scripts\python.exe manage.py runserver
pause
