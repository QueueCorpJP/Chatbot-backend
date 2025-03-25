"""
データベーススキーマ定義
アプリケーションで使用するデータベーステーブルを定義します
"""

# データベーステーブル定義
SCHEMA = {
    # 会社テーブル
    "companies": """
    CREATE TABLE IF NOT EXISTS companies (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        created_at TEXT NOT NULL
    )
    """,
    
    # ユーザーテーブル
    "users": """
    CREATE TABLE IF NOT EXISTS users (
        id TEXT PRIMARY KEY,
        email TEXT UNIQUE NOT NULL,
        password TEXT NOT NULL,
        name TEXT NOT NULL,
        role TEXT NOT NULL DEFAULT 'user',  -- 'admin', 'user', or 'employee'
        company_id TEXT,
        created_at TEXT NOT NULL,
        FOREIGN KEY (company_id) REFERENCES companies (id)
    )
    """,
    
    # 利用制限テーブル
    "usage_limits": """
    CREATE TABLE IF NOT EXISTS usage_limits (
        user_id TEXT PRIMARY KEY,
        document_uploads_used INTEGER NOT NULL DEFAULT 0,
        document_uploads_limit INTEGER NOT NULL DEFAULT 1,
        questions_used INTEGER NOT NULL DEFAULT 0,
        questions_limit INTEGER NOT NULL DEFAULT 5,
        is_unlimited BOOLEAN NOT NULL DEFAULT 0,
        FOREIGN KEY (user_id) REFERENCES users (id)
    )
    """,
    
    # ドキュメントソーステーブル
    "document_sources": """
    CREATE TABLE IF NOT EXISTS document_sources (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        type TEXT NOT NULL,
        page_count INTEGER,
        uploaded_by TEXT NOT NULL,
        company_id TEXT NOT NULL,
        uploaded_at TEXT NOT NULL,
        active BOOLEAN NOT NULL DEFAULT 1,
        FOREIGN KEY (uploaded_by) REFERENCES users (id),
        FOREIGN KEY (company_id) REFERENCES companies (id)
    )
    """,
    
    # チャット履歴テーブル (既存のテーブルを拡張)
    "chat_history": """
    CREATE TABLE IF NOT EXISTS chat_history (
        id TEXT PRIMARY KEY,
        user_message TEXT NOT NULL,
        bot_response TEXT NOT NULL,
        timestamp TEXT NOT NULL,
        category TEXT,
        sentiment TEXT,
        employee_id TEXT,
        employee_name TEXT,
        source_document TEXT,
        source_page TEXT
    )
    """
}

# 初期データ
INITIAL_DATA = {
    # デフォルト会社
    "default_company": """
    INSERT OR IGNORE INTO companies (id, name, created_at)
    VALUES ('company_1', 'ヘルプ', datetime('now'))
    """,
    
    # 管理者アカウント
    "admin_user": """
    INSERT OR IGNORE INTO users (id, email, password, name, role, company_id, created_at)
    VALUES ('admin', 'queue@queuefood.co.jp', 'QueueMainPass0401', '管理者', 'admin', 'company_1', datetime('now'))
    """,
    
    # 管理者の無制限設定
    "admin_unlimited": """
    INSERT OR IGNORE INTO usage_limits (user_id, is_unlimited)
    VALUES ('admin', 1)
    """
}