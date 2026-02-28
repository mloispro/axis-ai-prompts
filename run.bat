@echo off
setlocal

REM Root launcher for the ai-prompts workbench
cd /d %~dp0tools\workbench-web
call run.bat %*

