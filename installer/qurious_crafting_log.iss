; Inno Setup スクリプト。
; 事前に `flet build windows` で build\windows 以下に本体一式を出力しておくこと。
; ビルド方法: ISCC.exe installer\qurious_crafting_log.iss
; （Inno Setup 6がインストールされていれば、通常 "C:\Program Files (x86)\Inno Setup 6\ISCC.exe"）

#define MyAppName "モンハン錬成結果 記録・検索"
#define MyAppVersion "1.2"
#define MyAppExeName "qurious-crafting-log.exe"
#define MyBuildDir "..\build\windows"

[Setup]
AppId={{B7C2B3B0-6C1E-4C7B-9D9C-1B1F1B0B7E2A}}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
DefaultDirName={autopf}\QuriousCraftingLog
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
; %LOCALAPPDATA%側にDBを保存するため、インストール先はProgram Filesで問題ない
OutputDir=..\build\installer
OutputBaseFilename=qurious-crafting-log-setup
Compression=lzma
SolidCompression=yes
WizardStyle=modern
ArchitecturesInstallIn64BitMode=x64compatible
UninstallDisplayIcon={app}\{#MyAppExeName}

[Languages]
Name: "japanese"; MessagesFile: "compiler:Languages\Japanese.isl"

[Tasks]
Name: "desktopicon"; Description: "デスクトップにアイコンを作成する"; GroupDescription: "追加のアイコン:"; Flags: unchecked

[Files]
; build\windows以下を丸ごと同梱（exe本体、DLL、app/data/site-packages等）
Source: "{#MyBuildDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\{cm:UninstallProgram,{#MyAppName}}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#MyAppName}}"; Flags: nowait postinstall skipifsilent
