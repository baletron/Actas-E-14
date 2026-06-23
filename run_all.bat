@echo off
REM ============================================================
REM Descarga masiva actas E-14 2da vuelta presidencial 2026
REM Corre en tu PC Windows (red Colombia). NO funciona en sandbox.
REM ============================================================

setlocal enabledelayedexpansion
cd /d "%~dp0"

echo.
echo ========================================
echo Actas E-14 Colombia 2026 - 2da Vuelta
echo ========================================
echo.

REM Verificar Python
where python >nul 2>nul
if errorlevel 1 (
    echo [ERROR] Python no encontrado en PATH.
    echo Instala desde https://python.org y reintenta.
    pause
    exit /b 1
)

REM Instalar dependencias
echo [1/5] Instalando certifi...
python -m pip install --quiet certifi
if errorlevel 1 (
    echo [WARN] pip install fallo. Sigue, puede funcionar sin certifi.
)

REM Bajar catalogo
echo.
echo [2/5] Descargando catalogo allTransmissionCodes.json...
python download_actas.py fetch-catalog --out catalog.json
if errorlevel 1 (
    echo [ERROR] No se pudo bajar catalogo. Sitio caido o sin red Colombia.
    pause
    exit /b 1
)

REM Mostrar tamano catalogo
echo.
for %%I in (catalog.json) do echo Catalogo: %%~zI bytes
echo.

REM Bajar PDFs (todos)
echo [3/5] Descargando PDFs (estimado ~122k mesas, ~30 GB, varias horas)...
echo Puedes cancelar con Ctrl+C y reanudar despues.
python download_actas.py download --from-catalog catalog.json --out actas\ --workers 16 --throttle-ms 50

REM Commit a Git (incremental)
echo.
echo [4/5] Subiendo a GitHub (commits por depto)...
where git >nul 2>nul
if errorlevel 1 (
    echo [WARN] Git no encontrado. Saltando commit/push.
    goto :final
)

for /d %%D in (actas\*) do (
    git add "%%D"
    git commit -m "Actas E-14 depto %%~nxD" 2>nul
    if not errorlevel 1 git push 2>nul
)

:final
echo.
echo [5/5] Listo.
echo PDFs en: %CD%\actas\
echo.
pause
