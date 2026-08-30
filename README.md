# qurious-crafting-log

モンスターハンターの錬成結果（`result_log`）を記録・検索するためのWindowsデスクトップアプリです。
NX Macro Controllerなどで大量に自動生成される錬成結果を、Excelに貼り付けて管理する代わりに、
このアプリに取り込んで検索できるようにします。数万件規模のデータでも高速に検索できます。

## ダウンロード・インストール

1. [Releases](../../releases) から最新の `qurious-crafting-log-setup.exe` をダウンロードします。
2. ダウンロードしたexeを実行し、案内に従ってインストールします。
3. インストール後、スタートメニューから起動できます。

Pythonなどの実行環境を別途用意する必要はありません。

## できること

- **取込**：クリップボードにコピーした錬成結果（result_log）を貼り付けで取り込み、練成している防具ごとに記録
- **検索**：スキル集合（保存・呼び出し可能）、コスト、耐性、スキル欠けの有無、取込日時、対象バッチなどで絞り込み検索
- **履歴**：取込バッチ一覧の閲覧・削除、防具ごとの練成数サマリー
- **回収確認**：検索結果で「回収」にチェックを付けると、どのタブを見ていても内容を確認できるサイドパネルで管理
- **設定**：
  - 起動時のアップデート確認のON/OFF
  - 防具ごとの検索初期設定（取込直後に自動で検索タブへ移動する際の初期条件）
  - 検索結果のスキル文字色（プラス/マイナス）のカスタマイズ
  - DBファイルのバックアップ・復元
- **自動アップデート確認**：起動時にGitHub Releasesの最新版を確認し、新しいバージョンがあれば通知

## データの保存場所

`%LOCALAPPDATA%\QuriousCraftingLog\qurious_crafting_log.db`（SQLite）

OneDrive等の同期対象外のフォルダに保存されるため、同期による競合でファイルが壊れる心配がありません。

## 開発者向け

### セットアップ

```powershell
python -m venv .venv
.venv\Scripts\pip install -e .[dev]
```

### アプリの起動

```powershell
.venv\Scripts\flet run app/main.py
```

### テスト

```powershell
.venv\Scripts\pytest
```

### Windows向けビルド（インストーラー作成）

```powershell
.venv\Scripts\flet build windows
& "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" installer\qurious_crafting_log.iss
```

`build\installer\qurious-crafting-log-setup.exe` が生成されます。

新しいバージョンをリリースする際は、`app/version.py` の `APP_VERSION` を、GitHub Releasesの
タグ名と一致するように更新してください（アプリ内の更新チェック機能がこの値を参照します）。

## 技術スタック

- [Python](https://www.python.org/) + [Flet](https://flet.dev/)（GUIフレームワーク）
- SQLite（データ永続化）
- [Inno Setup](https://jrsoftware.org/isinfo.php)（Windowsインストーラー作成）

## お問い合わせ

不具合報告・ご要望は、アプリ内の「お問い合わせ」タブ、または
[GitHub Issues](../../issues) までお願いします。
