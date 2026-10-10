@echo off
rem 画像フォルダを圧縮なしで 1 つの .tar にまとめ、ギガファイル便を開く。
rem 使い方: フォルダをこのファイルの上にドラッグ＆ドロップする（ダブルクリックならフォルダ選択が出る）。
chcp 65001 >nul
setlocal

set "SRC=%~1"
if defined SRC goto have_src
for /f "usebackq delims=" %%I in (`powershell -NoProfile -Command "Add-Type -AssemblyName System.Windows.Forms; $d = New-Object System.Windows.Forms.FolderBrowserDialog; $d.Description = '送る画像のフォルダを選んでください'; if ($d.ShowDialog() -eq 'OK') { $d.SelectedPath }"`) do set "SRC=%%I"
if not defined SRC goto no_src

:have_src
if not exist "%SRC%\" goto not_folder
for %%I in ("%SRC%") do set "NAME=%%~nxI"
for %%I in ("%SRC%") do set "PARENT=%%~dpI"
set "OUT=%PARENT%%NAME%.tar"
if exist "%OUT%" goto out_exists

echo まとめています（2GB で 1 分ほど）...
echo   %SRC%
tar -cf "%OUT%" -C "%PARENT%." "%NAME%"
if errorlevel 1 goto failed

echo.
echo できました:
echo   %OUT%
echo.
echo 開いたブラウザのギガファイル便に、このファイルをドラッグしてください。
explorer /select,"%OUT%"
start "" https://gigafile.nu/
goto end

:no_src
echo フォルダが選ばれませんでした。
goto end

:not_folder
echo フォルダではありません:
echo   %SRC%
goto end

:out_exists
echo 同じ名前のファイルがすでにあります。消すか名前を変えてから、もう一度実行してください:
echo   %OUT%
goto end

:failed
echo まとめるのに失敗しました。
if exist "%OUT%" del "%OUT%"

:end
echo.
pause
