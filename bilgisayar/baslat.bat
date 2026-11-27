@echo off
rem Vadeli Sinyal Tarayici - Windows tek tikla baslatici. Cift tiklayin.
chcp 65001 >nul
cd /d "%~dp0"
title Vadeli Sinyal Tarayici
set "PYCMD="
py -3 -c "import sys" >nul 2>&1 && set "PYCMD=py -3"
if not defined PYCMD python -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>&1 && set "PYCMD=python"
if not defined PYCMD (
  echo Python bulunamadi. Python 3.11 veya ustunu kurun.
  echo Kurulumun ilk ekraninda "Add python.exe to PATH" kutusunu ISARETLEYIN.
  start "" https://www.python.org/downloads/
  pause
  exit /b 1
)
%PYCMD% baslat.py %*
if errorlevel 1 pause
