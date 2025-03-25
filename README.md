# バックエンドアプリケーション

このディレクトリには、チャットボットアプリケーションのバックエンドコードが含まれています。

## 技術スタック

- **言語**: Python 3.9+
- **フレームワーク**: FastAPI
- **データベース**: SQLite
- **AI**: Google Gemini API

## ディレクトリ構造

```
backend/
├── modules/         # モジュール化されたコード
│   ├── __init__.py  # パッケージ初期化ファイル
│   ├── admin.py     # 管理画面関連の機能
│   ├── chat.py      # チャット処理関連の機能
│   ├── company.py   # 会社名管理関連の機能
│   ├── config.py    # アプリケーション設定
│   ├── database.py  # データベース接続と操作
│   ├── knowledge_base.py # 知識ベース管理
│   └── models.py    # データモデル定義
├── .env             # 環境変数設定ファイル
├── chatbot.db       # SQLiteデータベースファイル
├── main.py          # メインアプリケーションエントリーポイント
├── Procfile         # デプロイ用設定ファイル
└── README.md        # このファイル
```

## 環境変数

バックエンドアプリケーションは以下の環境変数を使用します：

- `GOOGLE_API_KEY`: Google Gemini APIのAPIキー
- `PORT`: サーバーのポート番号（デフォルト: 8083）
- `COMPANY_NAME`: 会社名（デフォルト: "ワンスアラウンド"）

これらの環境変数は `.env` ファイルに設定することができます。

## モジュール説明

### config.py

アプリケーション全体の設定を管理します。環境変数の読み込み、ロギング設定、Gemini API設定などを行います。

### database.py

データベース接続と初期化を管理します。SQLiteデータベースの設定とテーブル作成を行います。

### models.py

APIで使用するPydanticモデルを定義します。リクエスト/レスポンスの型を定義します。

### knowledge_base.py

知識ベースの管理と処理を行います。URLやファイルからのデータ抽出、保存を担当します。

### chat.py

チャット機能とAI応答生成を管理します。Gemini APIを使用した応答生成を行います。

### admin.py

管理画面で使用する機能を提供します。チャット履歴の分析や社員利用状況の取得を行います。

### company.py

会社名の管理と設定を行います。環境変数と.envファイルの更新を担当します。

## API エンドポイント

### チャット関連

- `POST /api/chat`: チャットメッセージを送信し、AIからの応答を取得
- `GET /api/knowledge-base`: 現在の知識ベース情報を取得
- `POST /api/upload-knowledge`: ファイルをアップロードして知識ベースを更新
- `POST /api/submit-url`: URLを送信して知識ベースを更新

### 管理画面関連

- `GET /api/admin/chat-history`: チャット履歴を取得
- `GET /api/admin/analyze-chats`: チャット履歴を分析
- `GET /api/admin/employee-details/{employee_id}`: 特定の社員の詳細情報を取得
- `GET /api/admin/employee-usage`: 社員ごとの利用状況を取得

### 会社設定関連

- `GET /api/company-name`: 現在の会社名を取得
- `POST /api/company-name`: 会社名を設定

## 起動方法

```bash
# 依存関係のインストール
pip install -r requirements.txt

# アプリケーションの起動
python backend/main.py
```

サーバーは `http://localhost:8083` で起動します。