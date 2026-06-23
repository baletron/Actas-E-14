@echo off
REM ============================================================
REM Descarga masiva actas E-14 2da vuelta presidencial 2026
REM Corre en tu PC Windows con red Colombia.
REM ============================================================

setlocal enabledelayedexpansion
cd /d "%~dp0"

echo.
echo ========================================
echo Actas E-14 Colombia 2026 - 2da Vuelta
echo ========================================
echo.

REM Detectar Python
where py >nul 2>nul
if not errorlevel 1 (set PY=py -3) else (set PY=python)
where %PY% >nul 2>nul || (
    echo [ERROR] Python no encontrado en PATH.
    echo Instala desde https://python.org y reintenta.
    pause & exit /b 1
)
%PY% --version

REM Install certifi PRIMERO (necesario para msys2 Python sin CA bundle)
echo.
echo [1/5] Instalando certifi (obligatorio para SSL)...
%PY% -m pip install --quiet --break-system-packages certifi 2>nul
if errorlevel 1 (
    %PY% -m pip install --quiet certifi 2>nul
)
%PY% -c "import certifi; print('certifi:',certifi.where())" || (
    echo [ERROR] certifi no instalable. Instala manual:
    echo   %PY% -m pip install --break-system-packages certifi
    pause & exit /b 1
)

REM Test conectividad con certifi
echo.
echo [2/5] Probando conectividad...
%PY% -c "import urllib.request,ssl,certifi; ctx=ssl.create_default_context(cafile=certifi.where()); r=urllib.request.urlopen(urllib.request.Request('https://e14segundavueltapresidente.registraduria.gov.co/',headers={'User-Agent':'Mozilla/5.0'}),timeout=20,context=ctx); print('  Sitio HTTP',r.status)"
set SITE_OK=%errorlevel%
%PY% -c "import urllib.request,ssl,certifi,json; ctx=ssl.create_default_context(cafile=certifi.where()); r=urllib.request.urlopen(urllib.request.Request('https://cognito-identity.us-east-2.amazonaws.com/',data=json.dumps({'IdentityPoolId':'us-east-2:f44a557a-d26b-4f14-8a4d-1de5a0b0f7aa'}).encode(),method='POST',headers={'Content-Type':'application/x-amz-json-1.1','X-Amz-Target':'AWSCognitoIdentityService.GetId','User-Agent':'Mozilla/5.0'}),timeout=20,context=ctx); print('  Cognito HTTP',r.status,'->', r.read()[:80].decode())"
set COG_OK=%errorlevel%

if not %SITE_OK%==0 if not %COG_OK%==0 (
    echo [ERROR] Ni sitio ni Cognito responden. Verifica internet.
    pause & exit /b 1
)
if not %SITE_OK%==0 echo   [INFO] Sitio principal falla, usaré GraphQL via Cognito (OK).
if not %COG_OK%==0 echo   [INFO] Cognito falla, usaré sitio principal (OK).

REM Bajar catalogo (con fallback GraphQL automatico)
echo.
echo [3/5] Descargando catalogo...
%PY% download_actas.py fetch-catalog --out catalog.json
if errorlevel 1 (
    echo [ERROR] Catalogo fallo en ambos modos. Aborto.
    pause & exit /b 1
)
for %%I in (catalog.json) do echo   catalogo: %%~zI bytes

REM Descarga PDFs
echo.
echo [4/5] Descargando PDFs (Ctrl+C cancela, re-ejecutar reanuda)...
%PY% download_actas.py download --from-catalog catalog.json --out actas\ --workers 12 --throttle-ms 60

REM Git commit + push por departamento
echo.
echo [5/5] Subiendo a GitHub...
where git >nul 2>nul && (
    for /d %%D in (actas\*) do (
        echo Procesando depto %%~nxD...
        git add "%%D" 2>nul
        git commit -m "Actas E-14 depto %%~nxD" 2>nul && git push 2>nul
    )
) || echo [WARN] git no encontrado, saltando push.

echo.
echo LISTO. PDFs en: %CD%\actas\
pause
