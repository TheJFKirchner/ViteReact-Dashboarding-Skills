@echo off
rem Double-click to start the dashboard with the dashboard agent and open it in your browser.
rem Starts the Analysis server (Python) and the dashboard; the agent comes from the dashboard-work
rem skill (agent.home in dashboard.config.json); if it can't be found, the dashboard starts without it. Close this window to stop.
rem Viewer only: Start dashboard (viewer).cmd
cd /d "%~dp0"
call npm run dev:agent -- --open
pause
