@echo off
rem Double-click to open the dashboard as a VIEWER: no agent, no card id badges.
rem For building and editing, use "Start dashboard.cmd" (agent + badges). Close this window to stop.
cd /d "%~dp0"
call npm run dev -- --open
pause
