@echo off
REM ===========================================================================
REM  refresh_snapshot.cmd -- Task Scheduler entry point for the BOM snapshot.
REM
REM  Rebuilds data\bom.sqlite from the source view, but only if the current
REM  snapshot is older than MAX_AGE_HOURS. Safe to fire at every logon: when
REM  the snapshot is already fresh it exits in under a second without touching
REM  SQL Server.
REM
REM  Register it (run this once, in a normal Command Prompt -- NOT as admin,
REM  so the task runs as you and inherits your database access):
REM
REM    schtasks /Create /TN "BOM Snapshot Refresh" /SC ONLOGON ^
REM      /TR "\"%~f0\"" /RL LIMITED /F
REM
REM  Then check it:   schtasks /Query /TN "BOM Snapshot Refresh" /V /FO LIST
REM  Run it now:      schtasks /Run   /TN "BOM Snapshot Refresh"
REM  Remove it:       schtasks /Delete /TN "BOM Snapshot Refresh" /F
REM
REM  Exit codes: 0 = rebuilt or already fresh | 1 = failed
REM              2 = sanity gate rejected the extract (live snapshot untouched)
REM              3 = skipped, the web app is holding the snapshot open
REM ===========================================================================

setlocal EnableExtensions

REM --- Settings --------------------------------------------------------------
REM Rebuild only if the snapshot is older than this many hours. 20 suits a
REM once-a-day laptop: log on tomorrow and it refreshes, log on again an hour
REM later and it does not.
set "MAX_AGE_HOURS=20"

REM The port uvicorn serves on. Used only to detect that the app is running --
REM the swap cannot rename over a snapshot the app holds open on Windows.
set "APP_PORT=8000"

REM --- Locate the project ----------------------------------------------------
REM %~dp0 is this script's own folder, so the task works regardless of what
REM Task Scheduler sets as the working directory.
set "SCRIPT_DIR=%~dp0"
pushd "%SCRIPT_DIR%.." || exit /b 1
set "PROJECT_DIR=%CD%"

REM --- Locate Python ---------------------------------------------------------
REM Scheduled tasks do not reliably inherit an interactive PATH, so prefer the
REM py launcher, which lives in a fixed location, and fall back to python.
set "PY_CMD="
where py >nul 2>&1 && set "PY_CMD=py -3"
if not defined PY_CMD where python >nul 2>&1 && set "PY_CMD=python"
if not defined PY_CMD (
    echo [%date% %time%] FAILED: no Python found on PATH. Set PY_CMD in this script to a full path, e.g. "C:\Python313\python.exe".
    popd
    exit /b 1
)

REM --- Refuse to run while the app holds the snapshot open --------------------
REM Without this the extract would spend ~2 minutes and a heavy production
REM query, then fail at the swap. Better to skip immediately and say why.
netstat -ano | findstr /R /C:"LISTENING" | findstr /C:":%APP_PORT% " >nul 2>&1
if %ERRORLEVEL% EQU 0 (
    echo [%date% %time%] SKIPPED: something is listening on port %APP_PORT%, so the web app is probably running.
    echo                  The swap cannot replace a snapshot the app holds open. Stop uvicorn and run this again.
    popd
    exit /b 3
)

REM --- Rebuild ---------------------------------------------------------------
echo [%date% %time%] Refreshing the BOM snapshot (rebuild if older than %MAX_AGE_HOURS% h)...
%PY_CMD% "%PROJECT_DIR%\scripts\build_snapshot.py" --max-age-hours %MAX_AGE_HOURS%
set "RC=%ERRORLEVEL%"

if "%RC%"=="0" (
    echo [%date% %time%] OK. Per-run detail is in %PROJECT_DIR%\scripts\logs\.
) else if "%RC%"=="2" (
    echo [%date% %time%] SANITY GATE: the new extract had too few rows and was NOT swapped in.
    echo                  The existing snapshot is untouched. See %PROJECT_DIR%\scripts\logs\.
) else (
    echo [%date% %time%] FAILED with exit code %RC%. See %PROJECT_DIR%\scripts\logs\.
)

popd
exit /b %RC%
