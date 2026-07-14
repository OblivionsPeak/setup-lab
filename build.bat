@echo off
pyinstaller --noconfirm --onefile --noconsole --name SetupLab --icon icon.ico ^
  --add-data "templates;templates" --add-data "static;static" app.py
echo.
echo Built dist\SetupLab.exe
