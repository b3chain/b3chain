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

setlocal EnableExtensions
set "HERE=%~dp0"
set "VENV=%HERE%.venv"
set "REQ=%HERE%requirements.txt"
set "ENTRY=%HERE%test_ui.py"
set "PYLAUNCH="

rem ---- Locate a Python launcher ----
where py >nul 2>nul
if not errorlevel 1 (
    set "PYLAUNCH=py -3"
    goto :have_python
)

where python >nul 2>nul
if not errorlevel 1 (
    set "PYLAUNCH=python"
    goto :have_python
)

echo ERROR: No Python found on PATH. Install Python 3.9+ from python.org and re-run.
pause
exit /b 1

:have_python

rem ---- Bootstrap the venv on first run ----
if exist "%VENV%\Scripts\python.exe" goto :have_venv

echo Creating virtualenv in "%VENV%" - first run, this takes about a minute...
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

:have_venv

rem ---- Self-check: catch import errors before going windowless.        ----
rem ---- We push the *parent* of the tests dir onto sys.path so the      ----
rem ---- 'tests' package itself is importable.                            ----
"%VENV%\Scripts\python.exe" -c "import sys, os; tests_dir=os.path.dirname(r'%ENTRY%'); sys.path.insert(0, os.path.dirname(tests_dir)); from PyQt6.QtWidgets import QApplication; from tests import test_ui as _t" >nul 2>nul
if errorlevel 1 (
    echo.
    echo ERROR: Python self-check failed. Re-running with full output:
    echo.
    "%VENV%\Scripts\python.exe" -c "import sys, os; tests_dir=os.path.dirname(r'%ENTRY%'); sys.path.insert(0, os.path.dirname(tests_dir)); from PyQt6.QtWidgets import QApplication; from tests import test_ui as _t; print('selfcheck ok')"
    echo.
    pause
    exit /b 1
)

rem ---- Launch the UI (pythonw = no console window). Redirecting stdio ----
rem ---- so the launched process doesn't inherit our pipes; this lets    ----
rem ---- cmd.exe exit immediately even when invoked from a piped shell.  ----
if exist "%VENV%\Scripts\pythonw.exe" (
    start "" "%VENV%\Scripts\pythonw.exe" "%ENTRY%" %* < NUL > NUL 2> NUL
) else (
    start "" "%VENV%\Scripts\python.exe" "%ENTRY%" %* < NUL > NUL 2> NUL
)

endlocal
