# 実装フェーズ一覧

モンスターハンター錬成結果 記録・検索アプリの実装計画と進捗。
設計の全体像は `C:\Users\takuy\.claude\plans\snappy-popping-hummingbird.md` を参照。

全9フェーズ。現在 **Phase 4 完了**。

---

## ✅ Phase 1 - コアロジック（完了）

result_logのパース・スキル集合検索用ビットマスク計算・DBスキーマをUIなしで実装。

- `app/core/parser.py` — result_logの1行パース（固定6項目＋可変個のスキル列）
- `app/core/skill_mask.py` — スキル集合のビットマスク化、許可集合との照合ロジック
- `app/core/skill_registry.py` — スキル名⇔ビットインデックスのDB連携管理
- `app/db/schema.sql` / `app/db/connection.py` — SQLiteスキーマと接続処理
- `tests/test_parser.py`, `tests/test_skill_mask.py`, `tests/test_skill_registry.py`

## ✅ Phase 2 - 取込UI（完了）

貼り付け欄＋バッチメモ入力＋取込ボタン。バックグラウンドでパース・保存し進捗表示。

- `app/core/importer.py` — パース〜バッチ作成〜マスク計算〜DB保存を1トランザクションで実行
- `app/ui/import_view.py` — 貼り付け欄・進捗バー（`page.run_thread`でUIをブロックしない）
- `app/main.py` — アプリのエントリポイント
- `tests/test_importer.py`

**追加改善（ユーザーフィードバックにより追加）:**
- メモ欄を自由記述から「練成している防具」の選択式（ギルパレ脚/クシャ胴/マッスル腕＋自作追加/削除可、前回選択を記憶）に変更
- `app/core/settings.py` — 選択状態・カスタム装備リストをDBに永続化する`app_settings`テーブル用ヘルパー
- `results`テーブルにも`label`（防具名）を非正規化して保存し、防具単位での検索を可能に（`app/core/search.py`の`label`フィルタ、`fetch_distinct_labels()`）
- `app/db/connection.py`に簡易マイグレーション機構を追加（既存DBファイルへの列追加に対応）

## ✅ Phase 3 - 検索コア＋ベンチマーク（完了）

スキル集合検索のコアロジックを実装し、1,000万件規模での検索速度を実測した。

- `app/core/search.py` — ビットマスク方式の検索クエリ組み立て・実行（日付範囲/バッチ/total_cost絞り込みにも対応）
- `tests/test_search.py` — 要件で提示された全判定例＋ランダムデータでの参照実装との突合テスト
- `scripts/benchmark_search.py` — ダミーデータ生成＋検索速度計測スクリプト

**実測結果（許可スキル10種、ヒット率を極めて低く設定した現実的な条件）:**

| 件数 | データ生成時間※ | 検索時間 |
| --- | --- | --- |
| 10万件 | 0.5秒 | 0.01秒 |
| 100万件 | 11.5秒 | 0.07秒 |
| 1,000万件 | 173.0秒 | **0.74秒** |

※データ生成時間はベンチマーク用ダミーデータ作成のコストであり、実運用では取込のたびに少しずつ蓄積されるため無関係。

目標（10〜30秒以内）に対して圧倒的に余裕があり、**Phase 8（numpyインメモリインデックスへの切替）は不要と判断**。SQLite全件走査ベースの実装のまま進める。

## ✅ Phase 4 - 検索UI（完了）

- `app/ui/search_view.py` — skillsマスタから動的取得したスキルのチェックボックス選択（複数可）
- 追加条件: 日付範囲、バッチ絞り込み（ドロップダウン）、防具（label）絞り込み、total_cost以上
- 検索結果一覧表示（最大200件、スキル内訳付き）
- `page.run_thread`による非同期実行＋進捗表示
- `app/core/search.py`に`fetch_skill_breakdown()`を追加（検索結果のスキル内訳をまとめて取得）
- `app/main.py`をタブ構成（取込／検索）に変更

## ⬜ Phase 5 - 履歴閲覧UI

- バッチ一覧（取込日時・メモ・件数）
- バッチ選択→該当resultsの一覧表示

## ⬜ Phase 6 - CSV/Excel出力

- 検索結果、またはバッチ単位でのエクスポート

## ⬜ Phase 7 - バックアップ/復元

- DBファイルのタイムスタンプ付きコピー
- 復元時は現DBを退避してから置換

## ⬜ Phase 8 - チューニング（必要な場合のみ）

- Phase 3のベンチマークで目標未達の場合のみ、numpyインメモリインデックス方式へ切替

## ⬜ Phase 9 - exe化

- PyInstaller / `flet pack` でのビルド確認
- Windows単体実行ファイルとして配布可能な状態にする
