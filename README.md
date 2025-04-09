# チャットボットバックエンド

# ローカル開発セットアップ

## リポジトリのクローン

```git
git clone https://github.com/QueueCorpJP/Chatbot-backend.git
cd Chatbot-backend
```

## Python 依存関係のインストール

```bash
python -m venv venv

# macOS/Linuxの場合
source venv/bin/activate

# Windowsの場合
venv\Scripts\activate

# 必要な依存関係をインストール
pip install -r requirements.txt
playwright install  # 重要
```

## PostgreSQL のインストール

Ubuntu の場合:

```bash
sudo apt update
sudo apt install postgresql postgresql-contrib
```

macOS (Homebrew を使用):

```bash
brew install postgresql
```

Windows の場合: PostgreSQL 公式サイトから PostgreSQL をダウンロードしてインストールします。

## PostgreSQL データベースの設定

PostgreSQL をインストールした後、データベースとユーザーを作成する必要があります。

## .env ファイルの設定

プロジェクトのルートディレクトリに .env ファイルを作成し、以下の内容を追加します（プレースホルダーを実際の値に置き換えてください）：

```txt
GOOGLE_API_KEY=AI...7I
COMPANY_NAME="Queue"
WEBSHAREPROXY_USERNAME=xv...ll
WEBSHAREPROXY_PASSWORD=t6...rt
ASSEMBLYAI_API_KEY=12...7b
DB_NAME=chatbot
DB_USER=postgres
DB_PASSWORD=yourpassword
DB_HOST=localhost
DB_PORT=5432
```

## FastAPI アプリの実行

```bash
python main.py
```

サーバーは `http://localhost:8083` で起動します。

# AWS EC2 上で FastAPI + PostgreSQL アプリケーションを構築・デプロイする手順

# 1. AWS EC2 インスタンスの作成（Amazon Linux 2023 + g4dn.2xlarge）

## (1) AWS にログイン：

https://aws.amazon.com/console/ にアクセスしてログインします。

## (2) EC2 ダッシュボードへ移動：

「EC2」と検索し、ダッシュボードを開きます。

## (3) インスタンスの起動：

「インスタンスを起動」をクリックします。

## (4) Amazon マシンイメージ（AMI）を選択：

Amazon Linux 2023 を選択してください。

## (5) インスタンスタイプを選択：

g4dn.2xlarge を選択します（NVIDIA T4 GPU 搭載、GPU ベースのアプリに最適）。

## (6) キーペアを作成または選択：

SSH 接続用に既存のキーペアを選ぶか、新しく作成してください。

## (7) ストレージ設定：

必要に応じて EBS（SSD）のサイズを増やすことを推奨します（例：50GB〜100GB 以上）。

## (8) セキュリティグループ設定：

以下のポートを開放します：

- 22（SSH）

- 80（HTTP）

- 443（HTTPS）

- 8083（FastAPI のバックエンド）

## (9) インスタンスの起動と接続：

.pem ファイルを使って以下のように SSH 接続します：

```bash
chmod 400 your-key.pem
ssh -i "your-key.pem" ec2-user@your-ec2-ip
```

# 2. AWS EC2 インスタンスへの FastAPI + PostgreSQL アプリケーションのデプロイ手順

## (1) 初期セットアップ：

- PostgreSQL のインストール

```bash
sudo yum clean metadata
sudo yum install -y postgresql15 postgresql15-server
which postgresql-setup
sudo postgresql-setup --initdb
sudo systemctl enable postgresql
sudo systemctl start postgresql
sudo systemctl status postgresql
```

- データベースとユーザーの作成

```bash
sudo -i -u postgres
psql -U postgres -W
// set password
sudo -i -u postgres
psql
\password postgres
```

- 認証方式の設定を変更

```bash
sudo nano /var/lib/pgsql/data/pg_hba.conf
```

- "peer" and "ident" update to "md5"

- PostgreSQL を再起動

```bash
sudo systemctl restart postgresql
```

- 最新のコードをプル：

```git
git clone https://github.com/QueueCorpJP/Chatbot-backend.git
cd Chatbot-backend
```

- 仮想環境の作成：

```bash
python -m venv venv
source venv/bin/activate
```

- 依存パッケージのインストール：

```bash
pip install -r requirements.txt
playwright install
```

- .env ファイルの作成： 例：

```txt
GOOGLE_API_KEY=AI...7I
COMPANY_NAME="Queue"
WEBSHAREPROXY_USERNAME=xv...ll
WEBSHAREPROXY_PASSWORD=t6...rt
ASSEMBLYAI_API_KEY=12...7b
DB_NAME = chatbot
DB_USER = postgres
DB_PASSWORD = yourpassword
DB_HOST = localhost
DB_PORT = 5432
```

- FastAPI アプリの起動：

```bash
python main.py
```

## (2) リバースプロキシ設定（Nginx）：

- Nginx をインストール（未インストールの場合）：

```bash
sudo apt install nginx
```

- Nginx の設定を編集：

```bash
sudo nano /etc/nginx/nginx.conf
```

- 以下を追加または修正：

```nginx
server {
  ...
  location /chatbot/api/ {
    proxy_pass http://127.0.0.1:8083; # バックエンドサービス（ポート 8083）
    proxy_set_header Host $host; # オリジナルの Host ヘッダーを保持
    proxy_set_header X-Real-IP $remote_addr; # クライアントの IP アドレス
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for; # IP チェーンの保持
    proxy_set_header X-Forwarded-Proto $scheme; # 使用プロトコルの保持
  }
  ...
}
```

- Nginx を再起動：

```bash
sudo systemctl restart nginx
```

## (3) 起動手順

### systemd を使用する場合：sudo systemctl start chatbot-backend

### ※サービスが未設定の場合は、別途 chatbot-backend.service を /etc/systemd/system/ に作成してください。

## (4) メンテナンス手順

### 最新のコードを取得：git pull

### サービスを再起動：sudo systemctl restart chatbot-backend

### ログを確認：journalctl -u chatbot-backend -f
