# テナントサポートチャットボット - バックエンド

## 必要条件
- Python 3.8以上
- pip（Pythonパッケージマネージャー）

## セットアップ手順

1. 必要なパッケージをインストール
```bash
pip install -r requirements.txt
```

2. 環境変数の設定
`.env`ファイルをbackendディレクトリに作成し、以下の内容を設定：
```
GOOGLE_API_KEY=your_gemini_api_key_here
```

## 実行方法

1. backendディレクトリに移動
```bash
cd tenant-chatbot/backend
```

2. サーバーを起動
```bash
python main.py
```

サーバーは`http://localhost:8082`で起動します。

## APIエンドポイント

- `POST /upload-knowledge`: ナレッジベースのアップロード
- `GET /knowledge-base`: 現在のナレッジベース情報を取得
- `POST /chat`: チャットメッセージの送信
- `GET /admin/chat-history`: チャット履歴の取得
- `GET /admin/analyze-chats`: チャット分析の取得