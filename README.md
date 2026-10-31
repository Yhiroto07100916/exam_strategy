# Exam Strategy

高校受験向けの成績・模試・単元別理解度・志望校目標を管理するWebアプリです。

## 起動

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
uvicorn api.main:app --reload
```

ブラウザで http://127.0.0.1:8000 を開きます。API確認は `/api/health`。

## 機能

- ダッシュボード：最新模試、科目別得点率、目標との差
- 成績管理：科目別成績の登録・編集・削除
- 問題別管理：科目・単元・正誤・配点・獲得点の登録・編集・削除
- 単元別分析：配点が揃っている場合は得点率、そうでない場合は正答数ベースで集計
- 志望校・目標：科目別目標点と出典メモの保存
- 総合目標点の科目別配分：現在点・満点・学習優先度から科目別目標を計算し、満点に達した科目の余剰分を再配分
- 目標配分API：`POST /api/targets/allocate`（学校独自の公式配点や合格可能性を推定する機能ではありません）
- Excel / CSV一括取り込み（行ごとの入力エラー表示、重複検出、DB保存のトランザクション化）
- PDFテキスト抽出（画像PDFのOCRは未実装）
- Excelレポート出力
- SQLiteによるローカル保存（`data/exam_strategy.sqlite3`）

既存のCLIスクリプトは保持しています。`data/schools_template.json` は構造例であり、実在校の確定した選抜ルールではありません。学校別配点・合格最低点・合格可能性は年度や方式ごとの公式資料を確認してから扱ってください。
