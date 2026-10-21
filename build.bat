@echo off
pip install -r requirements.txt pyinstaller || exit /b 1
pyinstaller --noconfirm --onefile --windowed --name WindowPartsViewer main.py
echo dist\WindowPartsViewer.exe
