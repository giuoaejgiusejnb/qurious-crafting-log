# 配布用の exe とインストーラーを作る。リポジトリ直下で実行する:
#   pwsh -File scripts\build_release.ps1   （PowerShell 7。Windows PowerShell 5.1 では日本語が化ける）
#
# プロジェクトのフォルダで直接 flet build すると、ビルドしたフォルダと一時フォルダのパス
# （C:\Users\<Windows のユーザー名>\...）が exe の中（.pyc・data\app.so・site-packages\bin\*.exe）に
# 記録される。subst でドライブを割り当てても、元の場所に読み替えて記録されるので防げない。
# そのため、コミット済みのファイルだけをユーザー名を含まないフォルダに書き出し、そこでビルドする
# （開発中の __pycache__ も入らない）。できたインストーラーは build\installer\ に置く。
# ビルド用のフォルダは、成功したら消す（-KeepBuildDir で残す）。
param(
    [string]$BuildDir = "C:\build\qcl",
    [string]$TempDir = "C:\build-tmp",
    [string]$Iscc = "C:\Program Files (x86)\Inno Setup 6\ISCC.exe",
    [switch]$KeepBuildDir   # ビルド用のフォルダを残す（exe の中身を調べたいとき。既定では終わったら消す）
)
$ErrorActionPreference = "Stop"
$repo = (Resolve-Path "$PSScriptRoot\..").Path
$flet = Join-Path $repo ".venv\Scripts\flet.exe"

if (git -C $repo status --porcelain) {
    throw "コミットしていない変更があります。ビルドするのはコミット済みの内容だけなので、先にコミットしてください。"
}
if ($BuildDir -match [regex]::Escape($env:USERNAME) -or $TempDir -match [regex]::Escape($env:USERNAME)) {
    throw "ビルド用のフォルダにユーザー名が含まれています: $BuildDir / $TempDir"
}

# コミット済みのファイルだけを書き出す（前回の生成物には古いパスが残るので、毎回作り直す）
if (Test-Path -LiteralPath $BuildDir) { Remove-Item -LiteralPath $BuildDir -Recurse -Force }
New-Item -ItemType Directory -Force $BuildDir, $TempDir | Out-Null
$archive = Join-Path $TempDir "source.tar"
git -C $repo archive --format=tar -o $archive HEAD
tar -x -f $archive -C $BuildDir
Remove-Item -LiteralPath $archive

$env:TEMP = $TempDir; $env:TMP = $TempDir; $env:PYTHONIOENCODING = "utf-8"
Push-Location $BuildDir
try {
    & $flet build windows --yes
    if ($LASTEXITCODE -ne 0) { throw "flet build が失敗しました（終了コード $LASTEXITCODE）" }
} finally { Pop-Location }

# exe の中にユーザー名が残っていないか調べる
# （パスは UTF-8 でも UTF-16 でも記録されうるので、両方の並びで探す）
$name = $env:USERNAME.ToLowerInvariant()
$latin1 = [System.Text.Encoding]::Latin1
$needles = @($latin1.GetString([System.Text.Encoding]::UTF8.GetBytes($name)),
             $latin1.GetString([System.Text.Encoding]::Unicode.GetBytes($name)))
$leaks = Get-ChildItem (Join-Path $BuildDir "build\windows") -Recurse -File | Where-Object {
    $text = $latin1.GetString([System.IO.File]::ReadAllBytes($_.FullName)).ToLowerInvariant()
    ($needles | Where-Object { $text.Contains($_) }).Count -gt 0
}
if ($leaks) {
    $leaks | ForEach-Object { Write-Host "ユーザー名が含まれています: $($_.FullName)" }
    throw "exe の中に Windows のユーザー名（$env:USERNAME）が残っています。インストーラーは作っていません。"
}

Push-Location (Join-Path $BuildDir "installer")
try {
    & $Iscc qurious_crafting_log.iss
    if ($LASTEXITCODE -ne 0) { throw "インストーラーの作成が失敗しました（終了コード $LASTEXITCODE）" }
} finally { Pop-Location }

$out = Join-Path $repo "build\installer"
New-Item -ItemType Directory -Force $out | Out-Null
Copy-Item (Join-Path $BuildDir "build\installer\qurious-crafting-log-setup.exe") $out -Force
Get-Item (Join-Path $out "qurious-crafting-log-setup.exe") | Select-Object FullName, Length, LastWriteTime
Write-Host "コミット $(git -C $repo rev-parse --short HEAD) の内容でビルドしました"

# ビルド用のフォルダは次回も最初から作り直すので、残しても使われない（約 1.3GB）。成功したら消す
# （失敗したときは、原因を調べられるように残る）
if ($KeepBuildDir) {
    Write-Host "exe は $BuildDir\build\windows にあります"
} else {
    Remove-Item -LiteralPath $BuildDir, $TempDir -Recurse -Force
}
