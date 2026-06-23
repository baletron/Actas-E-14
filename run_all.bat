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

REM Usa Python Windows nativo, no msys2
set PY=python
where %PY% >nul 2>nul || (
    echo [ERROR] Python no encontrado en PATH.
    echo Instala desde https://python.org y reintenta.
    pause & exit /b 1
)
%PY% --version

REM Test conectividad
echo.
echo [0/5] Probando conectividad...
%PY% -c "import urllib.request, ssl; r=urllib.request.urlopen('https://e14segundavueltapresidente.registraduria.gov.co/', timeout=15, context=ssl.create_default_context()); print('Sitio responde HTTP', r.status)"
if errorlevel 1 (
    echo.
    echo [WARN] Sitio principal no responde. Probare via GraphQL AWS AppSync...
    %PY% -c "import urllib.request, json; r=urllib.request.urlopen(urllib.request.Request('https://cognito-identity.us-east-2.amazonaws.com/', data=json.dumps({'IdentityPoolId':'us-east-2:f44a557a-d26b-4f14-8a4d-1de5a0b0f7aa'}).encode(), method='POST', headers={'Content-Type':'application/x-amz-json-1.1','X-Amz-Target':'AWSCognitoIdentityService.GetId'}), timeout=15); print('Cognito OK:', r.read()[:100])"
    if errorlevel 1 (
        echo [ERROR] Ni el sitio ni Cognito responden. Tu red bloquea o no hay internet.
        pause & exit /b 1
    )
)

REM Instalar certifi opcional
echo.
echo [1/5] Instalando certifi (opcional)...
%PY% -m pip install --quiet --break-system-packages certifi 2>nul || (
    %PY% -m pip install --quiet certifi 2>nul || echo   [skip] certifi no instalado, se usaran certs default
)

REM Bajar catalogo (con fallback GraphQL automatico)
echo.
echo [2/5] Descargando catalogo (estatico + fallback GraphQL)...
%PY% download_actas.py fetch-catalog --out catalog.json
if errorlevel 1 (
    echo [ERROR] Catalogo fallo en ambos modos. Aborto.
    pause & exit /b 1
)

for %%I in (catalog.json) do echo Catalogo: %%~zI bytes

REM Descarga PDFs
echo.
echo [3/5] Descargando PDFs...
echo Tip: Ctrl+C cancela. Re-ejecutar reanuda (skip de archivos existentes).
%PY% download_actas.py download --from-catalog catalog.json --out actas\ --workers 12 --throttle-ms 60

REM Git commit + push
echo.
echo [4/5] Subiendo a GitHub (por departamento)...
where git >nul 2>nul && (
    for /d %%D in (actas\*) do (
        echo Procesando depto %%~nxD...
        git add "%%D" 2>nul
        git commit -m "Actas E-14 depto %%~nxD" 2>nul && git push 2>nul
    )
) || echo [WARN] git no encontrado, saltando push.

echo.
echo [5/5] Listo. PDFs en: %CD%\actas\
pause
