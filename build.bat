@echo off
chcp 65001 >nul
echo ========================================
echo  MiniMax Tray 打包工具
echo ========================================
echo.

set PYTHON=python
where python >nul 2>&1 || (
    echo 未找到 python，请确保已安装 Python 3.10+
    pause
    exit /b 1
)

echo [1/3] 检查依赖...
%PYTHON% -m pip install pystray pillow requests pyinstaller --quiet
if errorlevel 1 (
    echo 依赖安装失败！
    pause
    exit /b 1
)
echo 依赖检查完成。

echo.
echo [2/3] 开始打包...
%PYTHON% -m PyInstaller ^
    --onefile ^
    --windowed ^
    --name "MiniMaxTray" ^
    --icon "icon.ico" ^
    --add-data "icon.ico;." ^
    minimax_tray.py

if errorlevel 1 (
    echo.
    echo 打包失败！尝试不带图标打包...
    %PYTHON% -m PyInstaller ^
        --onefile ^
        --windowed ^
        --name "MiniMaxTray" ^
        minimax_tray.py
)

echo.
echo [3/3] 完成！
if exist "dist\MiniMaxTray.exe" (
    echo 可执行文件已生成: dist\MiniMaxTray.exe
    echo 文件大小:
    for %%A in (dist\MiniMaxTray.exe) do echo   %%~zA 字节
) else (
    echo 未找到输出文件，请检查错误信息。
)

echo.
pause
