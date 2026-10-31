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
- 成績管理：科目別成績の登録・削除
- 志望校・目標：科目別目標点と出典メモの保存
- Excel / CSV一括取り込み
- PDFテキスト抽出（画像PDFのOCRは未実装）
- Excelレポート出力
- SQLiteによるローカル保存（`data/exam_strategy.sqlite3`）

既存のCLIスクリプトは保持しています。`data/schools_template.json` は構造例であり、実在校の確定した選抜ルールではありません。学校別配点・合格最低点・合格可能性は年度や方式ごとの公式資料を確認してから扱ってください。
