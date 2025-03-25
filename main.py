"""
メインアプリケーションファイル
FastAPIアプリケーションの設定とルーティングを行います
"""
import os
import os.path
import datetime
from typing import List
from fastapi import FastAPI, UploadFile, File, HTTPException, Depends, Request, Form, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from sqlite3 import Connection

# モジュールのインポート
from modules.config import setup_logging, setup_gemini
from modules.company import DEFAULT_COMPANY_NAME
from modules.database import get_db, init_db, get_all_users, get_demo_usage_stats, create_user
from modules.models import (
    ChatMessage, ChatResponse, ChatHistoryItem, AnalysisResult,
    EmployeeUsageItem, EmployeeUsageResult, UrlSubmission,
    CompanyNameResponse, CompanyNameRequest, ResourcesResult,
    ResourceToggleResponse, UserLogin, UserRegister, UserResponse,
    UserWithLimits, DemoUsageStats, AdminUserCreate
)
from modules.knowledge_base import process_url, process_file, get_knowledge_base_info
from modules.chat import process_chat, set_model as set_chat_model
from modules.admin import (
    get_chat_history, analyze_chats, get_employee_details,
    get_employee_usage, get_uploaded_resources, toggle_resource_active,
    get_company_employees, set_model as set_admin_model
)
from modules.company import get_company_name, set_company_name
from modules.auth import get_current_user, get_current_admin, register_new_user, get_admin_or_user, get_company_admin

# ロギングの設定
logger = setup_logging()

# Gemini APIの設定
model = setup_gemini()

# モデルの設定
set_chat_model(model)
set_admin_model(model)

# FastAPIアプリケーションの作成
app = FastAPI()

# リクエストロギングミドルウェア
@app.middleware("http")
async def log_requests(request: Request, call_next):
    logger.info(f"Request: {request.method} {request.url.path}")
    try:
        response = await call_next(request)
        logger.info(f"Response: {response.status_code}")
        return response
    except Exception as e:
        logger.error(f"Request error: {str(e)}")
        raise

# CORSミドルウェアの設定
# 統合環境では、すべてのオリジンを許可する
app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://chatbot-frontend-nine-eta.vercel.app"],  # すべてのオリジンを許可
    allow_credentials=True,  # クレデンシャルを含むリクエストを許可
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)

# アプリケーション起動時にデータベースを初期化
init_db()

# 認証関連エンドポイント
@app.post("/chatbot/api/auth/login", response_model=UserWithLimits)
async def login(credentials: UserLogin, db: Connection = Depends(get_db)):
    """ユーザーログイン"""
    # 直接データベースから認証
    from modules.database import authenticate_user, get_usage_limits
    user = authenticate_user(credentials.email, credentials.password, db)
    
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="無効なメールアドレスまたはパスワードです",
        )
    
    # 利用制限情報を取得
    limits = get_usage_limits(user["id"], db)
    
    return {
        "id": user["id"],
        "email": user["email"],
        "name": user["name"],
        "role": user["role"],
        "created_at": user["created_at"],
        "usage_limits": {
            "document_uploads_used": limits["document_uploads_used"],
            "document_uploads_limit": limits["document_uploads_limit"],
            "questions_used": limits["questions_used"],
            "questions_limit": limits["questions_limit"],
            "is_unlimited": bool(limits["is_unlimited"])
        }
    }

@app.post("/chatbot/api/auth/register", response_model=UserResponse)
async def register(user_data: UserRegister, db: Connection = Depends(get_db)):
    """新規ユーザー登録"""
    try:
        # 管理者権限チェックは不要（デモ版では誰でも登録可能）
        return register_new_user(user_data.email, user_data.password, user_data.name, db)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"登録に失敗しました: {str(e)}"
        )

@app.post("/chatbot/api/admin/register-user", response_model=UserResponse)
async def admin_register_user(user_data: AdminUserCreate, current_user = Depends(get_admin_or_user), db: Connection = Depends(get_db)):
    """管理者による新規ユーザー登録"""
    try:
        # まず、メールアドレスが既に存在するかチェック
        cursor = db.cursor()
        cursor.execute("SELECT id FROM users WHERE email = ?", (user_data.email,))
        existing_user = cursor.fetchone()
        
        if existing_user:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="このメールアドレスは既に登録されています"
            )
        
        # 特別な管理者（queue@queuefood.co.jp）の場合はロールを指定できる
        if current_user["email"] == "queue@queuefood.co.jp" and current_user.get("is_special_admin", False):
            # user_dataからロールを取得（デフォルトは"employee"）
            role = user_data.role if hasattr(user_data, "role") and user_data.role in ["user", "employee"] else "employee"
            
            # create_user関数を直接呼び出す
            user_id = create_user(
                email=user_data.email,
                password=user_data.password,
                name=user_data.name,
                role=role,
                company_id=None,
                db=db
            )
            
            return {
                "id": user_id,
                "email": user_data.email,
                "name": user_data.name,
                "role": role,
                "created_at": datetime.datetime.now().isoformat()
            }
        else:
            # 通常のユーザーの場合は社員アカウントとして登録（管理画面にアクセスできない）
            # 現在のユーザーの会社IDを取得して新しいユーザーに設定
            company_id = current_user.get("company_id")
            
            # 会社IDがない場合はエラー
            if not company_id:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="会社IDが設定されていません。管理者にお問い合わせください。"
                )
            
            # create_user関数を直接呼び出して会社IDを設定
            user_id = create_user(
                email=user_data.email,
                password=user_data.password,
                name=user_data.name,
                role="employee",
                company_id=company_id,
                db=db
            )
            
            return {
                "id": user_id,
                "email": user_data.email,
                "name": user_data.name,
                "role": "employee",
                "created_at": datetime.datetime.now().isoformat()
            }
    except HTTPException as e:
        # HTTPExceptionはそのまま再送出
        print(f"社員アカウント作成エラー: {e.status_code}: {e.detail}")
        raise
    except Exception as e:
        print(f"社員アカウント作成エラー: {str(e)}")
        import traceback
        print(traceback.format_exc())
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"社員アカウント作成に失敗しました: {str(e)}"
        )

@app.delete("/chatbot/api/admin/delete-user/{user_id}", response_model=dict)
async def admin_delete_user(user_id: str, current_user = Depends(get_admin_or_user), db: Connection = Depends(get_db)):
    """管理者によるユーザー削除"""
    # 特別な管理者（queue@queuefood.co.jp）のみがユーザーを削除できる
    if current_user["email"] != "queue@queuefood.co.jp" or not current_user.get("is_special_admin", False):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="この操作には特別な管理者権限が必要です"
        )
    
    # 自分自身は削除できない
    if user_id == current_user["id"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="自分自身を削除することはできません"
        )
    
    # ユーザーの存在確認
    cursor = db.cursor()
    cursor.execute("SELECT * FROM users WHERE id = ?", (user_id,))
    user = cursor.fetchone()
    
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="指定されたユーザーが見つかりません"
        )
    
    # ユーザーの削除
    cursor.execute("DELETE FROM usage_limits WHERE user_id = ?", (user_id,))
    cursor.execute("DELETE FROM users WHERE id = ?", (user_id,))
    db.commit()
    
    return {"message": f"ユーザー {user['email']} を削除しました", "deleted_user_id": user_id}

@app.get("/chatbot/api/admin/users", response_model=List[UserResponse])
async def admin_get_users(current_user = Depends(get_admin_or_user), db: Connection = Depends(get_db)):
    """全ユーザー一覧を取得"""
    # 特別な管理者（queue@queuefood.co.jp）のみが全ユーザー一覧を取得できる
    if current_user["email"] != "queue@queuefood.co.jp" or not current_user.get("is_special_admin", False):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="この操作には特別な管理者権限が必要です"
        )
    return get_all_users(db)

@app.get("/chatbot/api/admin/demo-stats", response_model=DemoUsageStats)
async def admin_get_demo_stats(current_user = Depends(get_admin_or_user), db: Connection = Depends(get_db)):
    """デモ利用状況の統計を取得"""
    return get_demo_usage_stats(db)

# URLを送信するエンドポイント
@app.post("/chatbot/api/submit-url")
async def submit_url(submission: UrlSubmission, current_user = Depends(get_current_user), db: Connection = Depends(get_db)):
    """URLを送信して知識ベースを更新"""
    return await process_url(submission.url, current_user["id"], None, db)

# ファイルをアップロードするエンドポイント
@app.post("/chatbot/api/upload-knowledge")
async def upload_knowledge(file: UploadFile = File(...), current_user = Depends(get_current_user), db: Connection = Depends(get_db)):
    """ファイルをアップロードして知識ベースを更新"""
    return await process_file(file, current_user["id"], None, db)

# 知識ベース情報を取得するエンドポイント
@app.get("/chatbot/api/knowledge-base")
async def get_knowledge_base(current_user = Depends(get_current_user)):
    """現在の知識ベースの情報を取得"""
    return get_knowledge_base_info()

# チャットエンドポイント
@app.post("/chatbot/api/chat", response_model=ChatResponse)
async def chat(message: ChatMessage, current_user = Depends(get_current_user), db: Connection = Depends(get_db)):
    """チャットメッセージを処理してGeminiからの応答を返す"""
    # ユーザーIDを設定
    message.user_id = current_user["id"]
    message.employee_name = current_user["name"]
    
    return await process_chat(message, db)

# チャット履歴を取得するエンドポイント
@app.get("/chatbot/api/admin/chat-history", response_model=List[ChatHistoryItem])
async def admin_get_chat_history(current_user = Depends(get_admin_or_user), db: Connection = Depends(get_db)):
    """チャット履歴を取得する"""
    # 現在のユーザーIDを渡して、そのユーザーのデータのみを取得
    # 特別な管理者（queue@queuefood.co.jp）の場合は全ユーザーのデータを取得できるようにする
    if current_user["email"] == "queue@queuefood.co.jp" and current_user.get("is_special_admin", False):
        # 特別な管理者の場合は全ユーザーのデータを取得
        return await get_chat_history(None, db)
    else:
        # 通常のユーザーの場合は自分のデータのみを取得
        user_id = current_user["id"]
        return await get_chat_history(user_id, db)

# チャット分析エンドポイント
@app.get("/chatbot/api/admin/analyze-chats", response_model=AnalysisResult)
async def admin_analyze_chats(current_user = Depends(get_admin_or_user), db: Connection = Depends(get_db)):
    """チャット履歴を分析する"""
    # 特別な管理者（queue@queuefood.co.jp）の場合は全ユーザーのデータを分析できるようにする
    if current_user["email"] == "queue@queuefood.co.jp" and current_user.get("is_special_admin", False):
        # 特別な管理者の場合は全ユーザーのデータを分析
        return await analyze_chats(None, db)
    else:
        # 通常のユーザーの場合は自分のデータのみを分析
        user_id = current_user["id"]
        return await analyze_chats(user_id, db)

# 社員詳細情報を取得するエンドポイント
@app.get("/chatbot/api/admin/employee-details/{employee_id}", response_model=List[ChatHistoryItem])
async def admin_get_employee_details(employee_id: str, current_user = Depends(get_admin_or_user), db: Connection = Depends(get_db)):
    """特定の社員の詳細なチャット履歴を取得する"""
    # 特別な管理者（queue@queuefood.co.jp）の場合は全ユーザーのデータを取得できるようにする
    is_special_admin = current_user["email"] == "queue@queuefood.co.jp" and current_user.get("is_special_admin", False)
    
    # ユーザーIDを渡して権限チェックを行う
    return await get_employee_details(employee_id, db, current_user["id"])

# 会社の全社員情報を取得するエンドポイント
@app.get("/chatbot/api/admin/company-employees")
async def admin_get_company_employees(current_user = Depends(get_company_admin), db: Connection = Depends(get_db)):
    """会社の全社員情報を取得する"""
    # 特別な管理者（queue@queuefood.co.jp）の場合は全ユーザーのデータを取得できるようにする
    is_special_admin = current_user["email"] == "queue@queuefood.co.jp" and current_user.get("is_special_admin", False)
    
    # 直接get_company_employees関数に処理を委譲
    # 特別な管理者の場合はuser_idを渡すだけで関数内で判定
    if is_special_admin:
        # 特別な管理者の場合は全ユーザーのデータを取得
        return await get_company_employees(current_user["id"], db, None)
    else:
        # 通常のユーザーの場合は自分の会社の社員のデータのみを取得
        # ユーザーの会社IDを取得
        cursor = db.cursor()
        cursor.execute("SELECT company_id FROM users WHERE id = ?", (current_user["id"],))
        user_row = cursor.fetchone()
        company_id = user_row["company_id"] if user_row else None
        
        if not company_id:
            raise HTTPException(status_code=400, detail="会社IDが見つかりません")
        
        return await get_company_employees(current_user["id"], db, company_id)

# 社員利用状況を取得するエンドポイント
@app.get("/chatbot/api/admin/employee-usage", response_model=EmployeeUsageResult)
async def admin_get_employee_usage(current_user = Depends(get_company_admin), db: Connection = Depends(get_db)):
    """社員ごとの利用状況を取得する"""
    # 特別な管理者（queue@queuefood.co.jp）の場合は全ユーザーのデータを取得できるようにする
    is_special_admin = current_user["email"] == "queue@queuefood.co.jp" and current_user.get("is_special_admin", False)
    
    if is_special_admin:
        # 特別な管理者の場合は全ユーザーのデータを取得
        return await get_employee_usage(None, db, is_special_admin=True)
    else:
        # 通常のユーザーの場合は自分の会社の社員のデータのみを取得
        user_id = current_user["id"]
        return await get_employee_usage(user_id, db, is_special_admin=False)

# アップロードされたリソースを取得するエンドポイント
@app.get("/chatbot/api/admin/resources", response_model=ResourcesResult)
async def admin_get_resources(current_user = Depends(get_admin_or_user)):
    """アップロードされたリソース（URL、PDF、Excel、TXT）の情報を取得する"""
    return await get_uploaded_resources()

# リソースのアクティブ状態を切り替えるエンドポイント
@app.post("/chatbot/api/admin/resources/{resource_name}/toggle", response_model=ResourceToggleResponse)
async def admin_toggle_resource(resource_name: str, current_user = Depends(get_admin_or_user)):
    """リソースのアクティブ状態を切り替える"""
    return await toggle_resource_active(resource_name)

# 会社名を取得するエンドポイント
@app.get("/chatbot/api/company-name", response_model=CompanyNameResponse)
async def api_get_company_name(current_user = Depends(get_current_user), db: Connection = Depends(get_db)):
    """現在の会社名を取得する"""
    return await get_company_name(current_user, db)

# 会社名を設定するエンドポイント
@app.post("/chatbot/api/company-name", response_model=CompanyNameResponse)
async def api_set_company_name(request: CompanyNameRequest, current_user = Depends(get_current_user), db: Connection = Depends(get_db)):
    """会社名を設定する"""
    return await set_company_name(request, current_user, db)

# 静的ファイルのマウント
# フロントエンドのビルドディレクトリを指定
frontend_build_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")

# 静的ファイルを提供するためのルートを追加
@app.get("/", include_in_schema=False)
async def read_root():
    index_path = os.path.join(frontend_build_dir, "index.html")
    if os.path.exists(index_path):
        return FileResponse(index_path)
    return {"message": f"Welcome to {DEFAULT_COMPANY_NAME} Chatbot API"}

# 静的ファイルをマウント
if os.path.exists(os.path.join(frontend_build_dir, "assets")):
    app.mount("/assets", StaticFiles(directory=os.path.join(frontend_build_dir, "assets")), name="assets")

# その他のルートパスをindex.htmlにリダイレクト（SPAのルーティング用）
@app.get("/{full_path:path}", include_in_schema=False)
async def catch_all(full_path: str):
    print(f"catch_all handler called with path: {full_path}")
    
    # APIエンドポイントはスキップ（/apiで始まるパスはAPIエンドポイントとして処理）
    if full_path.startswith("api/"):
        # APIエンドポイントの場合は404を返す
        raise HTTPException(status_code=404, detail="API endpoint not found")
    
    # SPAルーティング用にindex.htmlを返す
    index_path = os.path.join(frontend_build_dir, "index.html")
    if os.path.exists(index_path):
        return FileResponse(index_path)
    raise HTTPException(status_code=404, detail="Not Found")

# アプリケーションの実行
if __name__ == "__main__":
    import uvicorn
    from modules.config import get_port
    port = get_port()
    uvicorn.run(app, host="0.0.0.0", port=port)