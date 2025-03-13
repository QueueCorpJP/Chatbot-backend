import os
import sys
from fastapi import FastAPI, UploadFile, File, HTTPException, Depends, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
import os.path
import google.generativeai as genai
from dotenv import load_dotenv
import pandas as pd
from typing import Dict, List, Optional, Any
from io import BytesIO
from datetime import datetime
import json
from pydantic import BaseModel
import sqlite3
# from sqlite3 import Connection
import uuid
import logging
import PyPDF2
import re
import sqlitecloud

# ロギングの設定
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger("shibuya-scramble-assistant")
logger.setLevel(logging.INFO)
logger.info("バックエンドサーバーを起動しています...")

# 環境変数の読み込み
load_dotenv()

# Gemini APIの設定
genai.configure(api_key=os.getenv("GOOGLE_API_KEY"))
model = genai.GenerativeModel('gemini-2.0-flash-exp')

app = FastAPI()
CONNECTION_STRING = "sqlitecloud://cmiyvod2nz.g6.sqlite.cloud:8860/chinook.sqlite?apikey=bL5cWc5vE4sMTyK0c50ezVrdYXkLbeQt2vArWr9tYrM"

def dict_factory(cursor, row):
    return {col[0]: row[idx] for idx, col in enumerate(cursor.description)}

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
    allow_origins=["*"],  # すべてのオリジンを許可
    allow_credentials=False,  # クレデンシャルを含むリクエストを許可しない
    allow_methods=["*"],
    allow_headers=["*"],
)

# データベース接続
def get_db():
    conn = sqlitecloud.connect(CONNECTION_STRING)
    # Set row_factory to sqlite3.Row to enable dict-like access to columns
    conn.row_factory = dict_factory
    try:
        yield conn
    finally:
        conn.close()

# データベース初期化
def init_db():
    conn = sqlitecloud.connect(CONNECTION_STRING)
    
    try:
        # Create chat_history table if it doesn't exist
        conn.execute('''
            CREATE TABLE IF NOT EXISTS chat_history (
                id TEXT PRIMARY KEY,
                user_message TEXT NOT NULL,
                bot_response TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                category TEXT,
                sentiment TEXT,
                employee_id TEXT,
                employee_name TEXT
            )
        ''')
        # Check if additional columns exist and add if necessary
        cursor = conn.execute("PRAGMA table_info(chat_history)")
        columns = [row[1] for row in cursor.fetchall()]
        if 'employee_id' not in columns:
            logger.info("employee_id カラムを追加しています...")
            conn.execute("ALTER TABLE chat_history ADD COLUMN employee_id TEXT")
        if 'employee_name' not in columns:
            logger.info("employee_name カラムを追加しています...")
            conn.execute("ALTER TABLE chat_history ADD COLUMN employee_name TEXT")
        conn.commit()
        logger.info("データベースを初期化しました。")
    except Exception as e:
        logger.error(f"データベース初期化エラー: {e}")
    finally:
        conn.close()

# アプリケーション起動時にデータベースを初期化
init_db()

# モデル定義
class ChatMessage(BaseModel):
    text: str
    employee_id: Optional[str] = None
    employee_name: Optional[str] = None

class ChatResponse(BaseModel):
    response: str

class ChatHistoryItem(BaseModel):
    id: str
    user_message: str
    bot_response: str
    timestamp: str
    category: Optional[str] = None
    sentiment: Optional[str] = None
    employee_id: Optional[str] = None
    employee_name: Optional[str] = None

class AnalysisResult(BaseModel):
    category_distribution: Dict[str, int]
    sentiment_distribution: Dict[str, int]
    common_questions: List[Dict[str, Any]]
    insights: str

class EmployeeUsageItem(BaseModel):
    employee_id: str
    employee_name: str
    message_count: int
    last_activity: str
    top_categories: List[Dict[str, Any]]
    recent_questions: List[str]

class EmployeeUsageResult(BaseModel):
    employee_usage: List[EmployeeUsageItem]

# 知識ベースの保存用
class KnowledgeBase:
    def __init__(self):
        self.data = None
        self.raw_text = ""
        self.columns = []

knowledge_base = KnowledgeBase()

@app.post("/api/upload-knowledge")
async def upload_knowledge(file: UploadFile = File(...)):
    """ファイルをアップロードして知識ベースを更新"""
    if not file.filename.endswith(('.xlsx', '.xls', '.pdf')):
        raise HTTPException(
            status_code=400,
            detail="無効なファイル形式です。ExcelファイルまたはPDFファイル（.xlsx、.xls、.pdf）のみ対応しています。"
        )

    try:
        print(f"ファイルアップロード開始: {file.filename}")
        contents = await file.read()
        if len(contents) == 0:
            print("エラー: 空のファイル")
            raise HTTPException(
                status_code=400,
                detail="ファイルが空です。有効なファイルをアップロードしてください。"
            )
    except Exception as e:
        print(f"ファイル読み込みエラー: {str(e)}")
        raise HTTPException(
            status_code=400,
            detail=f"ファイルの読み込みに失敗しました: {str(e)}"
        )

    try:
        # ファイル形式に応じた処理
        if file.filename.endswith(('.xlsx', '.xls')):
            # Excelファイルの処理
            print("Excelファイル読み込み開始")
            excel_file = pd.ExcelFile(BytesIO(contents))
            print(f"利用可能なシート: {excel_file.sheet_names}")
            
            # 全シートのデータを格納するリスト
            all_data = []
            sheet_contents = {}  # シートごとのテキストデータを保存
            
            # 処理するシート（順序を指定）
            target_sheets = ['表紙', '観光スポット', '交通案内', 'ショッピング', '飲食店',
                           'イベント情報', '周辺施設', 'お役立ち情報']
            
            # 各シートのデータを読み込む
            for sheet in target_sheets:
                if sheet not in excel_file.sheet_names:
                    continue
                    
                print(f"シート '{sheet}' を処理中...")
                
                try:
                    # シートのデータを読み込む
                    df_sheet = pd.read_excel(
                        BytesIO(contents),
                        sheet_name=sheet
                    )
                    
                    # 空の行と列を削除
                    df_sheet = df_sheet.dropna(how='all')
                    df_sheet = df_sheet.dropna(axis=1, how='all')
                    
                    if not df_sheet.empty:
                        # シート名を列として追加
                        df_sheet['section'] = sheet
                        all_data.append(df_sheet)
                        
                        # シートの内容をテキストとして保存
                        sheet_text = []
                        for idx, row in df_sheet.iterrows():
                            row_items = []
                            for col in df_sheet.columns:
                                if col != 'section' and pd.notna(row[col]) and str(row[col]).strip():
                                    row_items.append(f"{col}: {row[col]}")
                            if row_items:
                                sheet_text.append(" | ".join(row_items))
                        
                        if sheet_text:
                            sheet_contents[sheet] = sheet_text
                        
                        print(f"シート '{sheet}' から {len(df_sheet)} 行のデータを抽出")
                
                except Exception as e:
                    print(f"シート '{sheet}' の処理中にエラー: {str(e)}")
                    continue
            
            if not all_data:
                raise HTTPException(
                    status_code=400,
                    detail="どのシートからもデータを抽出できませんでした。"
                )
            
            # 全シートのデータを結合
            df = pd.concat(all_data, ignore_index=True)
            
            # 知識ベーステキストの生成
            formatted_text = []
            for sheet in target_sheets:
                if sheet in sheet_contents:
                    formatted_text.append(f"\n=== {sheet} ===")
                    formatted_text.extend(sheet_contents[sheet])
            
            # データを保存
            knowledge_base.data = df
            knowledge_base.columns = df.columns.tolist()
            knowledge_base.raw_text = "\n".join(formatted_text)
            
            print(f"データ抽出完了: 合計 {len(df)} 行")
            print(f"セクション: {list(sheet_contents.keys())}")
            
            # プレビューデータの作成
            preview_data = []
            for sheet in list(sheet_contents.keys())[:3]:  # 最初の3つのセクションのみ
                sheet_df = df[df['section'] == sheet].head(2)  # 各セクションから2行まで
                # NaN値を適切に処理
                sheet_df = sheet_df.fillna('')
                records = sheet_df.to_dict('records')
                # 空文字をNoneに変換
                records = [{k: (None if v == '' else v) for k, v in record.items()} for record in records]
                preview_data.extend(records)
            
        elif file.filename.endswith('.pdf'):
            # PDFファイルの処理
            print("PDFファイル読み込み開始")
            pdf_reader = PyPDF2.PdfReader(BytesIO(contents))
            
            # PDFからテキストを抽出
            pdf_text = []
            for page_num in range(len(pdf_reader.pages)):
                page = pdf_reader.pages[page_num]
                text = page.extract_text()
                if text:
                    pdf_text.append(f"=== ページ {page_num + 1} ===")
                    pdf_text.append(text)
            
            # セクションに分割（見出しを検出）
            sections = {}
            current_section = "一般情報"
            section_content = []
            
            # 見出しパターン（例: 「1. 観光スポット」や「第2章 交通案内」など）
            heading_pattern = r'^(?:\d+[\.\s]+|第\d+[章節]\s+|[\*\#]+\s+)?(観光|交通|ショッピング|飲食|イベント|施設|案内|情報|スポット)'
            
            for line in "\n".join(pdf_text).split("\n"):
                line = line.strip()
                if not line:
                    continue
                
                # 見出しかどうかを判定
                if re.search(heading_pattern, line, re.IGNORECASE):
                    # 前のセクションを保存
                    if section_content:
                        sections[current_section] = section_content
                    
                    # 新しいセクションを開始
                    current_section = line
                    section_content = []
                else:
                    section_content.append(line)
            
            # 最後のセクションを保存
            if section_content:
                sections[current_section] = section_content
            
            # データフレームを作成
            data = []
            for section, content in sections.items():
                data.append({
                    'section': section,
                    'content': "\n".join(content),
                    'source': 'PDF'
                })
            
            df = pd.DataFrame(data)
            
            # 知識ベーステキストの生成
            formatted_text = []
            for section, content in sections.items():
                formatted_text.append(f"\n=== {section} ===")
                formatted_text.extend(content)
            
            # データを保存
            knowledge_base.data = df
            knowledge_base.columns = df.columns.tolist()
            knowledge_base.raw_text = "\n".join(formatted_text)
            
            print(f"データ抽出完了: 合計 {len(df)} 行")
            print(f"セクション: {list(sections.keys())}")
            
            # プレビューデータの作成
            preview_data = df.head(5).to_dict('records')
            # NaN値を適切に処理
            preview_data = [{k: (None if pd.isna(v) else v) for k, v in record.items()} for record in preview_data]
        
        return {
            "message": "渋谷スクランブル情報が正常に更新されました",
            "columns": knowledge_base.columns,
            "preview": preview_data,
            "total_rows": len(df),
            "sections": list(sheet_contents.keys() if 'sheet_contents' in locals() else sections.keys())
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"ファイルのアップロード中にエラーが発生しました: {str(e)}"
        )

@app.get("/api/knowledge-base")
async def get_knowledge_base():
    """現在の知識ベースの情報を取得"""
    if knowledge_base.data is None:
        return {"message": "渋谷スクランブル情報が未設定です"}
    
    # プレビューデータの作成（NaN値を処理）
    preview_data = knowledge_base.data.head().to_dict('records')
    preview_data = [{k: (None if pd.isna(v) else v) for k, v in record.items()}
                   for record in preview_data]
    
    return {
        "columns": knowledge_base.columns,
        "preview": preview_data,
        "total_rows": len(knowledge_base.data)
    }

@app.post("/api/chat", response_model=ChatResponse)
async def chat(message: ChatMessage, db = Depends(get_db)):
    """チャットメッセージを処理してGeminiからの応答を返す"""
    try:
        if knowledge_base.data is None:
            response_text = "申し訳ございません。渋谷スクランブル情報が設定されていません。まずはExcelファイルをアップロードしてください。"
            
            # チャット履歴を保存
            chat_id = str(uuid.uuid4())
            cursor = db.cursor()
            cursor.execute(
                "INSERT INTO chat_history (id, user_message, bot_response, timestamp, category, sentiment, employee_id, employee_name) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (chat_id, message.text, response_text, datetime.now().isoformat(), "設定エラー", "neutral", message.employee_id, message.employee_name)
            )
            db.commit()
            
            return {"response": response_text}

        # プロンプトの作成
        prompt = f"""
        あなたは親切で丁寧な対応ができる渋谷スクランブルアシスタントです。
        以下の知識ベースを参考に、ユーザーの質問に対して可能な限り具体的で役立つ回答を提供してください。

        回答の際の注意点：
        1. 常に丁寧な言葉遣いを心がけ、ユーザーに対して敬意を持って接してください
        2. 知識ベースに情報がない場合でも、一般的な文脈で回答できる場合は適切に対応してください
        3. 具体的な情報が必要な場合は、どのような情報があれば回答できるかを説明してください
        4. 可能な限り具体的で実用的な情報を提供してください

        利用可能なデータ列：
        {', '.join(knowledge_base.columns)}

        知識ベース内容：
        {knowledge_base.raw_text}

        ユーザーの質問：
        {message.text}
        """

        # Geminiによる応答生成
        response = model.generate_content(prompt)
        response_text = response.text
        
        # カテゴリと感情を分析するプロンプト
        analysis_prompt = f"""
        以下のユーザーの質問を分析し、以下の情報を提供してください：
        1. カテゴリ: 質問のカテゴリを1つだけ選んでください（観光情報、交通案内、ショッピング、飲食店、イベント情報、その他）
        2. 感情: ユーザーの感情を1つだけ選んでください（ポジティブ、ネガティブ、ニュートラル）

        回答は以下のJSON形式で返してください：
        {{
            "category": "カテゴリ名",
            "sentiment": "感情"
        }}

        ユーザーの質問：
        {message.text}
        """
        
        # 分析の実行
        analysis_response = model.generate_content(analysis_prompt)
        analysis_text = analysis_response.text
        
        # JSON部分を抽出
        try:
            # JSONの部分を抽出（コードブロックの中身を取得）
            import re
            json_match = re.search(r'```json\s*(.*?)\s*```', analysis_text, re.DOTALL)
            if json_match:
                analysis_json = json.loads(json_match.group(1))
            else:
                # コードブロックがない場合は直接パース
                analysis_json = json.loads(analysis_text)
                
            category = analysis_json.get("category", "未分類")
            sentiment = analysis_json.get("sentiment", "neutral")
        except Exception as json_error:
            print(f"JSON解析エラー: {str(json_error)}")
            category = "未分類"
            sentiment = "neutral"
        
        # チャット履歴を保存
        chat_id = str(uuid.uuid4())
        cursor = db.cursor()
        cursor.execute(
            "INSERT INTO chat_history (id, user_message, bot_response, timestamp, category, sentiment, employee_id, employee_name) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (chat_id, message.text, response_text, datetime.now().isoformat(), category, sentiment, message.employee_id, message.employee_name)
        )
        db.commit()
        
        return {"response": response_text}
    except Exception as e:
        print(f"チャットエラー: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/admin/chat-history", response_model=List[ChatHistoryItem])
async def get_chat_history(db = Depends(get_db)):
    """チャット履歴を取得する"""
    print("チャット履歴取得APIが呼び出されました")
    try:
        cursor = db.cursor()
        cursor.execute("SELECT * FROM chat_history ORDER BY timestamp DESC")
        rows = cursor.fetchall()
        
        print(f"チャット履歴取得結果: {len(rows)}件")
        
        # SQLite Rowオブジェクトを辞書に変換
        chat_history = []
        for row in rows:
            item = {
                "id": row["id"],
                "user_message": row["user_message"],
                "bot_response": row["bot_response"],
                "timestamp": row["timestamp"],
                "category": row["category"],
                "sentiment": row["sentiment"],
                "employee_id": row["employee_id"],
                "employee_name": row["employee_name"]
            }
            chat_history.append(item)
        
        print(f"チャット履歴変換結果: {len(chat_history)}件")
        return chat_history
    except Exception as e:
        print(f"チャット履歴取得エラー: {str(e)}")
        import traceback
        print(traceback.format_exc())
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/admin/analyze-chats", response_model=AnalysisResult)
async def analyze_chats(db = Depends(get_db)):
    """チャット履歴を分析する"""
    try:
        cursor = db.cursor()
        
        # 全チャット履歴を取得
        cursor.execute("SELECT * FROM chat_history ORDER BY timestamp DESC")
        rows = cursor.fetchall()
        
        if not rows:
            return {
                "category_distribution": {},
                "sentiment_distribution": {},
                "common_questions": [],
                "insights": "チャット履歴がありません。"
            }
        
        # チャット履歴をリストに変換
        chat_history = []
        for row in rows:
            chat_history.append({
                "id": row["id"],
                "user_message": row["user_message"],
                "bot_response": row["bot_response"],
                "timestamp": row["timestamp"],
                "category": row["category"],
                "sentiment": row["sentiment"]
            })
        
        # カテゴリ分布の集計
        category_distribution = {}
        for chat in chat_history:
            category = chat["category"] or "未分類"
            if category in category_distribution:
                category_distribution[category] += 1
            else:
                category_distribution[category] = 1
        
        # 感情分布の集計
        sentiment_distribution = {}
        for chat in chat_history:
            sentiment = chat["sentiment"] or "neutral"
            if sentiment in sentiment_distribution:
                sentiment_distribution[sentiment] += 1
            else:
                sentiment_distribution[sentiment] = 1
        
        # よくある質問の抽出（単純な頻度ベース）
        question_counts = {}
        for chat in chat_history:
            question = chat["user_message"]
            if question in question_counts:
                question_counts[question] += 1
            else:
                question_counts[question] = 1
        
        # 頻度順に並べ替えて上位5件を取得
        common_questions = []
        for question, count in sorted(question_counts.items(), key=lambda x: x[1], reverse=True)[:5]:
            common_questions.append({
                "question": question,
                "count": count
            })
        
        # Gemini APIを使用して深い分析を行う
        analysis_prompt = f"""
        以下のチャットデータを分析し、ユーザーからの質問傾向や改善点について洞察を提供してください。
        データ形式は以下の通りです：
        
        カテゴリ分布:
        {json.dumps(category_distribution, ensure_ascii=False, indent=2)}
        
        感情分布:
        {json.dumps(sentiment_distribution, ensure_ascii=False, indent=2)}
        
        よくある質問（上位5件）:
        {json.dumps(common_questions, ensure_ascii=False, indent=2)}
        
        分析結果は以下の点を含めてください：
        1. 最も多い質問カテゴリとその理由の考察
        2. ユーザーの感情傾向とその背景
        3. よくある質問から見えるユーザーの関心事や懸念点
        4. 知識ベースやサポート体制の改善提案
        
        回答は400字程度の日本語でお願いします。
        """
        
        # Gemini APIによる分析
        analysis_response = model.generate_content(analysis_prompt)
        insights = analysis_response.text
        
        return {
            "category_distribution": category_distribution,
            "sentiment_distribution": sentiment_distribution,
            "common_questions": common_questions,
            "insights": insights
        }
    except Exception as e:
        print(f"チャット分析エラー: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/admin/employee-details/{employee_id}", response_model=List[ChatHistoryItem])
async def get_employee_details(employee_id: str, db = Depends(get_db)):
    """特定の社員の詳細なチャット履歴を取得する"""
    try:
        cursor = db.cursor()
        
        # 'anonymous'の場合はNULLとして検索
        if employee_id == 'anonymous':
            cursor.execute("""
            SELECT * FROM chat_history
            WHERE employee_id IS NULL
            ORDER BY timestamp DESC
            """)
        else:
            cursor.execute("""
            SELECT * FROM chat_history
            WHERE employee_id = ?
            ORDER BY timestamp DESC
            """, (employee_id,))
        
        rows = cursor.fetchall()
        
        # SQLite Rowオブジェクトを辞書に変換
        chat_history = []
        for row in rows:
            chat_history.append({
                "id": row["id"],
                "user_message": row["user_message"],
                "bot_response": row["bot_response"],
                "timestamp": row["timestamp"],
                "category": row["category"],
                "sentiment": row["sentiment"],
                "employee_id": row["employee_id"],
                "employee_name": row["employee_name"]
            })
        
        return chat_history
    except Exception as e:
        print(f"社員詳細取得エラー: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/admin/employee-usage", response_model=EmployeeUsageResult)
async def get_employee_usage(db = Depends(get_db)):
    """社員ごとの利用状況を取得する"""
    try:
        cursor = db.cursor()
        
        # 社員ごとのデータを取得（employee_idがNULLの場合は'anonymous'として扱う）
        cursor.execute("""
        SELECT
            COALESCE(employee_id, 'anonymous') as employee_id,
            COALESCE(employee_name, '匿名ユーザー') as employee_name,
            COUNT(*) as message_count,
            MAX(timestamp) as last_activity,
            GROUP_CONCAT(category, ',') as categories
        FROM chat_history
        GROUP BY COALESCE(employee_id, 'anonymous'), COALESCE(employee_name, '匿名ユーザー')
        ORDER BY message_count DESC
        """)
        
        employee_rows = cursor.fetchall()
        
        if not employee_rows:
            return {"employee_usage": []}
        
        employee_usage = []
        
        for row in employee_rows:
            employee_id = row["employee_id"]
            employee_name = row["employee_name"]
            
            # 社員IDが'anonymous'の場合もデータを表示する
                
            # 社員ごとのカテゴリ分布を計算
            categories = row["categories"].split(',') if row["categories"] else []
            category_counts = {}
            
            for category in categories:
                if category:
                    if category in category_counts:
                        category_counts[category] += 1
                    else:
                        category_counts[category] = 1
            
            # 上位カテゴリを取得
            top_categories = []
            for category, count in sorted(category_counts.items(), key=lambda x: x[1], reverse=True)[:3]:
                top_categories.append({
                    "category": category,
                    "count": count
                })
            
            # 最近の質問を取得（employee_idが'anonymous'の場合はNULLとして検索）
            if employee_id == 'anonymous':
                cursor.execute("""
                SELECT user_message
                FROM chat_history
                WHERE employee_id IS NULL
                ORDER BY timestamp DESC
                LIMIT 3
                """)
            else:
                cursor.execute("""
                SELECT user_message
                FROM chat_history
                WHERE employee_id = ?
                ORDER BY timestamp DESC
                LIMIT 3
                """, (employee_id,))
            
            recent_questions = [q["user_message"] for q in cursor.fetchall()]
            
            employee_usage.append({
                "employee_id": employee_id,
                "employee_name": employee_name or "名前なし",
                "message_count": row["message_count"],
                "last_activity": row["last_activity"],
                "top_categories": top_categories,
                "recent_questions": recent_questions
            })
        
        return {"employee_usage": employee_usage}
    except Exception as e:
        print(f"社員利用状況取得エラー: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

# 静的ファイルのマウント
# フロントエンドのビルドディレクトリを指定
frontend_build_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")

# 静的ファイルを提供するためのルートを追加
@app.get("/", include_in_schema=False)
async def read_root():
    index_path = os.path.join(frontend_build_dir, "index.html")
    if os.path.exists(index_path):
        return FileResponse(index_path)
    return {"message": "Welcome to Tenant Chatbot API"}

# 静的ファイルをマウント
if os.path.exists(os.path.join(frontend_build_dir, "assets")):
    app.mount("/assets", StaticFiles(directory=os.path.join(frontend_build_dir, "assets")), name="assets")

# その他のルートパスをindex.htmlにリダイレクト（SPAのルーティング用）
@app.get("/{full_path:path}", include_in_schema=False)
async def catch_all(full_path: str):
    print(f"catch_all handler called with path: {full_path}")
    
    # APIエンドポイントはスキップ（/apiで始まるパスはAPIエンドポイントとして処理）
    # 注意: このハンドラーはAPIエンドポイントよりも優先度が低いため、
    # 明示的に定義されたAPIエンドポイントは正しく処理されるはずです
    
    # index.htmlを返す
    index_path = os.path.join(frontend_build_dir, "index.html")
    if os.path.exists(index_path):
        return FileResponse(index_path)
    raise HTTPException(status_code=404, detail="Not Found")

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8083))  # 環境変数PORTがない場合は8083を使用
    uvicorn.run(app, host="0.0.0.0", port=port)