# EXAM STRATEGY — 高校受験攻略システム

高校受験向けの個人学力分析ツールです。Excel / CSV / JSON / テキストPDFを読み込み、
科目別得点・平均・推移・単元別正答率・志望校目標との差を分析し、Excelレポートを出力します。

## セットアップ

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Windowsの場合は `.venv\\Scripts\\activate` を使用してください。

## 最初にテンプレートを作成

```bash
python exam_strategy.py template
```

`data/` に次のテンプレートが作られます。

- `scores_template.xlsx`：模試・定期考査などの科目別得点
- `questions_template.csv`：問題単位の正誤記録
- `target_template.json`：志望校の目標点・配点設定
- `profile_template.json`：受験プロフィール

テンプレートに実データを入力して保存してください。

## 分析を実行

```bash
python exam_strategy.py analyze --scores data/scores_template.xlsx --questions data/questions_template.csv --target data/target_template.json --profile data/profile_template.json
```

入力ファイルは省略できます。存在するデータだけで分析します。

PDFのテキスト抽出：

```bash
python exam_strategy.py extract-pdf 成績表.pdf --output data/pdf_text.txt
```

スキャン画像だけのPDFは文字抽出できません。OCRは初期版では自動実行せず、読み取った結果をテンプレートに転記してください。

## 入力データ仕様

### scores_template.xlsx / CSV

1行につき1回の試験・模試・科目の記録です。

| date | exam_name | exam_type | subject | score | max_score | deviation | rank | examinees |
|---|---|---|---|---:|---:|---:|---:|---:|

- `date`: YYYY-MM-DD
- `exam_type`: 模試 / 定期考査 / 過去問 / その他
- `deviation`, `rank`, `examinees`: 不明なら空欄
- 得点と満点は必須

### questions_template.csv

1行につき1問です。`correct` は `1` または `0`。

| date | exam_name | subject | unit | question_id | correct | points | earned_points |
|---|---|---|---|---|---:|---:|---:|

### target_template.json

志望校が公表している目標点・配点などを設定します。根拠のない合格最低点は入力しないでください。

## 注意

- 偏差値は模試主催者が算出した値がある場合のみ利用します。得点だけから異なる模試間の偏差値を推定しません。
- 合格可能性を断定するものではありません。目標点との差や成績推移を参考情報として表示します。
- 都道府県・入試年度・選抜方式により制度や配点が異なります。志望校データは公式資料で確認してください。


## 東京都立高校の調査書点・総合得点換算（令和9年度対応）

東京都教育委員会の令和9年度資料に基づく換算用モジュールを追加しました。

```bash
python tokyo_public.py
```

入力：
- `data/tokyo_public_template.xlsx` の「学力検査」シートに5教科の得点を入力
- 「調査書」シートに9教科の評定（1〜5）を入力
- `data/tokyo_public_config.json` の `selection_methods` を志望校の実施方式に合わせる

対応方式：
- `7:3`：5教科学力検査と調査書点の比率が7:3
- `6:4`：3教科学力検査と調査書点の比率が6:4
- `10:0`：5教科学力検査のみで算出
- 学校が7:3と10:0の両方で算出し高い方を採用する場合は `["7:3", "10:0"]`

5教科型の調査書点は、学力検査5教科の評定を1倍、実技4教科を2倍し、65点満点で換算します。3教科型は国数英を1倍、その他6教科を2倍し、75点満点で換算します。換算時の小数点以下は切り捨てます。

**重要：** 学校・学科・年度・選抜方式により扱いが異なります。必ず東京都教育委員会の当該年度「入学者選抜実施方法一覧」で対象校の方式を確認してください。私立高校はこの都立換算式を適用せず、学校ごとの募集要項に従います。


## 複数都県・公私立の志望校比較

対象地域は東京都・神奈川県・埼玉県・千葉県。公立・私立の両方を、学校・学科・年度・選抜方式ごとの設定で管理します。

```bash
python school_compare.py
```

設定ファイル：
- `data/schools_template.json`：学校ごとの選抜方式・配点・公式資料URL・確認状態
- `data/student_exam_template.json`：本人の得点・調査書データ
- `data/official_sources.json`：都県の公式入試情報ページ

### 学校ごとの換算ルール

`scoring_rule.components` に、入力キー・入力満点・換算後の配点を登録します。例の学校データは**構造を示す仮データ**で、実在校の入試方式ではありません。必ず公式資料に合わせて編集してください。

私立高校は学校・コース・推薦/一般・併願優遇等で条件が異なります。都県共通の式で自動推定せず、募集要項や学校公式資料を確認して登録します。

`verification_status` は `verified` / `needs_review` / `unverified` などで管理し、`verified_on` に確認日を記録してください。未確認データの比較結果を合格判定として扱わないでください。

### 令和9年度の公式資料

- 東京都公立：東京都教育委員会の令和9年度実施要綱・同細目
- 東京都私立：都内私立高校入学者選抜実施要項（学校ごとに変更の可能性あり）
- 神奈川県公立：神奈川県教育委員会の令和9年度実施要領
- 埼玉県公立：埼玉県教育委員会の令和9年度入試情報・各校選抜実施内容
- 千葉県公立：千葉県教育委員会の令和9年度入学者選抜情報
- 神奈川・埼玉・千葉の私立：各学校の当該年度募集要項を個別登録

入試制度・配点は年度で変更されます。公式資料の更新を確認し、毎年度データを更新してください。


## 模試成績の一括取り込み・OCR（v0.4）

### Excel / CSVの成績を統合

列名は日本語（科目・得点・満点・偏差値など）または英語（subject・score・max_scoreなど）に対応します。

```bash
python mock_import.py import 模試成績.xlsx --name "Vもぎ 10月" --date 2026-10-25
```

取り込んだデータは `data/scores.csv` に追記・重複整理されます。既存データを残したまま統合します。

### PDF / 画像のOCR

macOSでは初回のみ日本語OCRエンジンをインストールします。

```bash
brew install tesseract tesseract-lang
```

```bash
python mock_import.py ocr 成績表.pdf
python mock_import.py ocr 成績表.jpg
```

`data/ocr/` にOCR全文テキストと、科目・得点候補をまとめた確認用CSVを出力します。PDFの文字が埋め込まれている場合でも、OCRコマンドではページを画像化して読み取ります。

**重要：** OCRは読み取り候補の作成までです。数字・科目・満点の誤認識を避けるため、CSVを人が確認してから成績データへ取り込んでください。模試会社ごとの帳票レイアウトに合わせた専用パーサーは、実際の帳票サンプルをもとに追加できます。

### OCR後の分析

OCR候補CSVを確認してから、必要な行を `data/scores.csv` に統合してください。分析は次のように実行します。

```bash
python exam_strategy.py analyze --scores data/scores.csv --target data/target_template.json --profile data/profile_template.json
```

`pytesseract` はPythonラッパーであり、別途Tesseract本体と日本語学習データが必要です。
