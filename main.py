"""
メインアプリケーションファイル
FastAPIアプリケーションの設定とルーティングを行います
main.py
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
from psycopg2.extensions import connection as Connection
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
    get_company_employees, set_model as set_admin_model, delete_resource
)
from modules.company import get_company_name, set_company_name
from modules.auth import get_current_user, get_current_admin, register_new_user, get_admin_or_user, get_company_admin
from modules.resource import get_uploaded_resources_by_company_id, toggle_resource_active_by_id, remove_resource_by_id
import json

# ロギングの設定
logger = setup_logging()

# Gemini APIの設定
model = setup_gemini()

# モデルの設定
set_chat_model(model)
set_admin_model(model)

# FastAPIアプリケーションの作成
app = FastAPI()

origins = [
    "*",
    "http://localhost",
    "http://localhost:3000",  # if you're testing locally
    "https://chatbot-frontend-gztk.vercel.app/",  # replace with your frontend domain
    "https://chatbot-frontend-gztk-git-main-queuecorp-jps-projects.vercel.app/",  # replace with your frontend domain
    "https://chatbot-frontend-gztk-6ej6x79vu-queuecorp-jps-projects.vercel.app/",  # replace with your frontend domain
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,  # or ["*"] for all
    allow_credentials=False,
    allow_methods=["*"],  # or ["GET", "POST", ...]
    allow_headers=["*"],  # or specific headers
)

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
        "company_name": user["company_name"] or "",
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
        cursor.execute("SELECT id FROM users WHERE email = %s", (user_data.email,))
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
                "company_name": "",
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
                "company_name": "",
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
    cursor.execute("SELECT * FROM users WHERE id = %s", (user_id,))
    user = cursor.fetchone()
    
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="指定されたユーザーが見つかりません"
        )
    
    # ユーザーの削除
    cursor.execute("DELETE FROM usage_limits WHERE user_id = %s", (user_id,))
    cursor.execute("DELETE FROM document_sources WHERE uploaded_by = %s", (user_id,))
    cursor.execute("DELETE FROM users WHERE id = %s", (user_id,))
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

# 詳細ビジネス分析エンドポイント
@app.post("/chatbot/api/admin/detailed-analysis")
async def admin_detailed_analysis(request: dict, current_user = Depends(get_admin_or_user), db: Connection = Depends(get_db)):
    """詳細なビジネス分析を行う"""
    try:
        # ユーザー情報の取得
        is_special_admin = current_user["email"] == "queue@queuefood.co.jp" and current_user.get("is_special_admin", False)
        
        # プロンプトを取得
        prompt = request.get("prompt", "")
        
        # 通常の分析結果を取得
        if is_special_admin:
            analysis_result = await analyze_chats(None, db)
        else:
            analysis_result = await analyze_chats(current_user["id"], db)
        
        # チャット履歴からのサンプルデータを取得（analysis_resultから取得可能）
        # カテゴリーとセンチメントの分布から洞察を生成
        categories = analysis_result.get("category_distribution", {})
        sentiments = analysis_result.get("sentiment_distribution", {})
        questions = analysis_result.get("common_questions", [])
        
        # Gemini APIで詳細な分析を実行
        from modules.admin import model
        
        analysis_prompt = f"""
        {prompt}
        
        # 分析データ
        
        ## カテゴリ分布:
        {json.dumps(categories, ensure_ascii=False, indent=2)}
        
        ## 感情分布:
        {json.dumps(sentiments, ensure_ascii=False, indent=2)}
        
        ## よくある質問（上位件）:
        {json.dumps(questions, ensure_ascii=False, indent=2)}
        
        ## 基本的な洞察:
        {analysis_result.get("insights", "")}
        """
        
        # Gemini APIによる詳細分析
        analysis_response = model.generate_content(analysis_prompt)
        detailed_analysis_text = analysis_response.text
        
        # 詳細分析の結果をセクションごとに分割して整形
        # 実際のプロンプトに合わせてセクション分割のルールを調整する必要があります
        import re
        
        # 各セクションのデータ
        detailed_analysis = {
            "detailed_topic_analysis": "",
            "efficiency_opportunities": "",
            "frustration_points": "",
            "improvement_suggestions": "",
            "communication_gaps": "",
            "specific_recommendations": ""
        }
        
        # テキスト全体から各セクションを抽出する簡易的な方法
        # より高度な抽出が必要な場合は、正規表現やセクション名の検索方法を調整してください
        sections = [
            ("頻出トピック", "detailed_topic_analysis"),
            ("業務効率化", "efficiency_opportunities"),
            ("フラストレーション", "frustration_points"),
            ("改善", "improvement_suggestions"),
            ("コミュニケーションギャップ", "communication_gaps"),
            ("具体的な改善提案", "specific_recommendations")
        ]
        
        # 正規表現を使ってセクションを検出
        current_section = None
        lines = detailed_analysis_text.split("\n")
        section_content = []
        
        for line in lines:
            matched = False
            for keyword, section_key in sections:
                if keyword in line and (line.startswith("#") or line.startswith("**") or line.endswith("**") or line.endswith(":")):
                    if current_section:
                        detailed_analysis[current_section] = "\n".join(section_content).strip()
                    current_section = section_key
                    section_content = []
                    matched = True
                    break
            
            if not matched and current_section:
                section_content.append(line)
        
        # 最後のセクションを処理
        if current_section and section_content:
            detailed_analysis[current_section] = "\n".join(section_content).strip()
        
        # 何もセクションに当てはまらなかった場合は、最初のキーに全テキストを入れる
        if all(value == "" for value in detailed_analysis.values()):
            detailed_analysis["detailed_topic_analysis"] = detailed_analysis_text
        
        return {
            "detailed_analysis": detailed_analysis
        }
        
    except Exception as e:
        import traceback
        print(f"詳細ビジネス分析エラー: {str(e)}")
        print(traceback.format_exc())
        raise HTTPException(status_code=500, detail=str(e))

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
        cursor.execute("SELECT company_id FROM users WHERE id = %s", (current_user["id"],))
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
async def admin_get_resources(current_user = Depends(get_admin_or_user), db: Connection = Depends(get_db)):
    """アップロードされたリソース（URL、PDF、Excel、TXT）の情報を取得する"""
    # return await get_uploaded_resources()
    is_special_admin = current_user["email"] == "queue@queuefood.co.jp" and current_user.get("is_special_admin", False)
    if is_special_admin:
        return await get_uploaded_resources_by_company_id(None, db)
    else:
        company_id = current_user["company_id"]
        print(await get_uploaded_resources_by_company_id(company_id, db))
        return await get_uploaded_resources_by_company_id(company_id, db)

# リソースのアクティブ状態を切り替えるエンドポイント
@app.post("/chatbot/api/admin/resources/{resource_id:path}/toggle", response_model=ResourceToggleResponse)
async def admin_toggle_resource(resource_id: str, current_user = Depends(get_admin_or_user), db: Connection = Depends(get_db)):
    """リソースのアクティブ状態を切り替える"""
    # URLデコード
    import urllib.parse
    decoded_id = urllib.parse.unquote(resource_id)
    print(f"トグルリクエスト: {resource_id} -> デコード後: {decoded_id}")
    return await toggle_resource_active_by_id(decoded_id, db)

# リソースを削除するエンドポイント
@app.delete("/chatbot/api/admin/resources/{resource_id:path}", response_model=dict)
async def admin_delete_resource(resource_id: str, current_user = Depends(get_admin_or_user), db: Connection = Depends(get_db)):
    """リソースを削除する"""
    # URLデコード
    import urllib.parse
    decoded_id = urllib.parse.unquote(resource_id)
    print(f"削除リクエスト: {resource_id} -> デコード後: {decoded_id}")
    # return await delete_resource(decoded_id)
    return await remove_resource_by_id(decoded_id, db)

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
    uvicorn.run(app, host="0.0.0.0", port=port, timeout_keep_alive=300)