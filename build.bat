@echo off
setlocal

set "ICON_ARG=--icon app-t.ico"
if exist app.ico set "ICON_ARG=--icon app.ico"

python -m PyInstaller --noconfirm --clean --windowed --name "TurkishKeyboardAgent" %ICON_ARG% ^
  --hidden-import keyboard ^
  --hidden-import pyperclip ^
  --hidden-import pyautogui ^
  --hidden-import requests ^
  --hidden-import dotenv ^
  --hidden-import PySide6 ^
  --hidden-import PySide6.QtCore ^
  --hidden-import PySide6.QtGui ^
  --hidden-import PySide6.QtWidgets ^
  --hidden-import loading_overlay ^
  --hidden-import chat_store ^
  --add-data "data;data" ^
  --add-data ".env.example;." ^
  --add-data "README.md;." ^
  main.py

echo.
echo Build output:
echo dist\TurkishKeyboardAgent\TurkishKeyboardAgent.exe
