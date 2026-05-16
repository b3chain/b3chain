@echo off
rem -------------------------------------------------------------------
rem  b3chain CPU miner -- Windows test UI launcher.
rem
rem  First run creates a private venv next to this script and installs
rem  PyQt6 + blake3 into it. Subsequent runs are instant.
rem
rem  The UI window is launched via pythonw.exe so no console pops up.
rem  If you need to see launcher logs, edit the last line to use python.exe.
rem -------------------------------------------------------------------
setlocal
set HERE=%~dp0
set VENV=%HERE%.venv
set REQ=%HERE%requirements.txt
set ENTRY=%HERE%test_ui.py

rem ---- Locate a Python launcher ----
where py >nul 2>nul
if %ERRORLEVEL%==0 (
    set PYLAUNCH=py -3
) else (
    where python >nul 2>nul
    if %ERRORLEVEL%==0 (
        set PYLAUNCH=python
    ) else (
        echo ERROR: No Python found on PATH. Install Python 3.9+ from python.org and re-run.
        pause
        exit /b 1
    )
)

rem ---- Bootstrap the venv on first run ----
if not exist "%VENV%\Scripts\python.exe" (
    echo Creating virtualenv in "%VENV%" (first run, ~1 minute)...
    %PYLAUNCH% -m venv "%VENV%"
    if errorlevel 1 (
        echo ERROR: Failed to create venv.
        pause
        exit /b 1
    )
    "%VENV%\Scripts\python.exe" -m pip install --upgrade pip
    "%VENV%\Scripts\python.exe" -m pip install -r "%REQ%"
    if errorlevel 1 (
        echo ERROR: pip install failed.
        pause
        exit /b 1
    )
    echo.
    echo Venv ready.
)

rem ---- Launch the UI (pythonw = no console window) ----
if exist "%VENV%\Scripts\pythonw.exe" (
    start "" "%VENV%\Scripts\pythonw.exe" "%ENTRY%" %*
) else (
    "%VENV%\Scripts\python.exe" "%ENTRY%" %*
)

endlocal
