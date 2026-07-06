@echo off
REM ============================================================
REM  Kali Tools GUI - one-click installer  (by Hareli Dudai)
REM  Double-click to install. Elevates for boot-persistence.
REM ============================================================
echo Starting Kali Tools GUI installer...
powershell -NoProfile -ExecutionPolicy Bypass -Command "Start-Process powershell -Verb RunAs -ArgumentList '-NoProfile -ExecutionPolicy Bypass -File \"%~dp0setup.ps1\"'"
