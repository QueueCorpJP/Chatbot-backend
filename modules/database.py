"""
データベースモジュール
データベース接続と初期化を管理します
"""

import psycopg2
import uuid
import datetime
from psycopg2.extras import RealDictCursor
from psycopg2.extensions import connection as Connection
# from fastapi import Depends
from .config import get_db_params
from .database_schema import SCHEMA, INITIAL_DATA

def get_db():
    """データベース接続を取得します"""
    conn = psycopg2.connect(**get_db_params(), cursor_factory=RealDictCursor)
    try:
        yield conn
    finally:
        conn.close()

def init_db():
    """データベースを初期化します"""
    conn = psycopg2.connect(**get_db_params())
    cursor = conn.cursor()
    
    # スキーマ定義からテーブルを作成
    for table_name, create_statement in SCHEMA.items():
        cursor.execute(create_statement)
        print(f"{table_name} テーブルを初期化しました")
    
    # 指定されたテーブル・カラムが存在するか確認
    def column_exists(table_name: str, column_name: str) -> bool:
        cursor.execute("""
            SELECT 1
            FROM information_schema.columns
            WHERE table_name = %s AND column_name = %s
        """, (table_name, column_name))
        return cursor.fetchone() is not None
    
    # chat_historyテーブルのカラムチェック
    if not column_exists("chat_history", "source_document"):
        print("source_document カラムを追加しています...")
        cursor.execute("ALTER TABLE chat_history ADD COLUMN source_document TEXT")

    if not column_exists("chat_history", "source_page"):
        print("source_page カラムを追加しています...")
        cursor.execute("ALTER TABLE chat_history ADD COLUMN source_page TEXT")

    # usersテーブルのカラムチェック
    if not column_exists("users", "company_id"):
        print("company_id カラムを追加しています...")
        cursor.execute("ALTER TABLE users ADD COLUMN company_id TEXT")
        cursor.execute("UPDATE users SET company_id = 'company_1' WHERE company_id IS NULL")

    # document_sourcesテーブルの存在チェック
    cursor.execute("""
        SELECT EXISTS (
            SELECT FROM information_schema.tables
            WHERE table_name = 'document_sources'
        )
    """)
    if cursor.fetchone()[0]:  # テーブルが存在する場合
        if not column_exists("document_sources", "company_id"):
            print("document_sources.company_id カラムを追加しています...")
            cursor.execute("ALTER TABLE document_sources ADD COLUMN company_id TEXT DEFAULT 'company_1'")

        if not column_exists("document_sources", "active"):
            print("document_sources.active カラムを追加しています...")
            cursor.execute("ALTER TABLE document_sources ADD COLUMN active BOOLEAN DEFAULT TRUE")

    # 初期データの挿入
    for data_name, insert_statement in INITIAL_DATA.items():
        cursor.execute(insert_statement)
        print(f"{data_name} 初期データを挿入しました")
    
    conn.commit()
    conn.close()

def check_user_exists(email: str, db: Connection) -> bool:
    """ユーザーが存在するか確認します"""
    cursor = db.cursor()
    cursor.execute("SELECT id FROM users WHERE email = %s", (email,))
    return cursor.fetchone() is not None

def create_company(name: str, db: Connection = None) -> str:
    """新しい会社を作成します"""
    should_close = False
    if db is None:
        db = psycopg2.connect(**get_db_params())
        should_close = True
    
    cursor = db.cursor()
    company_id = str(uuid.uuid4())
    created_at = datetime.datetime.now().isoformat()
    
    cursor.execute(
        "INSERT INTO companies (id, name, created_at) VALUES (%s, %s, %s)",
        (company_id, name, created_at)
    )
    
    db.commit()
    
    if should_close:
        db.close()
    
    return company_id

def get_company_by_id(company_id: str, db: Connection) -> dict:
    """会社IDから会社情報を取得します"""
    cursor = db.cursor(cursor_factory=RealDictCursor)
    cursor.execute("SELECT * FROM companies WHERE id = %s", (company_id,))
    company = cursor.fetchone()
    
    return company if company else None

def get_all_companies(db: Connection) -> list:
    """すべての会社を取得します"""
    cursor = db.cursor(cursor_factory=RealDictCursor)
    cursor.execute("SELECT * FROM companies ORDER BY created_at DESC")
    return cursor.fetchall()

def create_user(email: str, password: str, name: str, role: str = "user", company_id: str = None, db: Connection = None) -> str:
    """新しいユーザーを作成します"""
    should_close = False
    if db is None:
        db = psycopg2.connect(**get_db_params())
        should_close = True

    cursor = db.cursor()
    user_id = str(uuid.uuid4())
    created_at = datetime.datetime.now().isoformat()

    cursor.execute(
        """
        INSERT INTO users (id, email, password, name, role, company_id, created_at)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
        """,
        (user_id, email, password, name, role, company_id, created_at)
    )

    is_unlimited = True if role == "admin" else False
    cursor.execute(
        "INSERT INTO usage_limits (user_id, is_unlimited) VALUES (%s, %s)",
        (user_id, is_unlimited)
    )

    db.commit()

    if should_close:
        db.close()

    return user_id

def authenticate_user(email: str, password: str, db: Connection) -> dict:
    """ユーザー認証を行います"""
    cursor = db.cursor(cursor_factory=RealDictCursor)
    cursor.execute("""
        SELECT u.*, c.name AS company_name
        FROM users u
        LEFT JOIN companies c ON u.company_id = c.id
        WHERE u.email = %s AND u.password = %s
    """, (email, password))
    
    user = cursor.fetchone()
    return user if user else None

def get_users_by_company(company_id: str, db: Connection) -> list:
    """会社に所属するユーザーを取得します"""
    cursor = db.cursor(cursor_factory=RealDictCursor)
    cursor.execute(
        "SELECT * FROM users WHERE company_id = %s ORDER BY created_at DESC",
        (company_id,)
    )
    return cursor.fetchall()

def get_usage_limits(user_id: str, db: Connection) -> dict:
    """ユーザーの利用制限を取得します"""
    cursor = db.cursor(cursor_factory=RealDictCursor)
    cursor.execute("SELECT * FROM usage_limits WHERE user_id = %s", (user_id,))
    limits = cursor.fetchone()

    return limits if limits else None

def update_usage_count(user_id: str, field: str, db: Connection) -> dict:
    """利用カウントを更新します"""
    cursor = db.cursor(cursor_factory=RealDictCursor)

    # ⚠️ WARNING: Directly injecting `field` is risky — ensure it's validated!
    cursor.execute(
        f"UPDATE usage_limits SET {field} = {field} + 1 WHERE user_id = %s",
        (user_id,)
    )
    db.commit()

    cursor.execute("SELECT * FROM usage_limits WHERE user_id = %s", (user_id,))
    return cursor.fetchone()

def get_all_users(db: Connection) -> list:
    """すべてのユーザーを取得します"""
    cursor = db.cursor(cursor_factory=RealDictCursor)
    cursor.execute("""
        SELECT u.*, COALESCE(c.name, 'No Company') AS company_name
        FROM users u
        LEFT JOIN companies c ON u.company_id = c.id
        WHERE u.role != 'admin'
        ORDER BY u.created_at DESC
    """)
    return cursor.fetchall()

def get_demo_usage_stats(db: Connection, company_id: str = None) -> dict:
    """デモ利用状況の統計を取得します"""
    cursor = db.cursor(cursor_factory=RealDictCursor)

    # 会社IDが指定されている場合は、その会社のユーザーのみを対象にする
    company_filter = ""
    params = []

    if company_id:
        company_filter = "AND u.company_id = %s"
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
              AND ul.is_unlimited = FALSE
              AND u.company_id = %s
        """, (company_id,))
    else:
        cursor.execute("""
            SELECT COUNT(*) as count
            FROM usage_limits
            WHERE questions_used > 0
              AND is_unlimited = FALSE
        """)
    active_users = cursor.fetchone()['count']

    # ドキュメントアップロード数
    if company_id:
        cursor.execute("""
            SELECT COUNT(*) as count
            FROM document_sources
            WHERE company_id = %s
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
            WHERE u.company_id = %s
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
              AND ul.is_unlimited = FALSE
              AND u.company_id = %s
        """, (company_id,))
    else:
        cursor.execute("""
            SELECT COUNT(*) as count
            FROM usage_limits
            WHERE questions_used >= questions_limit
              AND is_unlimited = FALSE
        """)
    limit_reached_users = cursor.fetchone()['count']

    # 会社数（会社IDが指定されていない場合のみ）
    total_companies = 0
    if not company_id:
        cursor.execute("SELECT COUNT(*) as count FROM companies")
        total_companies = cursor.fetchone()['count']

    # 結果構築
    result = {
        "total_users": total_users,
        "active_users": active_users,
        "total_documents": total_documents,
        "total_questions": total_questions,
        "limit_reached_users": limit_reached_users
    }

    if not company_id:
        result["total_companies"] = total_companies

    return result

def update_company_id_by_email(company_id: str, user_email: str, db: Connection) -> bool:
    cursor = db.cursor()
    print(company_id)
    print(user_email)
    cursor.execute("UPDATE users SET company_id = %s WHERE email = %s", (company_id, user_email))
    db.commit()
    return cursor.rowcount > 0