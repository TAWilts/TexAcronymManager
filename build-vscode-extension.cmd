@echo off
setlocal EnableExtensions

set "ROOT=%~dp0"
set "EXTENSION_DIR=%ROOT%vscode-extension"

if not exist "%EXTENSION_DIR%\package.json" (
    echo ERROR: vscode-extension\package.json was not found.
    echo Run this script from a TAcroMan repository checkout.
    exit /b 1
)

where npm >nul 2>nul
if errorlevel 1 (
    echo ERROR: npm was not found in PATH.
    echo Install Node.js LTS and reopen the terminal.
    exit /b 1
)

pushd "%EXTENSION_DIR%" || exit /b 1

echo.
echo [1/3] Installing/updating Node dependencies...
call npm install --no-fund --no-audit
if errorlevel 1 goto :failed

echo.
echo [2/3] Running extension tests...
call npm test
if errorlevel 1 goto :failed

echo.
echo [3/3] Building VSIX package...
call npm run package
if errorlevel 1 goto :failed

set "VSIX="
for /f "delims=" %%F in ('dir /b /a-d /o-d tacroman-vscode-*.vsix 2^>nul') do (
    if not defined VSIX set "VSIX=%EXTENSION_DIR%\%%F"
)

echo.
echo ========================================
echo TAcroMan VS Code extension build complete.
if defined VSIX echo VSIX: %VSIX%
echo ========================================
popd
exit /b 0

:failed
echo.
echo ERROR: VS Code extension build failed.
popd
exit /b 1
