@echo off
REM 校招看板 HTTP 服务器 — 开机自启
REM 另一台电脑访问: http://10.178.79.151:8080/
cd /d D:\hanako\job-board
echo [%date% %time%] Job Board Server Starting...
D:\Python\python.exe -m http.server 8080 --bind 0.0.0.0
