"""
会社名モジュール
会社名の管理と設定を行います
"""
import os
import logging
from fastapi import HTTPException, Depends
from psycopg2.extensions import connection as Connection
from .models import CompanyNameResponse, CompanyNameRequest
from .database import get_db, get_company_by_id

# デフォルト会社名（初期値は空）
DEFAULT_COMPANY_NAME = ""

logger = logging.getLogger(__name__)

# 起動時に環境変数からデフォルト会社名を読み込む
def init_company_name():
    """環境変数からデフォルト会社名を初期化する"""
    global DEFAULT_COMPANY_NAME
    env_company_name = os.getenv("COMPANY_NAME")
    if env_company_name:
        DEFAULT_COMPANY_NAME = env_company_name
        logger.info(f"環境変数からデフォルト会社名を読み込みました: {DEFAULT_COMPANY_NAME}")

# 初期化を実行
init_company_name()

async def get_company_name(user=None, db: Connection = Depends(get_db)):
    """
    会社名を取得する
    user: 現在のユーザー情報。指定されていない場合はデフォルト会社名を返す
    """
    # ユーザーが指定されていない場合はデフォルト会社名を返す
    if not user:
        return {"company_name": DEFAULT_COMPANY_NAME}
    
    # 特別な管理者の場合はデフォルト会社名を返す
    if user["email"] == "queue@queuefood.co.jp":
        return {"company_name": DEFAULT_COMPANY_NAME}
    
    # ユーザーの会社IDがある場合は、その会社の名前を返す
    if user.get("company_id"):
        company = get_company_by_id(user["company_id"], db)
        if company:
            return {"company_name": company["name"]}
    
    # 会社が見つからない場合はデフォルト会社名を返す
    return {"company_name": DEFAULT_COMPANY_NAME}

async def set_company_name(request: CompanyNameRequest, user=None, db: Connection = Depends(get_db)):
    """
    会社名を設定する
    request: 新しい会社名のリクエスト
    user: 現在のユーザー情報。指定されていない場合はデフォルト会社名を更新する
    """
    # 新しい会社名を取得
    new_company_name = request.company_name.strip()
    if not new_company_name:
        raise HTTPException(status_code=400, detail="会社名は空にできません")
    
    # 特別な管理者の場合はデフォルト会社名を更新する
    if not user or user["email"] == "queue@queuefood.co.jp":
        # グローバル変数を更新
        global DEFAULT_COMPANY_NAME
        DEFAULT_COMPANY_NAME = new_company_name
        logger.info(f"デフォルト会社名を「{new_company_name}」に更新しました")
        
        # 環境変数も更新（プロセス内のみ）
        os.environ["COMPANY_NAME"] = new_company_name
        
        # .envファイルの更新を試みる（オプション）
        try:
            # バックエンドディレクトリのパスを取得
            backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            env_path = os.path.join(backend_dir, ".env")
            
            # 既存の.envファイルを読み込む
            env_content = ""
            if os.path.exists(env_path):
                try:
                    with open(env_path, "r", encoding="utf-8") as f:
                        env_content = f.read()
                except Exception as read_error:
                    logger.warning(f".envファイルの読み込みに失敗しました: {str(read_error)}")
            
            # COMPANY_NAME行があるか確認
            if "COMPANY_NAME=" in env_content:
                # 既存の行を置き換え
                lines = env_content.split("\n")
                updated_lines = []
                for line in lines:
                    if line.startswith("COMPANY_NAME="):
                        updated_lines.append(f'COMPANY_NAME="{new_company_name}"')
                    else:
                        updated_lines.append(line)
                env_content = "\n".join(updated_lines)
            else:
                # 新しい行を追加
                if env_content and not env_content.endswith("\n"):
                    env_content += "\n"
                env_content += f'COMPANY_NAME="{new_company_name}"\n'
            
            # .envファイルに書き込む
            try:
                with open(env_path, "w", encoding="utf-8") as f:
                    f.write(env_content)
                logger.info(f".envファイルを更新しました: {env_path}")
            except Exception as write_error:
                logger.warning(f".envファイルの書き込みに失敗しました: {str(write_error)}")
        except Exception as e:
            logger.warning(f".envファイルの更新中にエラーが発生しました: {str(e)}")
    
    # ユーザーの会社IDがある場合は、その会社の名前を更新する
    elif user.get("company_id"):
        cursor = db.cursor()
        cursor.execute(
            "UPDATE companies SET name = %s WHERE id = %s",
            (new_company_name, user["company_id"])
        )
        db.commit()
        logger.info(f"会社ID {user['company_id']} の名前を「{new_company_name}」に更新しました")
    
    # 成功レスポンスを返す
    return {"company_name": new_company_name}