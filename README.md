# テナントサポートチャットボット - バックエンド

## 必要条件

- Python 3.8 以上
- pip（Python パッケージマネージャー）

## セットアップ手順

1. 必要なパッケージをインストール

```bash
pip install -r requirements.txt
```

2. 環境変数の設定
   `.env`ファイルを backend ディレクトリに作成し、以下の内容を設定：

```
GOOGLE_API_KEY=your_gemini_api_key_here
```

## 実行方法

1. backend ディレクトリに移動

```bash
cd tenant-chatbot/backend
```

2. サーバーを起動

```bash
python main.py
```

サーバーは`http://localhost:8082`で起動します。

## API エンドポイント

- `POST /upload-knowledge`: ナレッジベースのアップロード
- `GET /knowledge-base`: 現在のナレッジベース情報を取得
- `POST /chat`: チャットメッセージの送信
- `GET /admin/chat-history`: チャット履歴の取得
- `GET /admin/analyze-chats`: チャット分析の取得

# チャットボットバックエンドのデプロイガイド

このガイドでは、AWS EC2 インスタンス上に Nginx を使用してチャットボットバックエンドアプリケーションをデプロイする方法を説明します。

## 1. プロジェクトリポジトリのクローン

まず、EC2 インスタンスにリポジトリをクローンします：

```bash
git clone https://github.com/QueueCorpJP/Chatbot-backend.git
```

## 2. Python モジュールのインストール

プロジェクトディレクトリに移動し、必要な Python モジュールを pip でインストールします：

```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

## 3. chatbot-backend.service ファイルの作成

次に、バックエンドサービスを管理するための systemd サービスファイルを作成します。サービスファイルを編集します：

```bash
sudo nano /etc/systemd/system/chatbot-backend.service
```

以下の設定をサービスファイルに追加します：

```ini
[Unit]
Description=Chatbot Backend service
After=network.target

[Service]
User=ec2-user
WorkingDirectory=/home/ec2-user/Chatbot/Chatbot-backend
ExecStart=/home/ec2-user/Chatbot/Chatbot-backend/venv/bin/python main.py
Restart=always

[Install]
WantedBy=multi-user.target
```

## 4. サービスの開始と状態確認

サービスを有効にして開始し、正しく動作しているか確認します：

```bash
sudo systemctl start chatbot-backend
sudo systemctl status chatbot-backend

```

バックエンドサービスはポート 8083 で実行されます。

## 5. AWS EC2 でポート 8083 を開放

ポート 8083 でトラフィックを許可するために、このポートを AWS セキュリティグループで開放する必要があります。

1. **EC2 管理コンソールに移動。**.
2. **セキュリティグループに移動し、** EC2 インスタンスにアタッチされているセキュリティグループを選択。
3. **インバウンドルールを編集し、** ポート 8083 でトラフィックを許可する新しいルールを追加します：
   - **タイプ**: カスタム TCP ルール
   - **ポート範囲**: 8083
   - **ソース**: 0.0.0.0/0

## 6. Nginx 設定の更新

次に、バックエンドサービスへのリクエストをプロキシするために Nginx の設定を更新します。nginx.conf ファイルを開き、以下のブロックを追加します：

```bash
sudo nano /etc/nginx/nginx.conf

```

以下の設定をファイルに追加します：

```nginx
location /api/ {
    proxy_pass http://127.0.0.1:8083;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
}

```

## 7. Nginx のテストと再起動

最後に、Nginx 設定をテストし、サービスを再起動して変更を適用します：

```bash
sudo nginx -t
sudo systemctl restart nginx
```
