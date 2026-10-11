@echo off
cd /d "%~dp0"
python -m PyInstaller --onefile --noconsole --name PhoneTransfer --add-data "locales;locales" phone_transfer.py
