@echo off
setlocal
pushd "%~dp0\.." || exit /b 1
if not defined PYTHON set "PYTHON=python"
%PYTHON% "src\generate_ghost_candidate.py" %1
set "EXIT_CODE=%ERRORLEVEL%"
popd
exit /b %EXIT_CODE%
