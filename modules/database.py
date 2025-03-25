"""
データベースモジュール
データベース接続と初期化を管理します
"""
import sqlite3
import uuid
import datetime
from sqlite3 import Connection
from fastapi import Depends
from .config import get_db_path
from .database_schema import SCHEMA, INITIAL_DATA

def get_db():
    """データベース接続を取得します"""
    conn = sqlite3.connect(get_db_path(), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()

def init_db():
    """データベースを初期化します"""
    conn = sqlite3.connect(get_db_path())
    cursor = conn.cursor()
    
    # スキーマ定義からテーブルを作成
    for table_name, create_statement in SCHEMA.items():
        cursor.execute(create_statement)
        print(f"{table_name} テーブルを初期化しました")
    
    # 既存のテーブルに必要なカラムが存在するか確認し、なければ追加
    
    # chat_historyテーブルのカラムチェック
    cursor.execute("PRAGMA table_info(chat_history)")
    chat_columns = [column[1] for column in cursor.fetchall()]
    
    if 'source_document' not in chat_columns:
        print("source_document カラムを追加しています...")
        cursor.execute("ALTER TABLE chat_history ADD COLUMN source_document TEXT")
    
    if 'source_page' not in chat_columns:
        print("source_page カラムを追加しています...")
        cursor.execute("ALTER TABLE chat_history ADD COLUMN source_page TEXT")
    
    # usersテーブルのカラムチェック
    cursor.execute("PRAGMA table_info(users)")
    users_columns = [column[1] for column in cursor.fetchall()]
    
    if 'company_id' not in users_columns:
        print("company_id カラムを追加しています...")
        cursor.execute("ALTER TABLE users ADD COLUMN company_id TEXT")
        # デフォルト会社IDを設定
        cursor.execute("UPDATE users SET company_id = 'company_1' WHERE company_id IS NULL")
    
    # document_sourcesテーブルのカラムチェック
    cursor.execute("PRAGMA table_info(document_sources)")
    if cursor.fetchall():  # テーブルが存在する場合
        doc_columns = [column[1] for column in cursor.execute("PRAGMA table_info(document_sources)").fetchall()]
        
        if 'company_id' not in doc_columns:
            print("document_sources.company_id カラムを追加しています...")
            cursor.execute("ALTER TABLE document_sources ADD COLUMN company_id TEXT DEFAULT 'company_1'")
        
        if 'active' not in doc_columns:
            print("document_sources.active カラムを追加しています...")
            cursor.execute("ALTER TABLE document_sources ADD COLUMN active BOOLEAN DEFAULT 1")
    
    # 初期データの挿入
    for data_name, insert_statement in INITIAL_DATA.items():
        cursor.execute(insert_statement)
        print(f"{data_name} 初期データを挿入しました")
    
    conn.commit()
    conn.close()

def check_user_exists(email: str, db: Connection) -> bool:
    """ユーザーが存在するか確認します"""
    cursor = db.cursor()
    cursor.execute("SELECT id FROM users WHERE email = ?", (email,))
    return cursor.fetchone() is not None

def create_company(name: str, db: Connection = None) -> str:
    """新しい会社を作成します"""
    should_close = False
    if db is None:
        db = sqlite3.connect(get_db_path())
        should_close = True
    
    cursor = db.cursor()
    company_id = str(uuid.uuid4())
    created_at = datetime.datetime.now().isoformat()
    
    cursor.execute(
        "INSERT INTO companies (id, name, created_at) VALUES (?, ?, ?)",
        (company_id, name, created_at)
    )
    
    db.commit()
    
    if should_close:
        db.close()
    
    return company_id

def get_company_by_id(company_id: str, db: Connection) -> dict:
    """会社IDから会社情報を取得します"""
    cursor = db.cursor()
    cursor.execute("SELECT * FROM companies WHERE id = ?", (company_id,))
    company = cursor.fetchone()
    
    if company:
        return dict(company)
    return None

def get_all_companies(db: Connection) -> list:
    """すべての会社を取得します"""
    cursor = db.cursor()
    cursor.execute("SELECT * FROM companies ORDER BY created_at DESC")
    return [dict(row) for row in cursor.fetchall()]

def create_user(email: str, password: str, name: str, role: str = "user", company_id: str = None, db: Connection = None) -> str:
    """新しいユーザーを作成します"""
    should_close = False
    if db is None:
        db = sqlite3.connect(get_db_path())
        should_close = True
    
    cursor = db.cursor()
    user_id = str(uuid.uuid4())
    created_at = datetime.datetime.now().isoformat()
    
    cursor.execute(
        "INSERT INTO users (id, email, password, name, role, company_id, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (user_id, email, password, name, role, company_id, created_at)
    )
    
    # 利用制限の設定
    is_unlimited = 1 if role == "admin" else 0
    cursor.execute(
        "INSERT INTO usage_limits (user_id, is_unlimited) VALUES (?, ?)",
        (user_id, is_unlimited)
    )
    
    db.commit()
    
    if should_close:
        db.close()
    
    return user_id
def authenticate_user(email: str, password: str, db: Connection) -> dict:
    """ユーザー認証を行います"""
    cursor = db.cursor()
    cursor.execute("""
        SELECT u.*, c.name as company_name
        FROM users u
        LEFT JOIN companies c ON u.company_id = c.id
        WHERE u.email = ? AND u.password = ?
    """, (email, password))
    user = cursor.fetchone()
    
    if user:
        return dict(user)
    return None

def get_users_by_company(company_id: str, db: Connection) -> list:
    """会社に所属するユーザーを取得します"""
    cursor = db.cursor()
    cursor.execute("SELECT * FROM users WHERE company_id = ? ORDER BY created_at DESC", (company_id,))
    return [dict(row) for row in cursor.fetchall()]
    return None

def get_usage_limits(user_id: str, db: Connection) -> dict:
    """ユーザーの利用制限を取得します"""
    cursor = db.cursor()
    cursor.execute("SELECT * FROM usage_limits WHERE user_id = ?", (user_id,))
    limits = cursor.fetchone()
    
    if limits:
        return dict(limits)
    return None

def update_usage_count(user_id: str, field: str, db: Connection) -> dict:
    """利用カウントを更新します"""
    cursor = db.cursor()
    cursor.execute(f"UPDATE usage_limits SET {field} = {field} + 1 WHERE user_id = ?", (user_id,))
    db.commit()
    
    cursor.execute("SELECT * FROM usage_limits WHERE user_id = ?", (user_id,))
    return dict(cursor.fetchone())

def get_all_users(db: Connection) -> list:
    """すべてのユーザーを取得します"""
    cursor = db.cursor()
    cursor.execute("""
        SELECT u.*, c.name as company_name
        FROM users u
        LEFT JOIN companies c ON u.company_id = c.id
        WHERE u.role != 'admin'
        ORDER BY u.created_at DESC
    """)
    return [dict(row) for row in cursor.fetchall()]

def get_demo_usage_stats(db: Connection, company_id: str = None) -> dict:
    """デモ利用状況の統計を取得します"""
    cursor = db.cursor()
    
    # 会社IDが指定されている場合は、その会社のユーザーのみを対象にする
    company_filter = ""
    params = []
    
    if company_id:
        company_filter = "AND u.company_id = ?"
        params.append(company_id)
    
    # 総ユーザー数
    cursor.execute(f"""
        SELECT COUNT(*) as count
        FROM users u
        WHERE u.role != 'admin' {company_filter}
    """, params)
    total_users = cursor.fetchone()['count']
    
    # アクティブユーザー数（質問を1回以上したユーザー）
    if company_id:
        cursor.execute("""
            SELECT COUNT(*) as count
            FROM usage_limits ul
            JOIN users u ON ul.user_id = u.id
            WHERE ul.questions_used > 0
            AND ul.is_unlimited = 0
            AND u.company_id = ?
        """, (company_id,))
    else:
        cursor.execute("""
            SELECT COUNT(*) as count
            FROM usage_limits
            WHERE questions_used > 0
            AND is_unlimited = 0
        """)
    active_users = cursor.fetchone()['count']
    
    # ドキュメントアップロード数
    if company_id:
        cursor.execute("""
            SELECT COUNT(*) as count
            FROM document_sources
            WHERE company_id = ?
        """, (company_id,))
    else:
        cursor.execute("SELECT COUNT(*) as count FROM document_sources")
    total_documents = cursor.fetchone()['count']
    
    # 質問総数
    if company_id:
        cursor.execute("""
            SELECT SUM(ul.questions_used) as count
            FROM usage_limits ul
            JOIN users u ON ul.user_id = u.id
            WHERE u.company_id = ?
        """, (company_id,))
    else:
        cursor.execute("SELECT SUM(questions_used) as count FROM usage_limits")
    total_questions = cursor.fetchone()['count'] or 0
    
    # 制限に達したユーザー数
    if company_id:
        cursor.execute("""
            SELECT COUNT(*) as count
            FROM usage_limits ul
            JOIN users u ON ul.user_id = u.id
            WHERE ul.questions_used >= ul.questions_limit
            AND ul.is_unlimited = 0
            AND u.company_id = ?
        """, (company_id,))
    else:
        cursor.execute("""
            SELECT COUNT(*) as count
            FROM usage_limits
            WHERE questions_used >= questions_limit
            AND is_unlimited = 0
        """)
    limit_reached_users = cursor.fetchone()['count']
    
    # 会社数（会社IDが指定されていない場合のみ）
    total_companies = 0
    if not company_id:
        cursor.execute("SELECT COUNT(*) as count FROM companies")
        total_companies = cursor.fetchone()['count']
    
    result = {
        "total_users": total_users,
        "active_users": active_users,
        "total_documents": total_documents,
        "total_questions": total_questions,
        "limit_reached_users": limit_reached_users
    }
    
    # 会社IDが指定されていない場合は会社数も含める
    if not company_id:
        result["total_companies"] = total_companies
    
    return result