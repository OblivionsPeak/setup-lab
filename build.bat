@echo off
pyinstaller --noconfirm --onefile --noconsole --name SetupLab ^
  --add-data "templates;templates" --add-data "static;static" app.py
echo.
echo Built dist\SetupLab.exe
