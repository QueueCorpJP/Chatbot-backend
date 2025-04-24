"""
知識ベースモジュール
知識ベースの管理と処理を行います
"""
import re
import pandas as pd
import requests
from bs4 import BeautifulSoup
import urllib.parse
import logging
from fastapi import HTTPException, UploadFile, File, Depends
from io import BytesIO
import PyPDF2
import io
import base64
import google.generativeai as genai
from PIL import Image
from .company import DEFAULT_COMPANY_NAME
from psycopg2.extensions import connection as Connection
from .database import get_db, update_usage_count
from .auth import check_usage_limits
import uuid
from pdf2image import convert_from_bytes 
from modules.config import setup_gemini
from .utils import transcribe_youtube_video, extract_text_from_html, _process_video_file, extract_text_from_pdf
import asyncio

logger = logging.getLogger(__name__)

import datetime
from datetime import datetime

model = setup_gemini()

# 知識ベースの保存用クラス
class KnowledgeBase:
    def __init__(self):
        self.data = None
        self.raw_text = ""
        self.columns = []
        self.sources = []  # ソース（ファイル名やURL）を保存するリスト
        self.url_data = []  # URLから取得したデータを保存するリスト
        self.url_texts = []  # URLから取得したテキストを保存するリスト
        self.file_data = []  # ファイルから取得したデータを保存するリスト
        self.file_texts = []  # ファイルから取得したテキストを保存するリスト
        self.images = []    # PDFから抽出した画像データを保存するリスト
        self.source_info = {}  # ソースの詳細情報（タイムスタンプ、アクティブ状態など）
        self.original_data = {}  # 各ソースの元のデータを保存する辞書 {source_name: {'df': dataframe, 'text': text}}
        self.company_sources = {}  # 会社ごとのソースを保存する辞書 {company_id: [source_name1, source_name2, ...]}
        
    def get_company_data(self, company_id):
        """会社IDに関連するデータを取得する"""
        if not company_id or company_id not in self.company_sources:
            return None, "", []
            
        company_sources = self.company_sources.get(company_id, [])
        if not company_sources:
            return None, "", []
            
        # 会社のソースに関連するデータを収集
        company_data = []
        company_text = ""
        company_columns = []
        
        for source in company_sources:
            if source in self.original_data:
                source_data = self.original_data[source]
                if 'df' in source_data and not source_data['df'].empty:
                    company_data.append(source_data['df'])
                if 'text' in source_data:
                    company_text += source_data['text'] + "\n\n"
        
        # データフレームを結合
        combined_df = None
        if company_data:
            combined_df = pd.concat(company_data, ignore_index=True)
            company_columns = combined_df.columns.tolist()
            
        return combined_df, company_text, company_columns

# グローバルインスタンス
knowledge_base = KnowledgeBase()

# URLからテキストを抽出する関数
async def extract_text_from_url(url: str) -> str:
    """URLからテキストコンテンツを抽出する"""
    try:
        # URLが有効かチェック
        if not url.startswith(('http://', 'https://')):
            url = 'https://' + url
        if 'youtube.com' in url or 'youtu.be' in url:
            return transcribe_youtube_video(url)
        elif url.lower().endswith('.pdf'):
            return await extract_text_from_pdf(url)
        else:
            return await extract_text_from_html(url)
    except Exception as e:
        print(f"URLからのテキスト抽出エラー: {str(e)}")
        return f"URLからのテキスト抽出エラー: {str(e)} ===\n"
# URLを処理する関数
async def process_url(url: str, user_id: str = None, company_id: str = None, db: Connection = None):
    """URLを処理して知識ベースを更新する"""
    try:
        # ユーザーIDからcompany_idとroleを取得（指定されていない場合）
        if user_id:
            cursor = db.cursor()
            cursor.execute("SELECT company_id, role FROM users WHERE id = %s", (user_id,))
            user = cursor.fetchone()
            
            # 社員アカウントはドキュメントをアップロードできない
            if user and user['role'] == 'employee':
                raise HTTPException(
                    status_code=403,
                    detail="社員アカウントはドキュメントをアップロードできません。管理者にお問い合わせください。"
                )
                
            if user and user['company_id'] and not company_id:
                company_id = user['company_id']
        
        # ユーザーIDがある場合は利用制限をチェック
        if user_id:
            # ドキュメントアップロードの利用制限をチェック
            limits_check = check_usage_limits(user_id, "document_upload", db)
            
            if not limits_check["is_unlimited"] and not limits_check["allowed"]:
                raise HTTPException(
                    status_code=403,
                    detail=f"申し訳ございません。デモ版のドキュメントアップロード制限（{limits_check['limit']}回）に達しました。"
                )
        
        # URLからテキストを抽出
        extracted_text = await extract_text_from_url(url)
        if extracted_text.startswith("URLからのテキスト抽出エラー:"):
            raise HTTPException(
                status_code=500,
                detail=extracted_text  # エラー詳細をそのまま返す
            )
        
        # テキストをセクションに分割
        sections = {}
        current_section = "メインコンテンツ"
        section_text = []
        
        for line in extracted_text.split('\n'):
            if line.startswith('=== ') and line.endswith(' ==='):
                # 新しいセクションの開始
                if section_text:
                    sections[current_section] = section_text
                    section_text = []
                current_section = line.strip('= ')
            else:
                section_text.append(line)
        
        # 最後のセクションを追加
        if section_text:
            sections[current_section] = section_text
        
        # データフレームを作成
        data = []
        for section_name, lines in sections.items():
            content = '\n'.join(lines)
            data.append({
                'section': section_name,
                'content': content,
                'source': 'URL',
                'url': url,
                'file': None  # ファイルフィールドを明示的に追加
            })
        
        df = pd.DataFrame(data)
        
        # 知識ベースを更新（URLデータとして保存）
        _update_knowledge_base(df, extracted_text, is_file=False, source_name=url, company_id=company_id)
        
        # ソースリストにURLを追加し、タイムスタンプと有効状態を記録
        if url not in knowledge_base.sources:
            knowledge_base.sources.append(url)
            # 現在のタイムスタンプを記録
            knowledge_base.source_info[url] = {
                'timestamp': datetime.now().isoformat(),
                'active': True  # デフォルトで有効
            }
        
        # 最新の会社名を取得
        from .company import DEFAULT_COMPANY_NAME as current_company_name
        
        # ユーザーIDがある場合はドキュメントアップロードカウントを更新

        # if user_id and not limits_check.get("is_unlimited", False):
        if user_id:
            updated_limits = update_usage_count(user_id, "document_uploads_used", db)
            
            # ドキュメントソースを記録
            document_id = str(uuid.uuid4())
            cursor = db.cursor()
            cursor.execute(
                "INSERT INTO document_sources (id, name, type, page_count, content, uploaded_by, company_id, uploaded_at, active) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
                (document_id, url, "URL", 1, extracted_text, user_id, company_id, datetime.now().isoformat(), True)
            )
            
            # 会社のソースリストに追加
            if company_id:
                if company_id not in knowledge_base.company_sources:
                    knowledge_base.company_sources[company_id] = []
                if url not in knowledge_base.company_sources[company_id]:
                    knowledge_base.company_sources[company_id].append(url)
            db.commit()
        
        # アクティブなソースを取得
        active_sources = get_active_resources()
        limits_check = check_usage_limits(user_id, "document_upload", db)
        return {
            "message": f"{current_company_name}の情報が正常に更新されました（URL: {url}）",
            "columns": knowledge_base.columns if knowledge_base.data is not None else [],
            "preview": df.head(5).to_dict('records') if not df.empty else [],
            "total_rows": len(df),
            "sections": list(sections.keys()),
            "url": url,
            "sources": knowledge_base.sources,
            "active_sources": active_sources,
            "remaining_uploads": limits_check.get("remaining", None) if user_id else None,
            "limit_reached": not limits_check.get("allowed", True) if user_id else False
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"URLの処理中にエラーが発生しました: {str(e)}"
        )

# ファイルを処理する関数
async def process_file(file: UploadFile = File(...), user_id: str = None, company_id: str = None, db: Connection = None):
    """ファイルを処理して知識ベースを更新する"""
    # ユーザーIDからcompany_idとroleを取得（指定されていない場合）
    if user_id:
        cursor = db.cursor()
        cursor.execute("SELECT company_id, role FROM users WHERE id = %s", (user_id,))
        user = cursor.fetchone()
        
        # 社員アカウントはドキュメントをアップロードできない
        if user and user['role'] == 'employee':
            raise HTTPException(
                status_code=403,
                detail="社員アカウントはドキュメントをアップロードできません。管理者にお問い合わせください。"
            )
            
        if user and user['company_id'] and not company_id:
            company_id = user['company_id']
    if not file.filename.endswith(('.xlsx', '.xls', '.pdf', '.txt', '.avi', '.mp4', '.webp')):
        raise HTTPException(
            status_code=400,
            detail="無効なファイル形式です。ExcelファイルまたはPDFファイル、テキストファイル（.xlsx、.xls、.pdf、.txt）のみ対応しています。"
        )

    try:
        # ユーザーIDがある場合は利用制限をチェック
        remaining_uploads = None
        limit_reached = False
        
        if user_id:
            # ドキュメントアップロードの利用制限をチェック
            limits_check = check_usage_limits(user_id, "document_upload", db)
            
            if not limits_check["is_unlimited"] and not limits_check["allowed"]:
                raise HTTPException(
                    status_code=403,
                    detail=f"申し訳ございません。デモ版のドキュメントアップロード制限（{limits_check['limit']}回）に達しました。"
                )
            
            # 無制限でない場合は残り回数を計算
            if not limits_check["is_unlimited"]:
                remaining_uploads = limits_check["remaining"]
        
        print(f"ファイルアップロード開始: {file.filename}")
        contents = await file.read()
        file_size_mb = len(contents) / (1024 * 1024)
        print(f"ファイルサイズ: {file_size_mb:.2f} MB")
        
        if len(contents) == 0:
            print("エラー: 空のファイル")
            raise HTTPException(
                status_code=400,
                detail="ファイルが空です。有効なファイルをアップロードしてください。"
            )
        
        # 大きなファイルの場合は警告
        if file_size_mb > 10:
            print(f"警告: ファイルサイズが大きい ({file_size_mb:.2f} MB)。処理に時間がかかる場合があります。")
            
        # ファイル形式に応じた処理
        file_extension = file.filename.split('.')[-1].lower()
        
        # データフレームとセクションを初期化
        df = None
        sections = {}
        extracted_text = ""
        
        try:
            # ファイル形式に応じた処理関数を呼び出す
            if file_extension in ['xlsx', 'xls']:
                print(f"Excelファイル処理開始: {file.filename}")
                df, sections, extracted_text = _process_excel_file(contents, file.filename)
                print(f"Excelファイル処理完了: {len(df)} 行のデータを抽出")
            elif file_extension == 'pdf':
                print(f"PDFファイル処理開始: {file.filename}")
                
                # PDFファイルが大きすぎる場合はエラーを返す
                if file_size_mb > 10:
                    raise HTTPException(
                        status_code=400,
                        detail=f"PDFファイルが大きすぎます ({file_size_mb:.2f} MB)。10MB以下のファイルを使用するか、ファイルを分割してください。"
                    )
                
                df, sections, extracted_text = await _process_pdf_file(contents, file.filename)
                print(f"PDFファイル処理完了: {len(df)} 行のデータを抽出")
            elif file_extension == 'txt':
                print(f"テキストファイル処理開始: {file.filename}")
                df, sections, extracted_text = _process_txt_file(contents, file.filename)
                print(f"テキストファイル処理完了: {len(df)} 行のデータを抽出")

            elif file_extension in ['.avi', 'mp4', '.webm']:
                if file_size_mb > 500:
                    raise HTTPException(
                        status_code=400,
                        detail=f"ビデオファイルが大きすぎます ({file_size_mb:.2f} MB)。500MB以下のファイルを使用するか、ファイルを分割してください。"
                    )
                
                df, sections, extracted_text = _process_video_file(contents, file.filename)
                print(f"Videoファイル処理完了: {len(df)} 行のデータを抽出")
                
            # データフレームの内容を確認
            if df is not None and not df.empty:
                print(f"データフレーム列: {df.columns.tolist()}")
                print(f"最初の行: {df.iloc[0].to_dict() if len(df) > 0 else 'なし'}")
            else:
                print("警告: 空のデータフレームが生成されました")
                
        except HTTPException:
            # HTTPExceptionはそのまま再スロー
            raise
        except Exception as e:
            error_type = {
                'xlsx': 'Excel', 'xls': 'Excel',
                'pdf': 'PDF',
                'txt': 'テキスト'
            }.get(file_extension, 'ファイル')
            
            print(f"{error_type}ファイル処理エラー: {str(e)}")
            import traceback
            print(traceback.format_exc())
            
            # タイムアウトエラーの特別処理
            if "timeout" in str(e).lower():
                raise HTTPException(
                    status_code=408,  # Request Timeout
                    detail=f"処理がタイムアウトしました。ファイルが大きすぎるか、複雑すぎる可能性があります。ファイルを分割するか、より小さなファイルを使用してください。"
                )
            else:
                raise HTTPException(
                    status_code=500,
                    detail=f"{error_type}ファイルの処理中にエラーが発生しました: {str(e)}"
                )
        
        # 知識ベースを更新（ファイルデータとして保存）
        if df is not None and not df.empty:
            # ファイル列が存在することを確認
            if 'file' not in df.columns:
                df['file'] = file.filename
                print(f"'file'列がないため追加しました: {file.filename}")
                
            # 知識ベースを更新
            _update_knowledge_base(df, extracted_text, is_file=True, source_name=file.filename, company_id=company_id)
            print(f"ファイルデータを知識ベースに追加: {file.filename} (会社ID: {company_id})")
            
            # 知識ベースの状態を確認
            print(f"知識ベース更新後のデータフレームサイズ: {len(knowledge_base.data) if knowledge_base.data is not None else 0} 行")
            print(f"知識ベース更新後のファイルデータ数: {len(knowledge_base.file_data)}")
        else:
            print("警告: データフレームが空のため知識ベースは更新されませんでした")
        
        # ソースリストにファイル名を追加し、タイムスタンプと有効状態を記録
        if file.filename not in knowledge_base.sources:
            knowledge_base.sources.append(file.filename)
            # 現在のタイムスタンプを記録
            knowledge_base.source_info[file.filename] = {
                'timestamp': datetime.now().isoformat(),
                'active': True  # デフォルトで有効
            }
            print(f"ソースリストに追加: {file.filename} (アクティブ: True)")
        else:
            print(f"ソースリストに既に存在: {file.filename}")
            # アクティブ状態を確認
            active = knowledge_base.source_info.get(file.filename, {}).get('active', True)
            print(f"現在のアクティブ状態: {active}")
            
        # ユーザーIDがある場合はドキュメントアップロードカウントを更新
        # if user_id and not limits_check.get("is_unlimited", False):
        if user_id:
            updated_limits = update_usage_count(user_id, "document_uploads_used", db)
            remaining_uploads = updated_limits["document_uploads_limit"] - updated_limits["document_uploads_used"]
            limit_reached = remaining_uploads <= 0
            
            # ドキュメントソースを記録
            document_id = str(uuid.uuid4())
            page_count = None
            if file_extension == 'pdf':
                try:
                    pdf_reader = PyPDF2.PdfReader(BytesIO(contents))
                    page_count = len(pdf_reader.pages)
                except:
                    pass
          
            cursor = db.cursor()

            cursor.execute(
                "INSERT INTO document_sources (id, name, type, page_count, content, uploaded_by, company_id, uploaded_at, active) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
                (document_id, file.filename, file_extension.upper(), page_count, extracted_text, user_id, company_id, datetime.now().isoformat(), True)
            )

            # 会社のソースリストに追加
            if company_id:
                if company_id not in knowledge_base.company_sources:
                    knowledge_base.company_sources[company_id] = []
                if file.filename not in knowledge_base.company_sources[company_id]:
                    knowledge_base.company_sources[company_id].append(file.filename)
            db.commit()
        
        # 最新の会社名を取得
        from .company import DEFAULT_COMPANY_NAME as current_company_name
        
        # プレビューデータの作成
        preview_data = []
        total_rows = 0
        
        if df is not None and not df.empty:
            preview_data = df.head(5).to_dict('records')
            # NaN値を適切に処理
            preview_data = [{k: (None if pd.isna(v) else v) for k, v in record.items()} for record in preview_data]
            total_rows = len(df)
        
        # アクティブなソースを取得
        active_sources = get_active_resources()
        print(f"現在のアクティブなソース: {active_sources}")
        
        return {
            "message": f"{current_company_name}の情報が正常に更新されました（ファイル: {file.filename}）",
            "columns": knowledge_base.columns if knowledge_base.data is not None else [],
            "preview": preview_data,
            "total_rows": total_rows,
            "sections": list(sections.keys()),
            "file": file.filename,
            "sources": knowledge_base.sources,
            "active_sources": active_sources,
            "remaining_uploads": remaining_uploads,
            "limit_reached": limit_reached
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"ファイルのアップロード中にエラーが発生しました: {str(e)}"
        )
# アクティブなリソースのみを取得する関数
def get_active_resources(company_id=None):
    """アクティブなリソースのみを取得する"""
    active_sources = []
    
    # 会社IDが指定されている場合は、その会社のリソースのみを対象にする
    if company_id and company_id in knowledge_base.company_sources:
        company_sources = knowledge_base.company_sources[company_id]
        for source in company_sources:
            if source in knowledge_base.source_info and knowledge_base.source_info[source].get('active', True):
                active_sources.append(source)
    else:
        # 会社IDが指定されていない場合は、すべてのアクティブなリソースを返す
        for source in knowledge_base.sources:
            if source in knowledge_base.source_info and knowledge_base.source_info[source].get('active', True):
                active_sources.append(source)
    
    return active_sources

# 知識ベース情報を取得する関数
def get_knowledge_base_info():
    """現在の知識ベースの情報を取得する"""
    # 最新の会社名を取得
    from .company import DEFAULT_COMPANY_NAME as current_company_name
    
    # ソース情報を整形
    sources_info = []
    for source in knowledge_base.sources:
        info = knowledge_base.source_info.get(source, {})
        source_type = "URL" if source.startswith(('http://', 'https://')) else "ファイル"
        
        sources_info.append({
            "name": source,
            "type": source_type,
            "timestamp": info.get('timestamp', '不明'),
            "active": info.get('active', True)
        })
    
    # アクティブなソースを取得
    active_sources = get_active_resources()
    
    return {
        "company_name": current_company_name,
        "total_sources": len(knowledge_base.sources),
        "active_sources": len(active_sources),
        "sources": sources_info,
        "data_size": len(knowledge_base.data) if knowledge_base.data is not None else 0,
        "columns": knowledge_base.columns if knowledge_base.data is not None else []
    }

# Excelファイルを処理する内部関数
def _process_excel_file(contents, filename):
    """Excelファイルを処理してデータフレーム、セクション、テキストを返す"""
    try:
        # BytesIOオブジェクトを作成
        excel_file = BytesIO(contents)
        
        # Excelファイルを読み込む
        df_dict = pd.read_excel(excel_file, sheet_name=None)
        
        # 全シートのデータを結合
        all_data = []
        sections = {}
        extracted_text = f"=== ファイル: {filename} ===\n\n"
        
        for sheet_name, sheet_df in df_dict.items():
            # シート名をセクションとして追加
            section_name = f"シート: {sheet_name}"
            sections[section_name] = sheet_df.to_string(index=False)
            extracted_text += f"=== {section_name} ===\n{sheet_df.to_string(index=False)}\n\n"
            
            # 各行のすべての内容を結合して content 列を作成
            for _, row in sheet_df.iterrows():
                row_dict = row.to_dict()
                
                # content 列を作成（すべての列の値を結合）
                content_parts = []
                for col, val in row_dict.items():
                    if not pd.isna(val):  # NaN値をスキップ
                        content_parts.append(f"{val}")
                
                # 結合したコンテンツを設定
                row_dict['content'] = " ".join(str(part) for part in content_parts if part)
                
                # メタデータを追加
                row_dict['section'] = section_name
                row_dict['source'] = 'Excel'
                row_dict['file'] = filename
                row_dict['url'] = None
                all_data.append(row_dict)
        
        # データフレームを作成
        result_df = pd.DataFrame(all_data) if all_data else pd.DataFrame({
            'section': [], 'content': [], 'source': [], 'file': [], 'url': []
        })
        
        # 必須列が存在することを確認
        for col in ['section', 'source', 'file', 'url', 'content']:
            if col not in result_df.columns:
                if col == 'source':
                    result_df[col] = 'Excel'
                elif col == 'file':
                    result_df[col] = filename
                elif col == 'content':
                    # 各行の全ての列の値を結合して content 列を作成
                    if not result_df.empty:
                        result_df[col] = result_df.apply(
                            lambda row: " ".join(str(val) for val in row.values if not pd.isna(val)),
                            axis=1
                        )
                else:
                    result_df[col] = None
        
        # デバッグ情報を出力
        print(f"処理後のデータフレーム列: {result_df.columns.tolist()}")
        if not result_df.empty:
            print(f"最初の行の content: {result_df['content'].iloc[0]}")
        
        return result_df, sections, extracted_text
    except Exception as e:
        print(f"Excelファイル処理エラー: {str(e)}")
        import traceback
        print(traceback.format_exc())
        raise

# PDFファイルを処理する内部関数
async def _process_pdf_file(contents, filename):
    """PDFファイルを処理してデータフレーム、セクション、テキストを返す"""
    try:
        # BytesIOオブジェクトを作成
        pdf_file = BytesIO(contents)
        
        # PDFファイルを読み込む
        pdf_reader = PyPDF2.PdfReader(pdf_file)
        
        # テキストを抽出
        all_text = ""
        sections = {}
        extracted_text = f"=== ファイル: {filename} ===\n\n"
        
        for i, page in enumerate(pdf_reader.pages):
            page_text = page.extract_text()
            if page_text:
                page_text = page_text.replace('\x00', '') # 🧼 Remove NUL characters
                section_name = f"ページ {i+1}" 
                sections[section_name] = page_text
                all_text += page_text + "\n"
                extracted_text += f"=== {section_name} ===\n{page_text}\n\n"
        
        # テキストをセクションに分割
        import re
        # 見出しパターン
        heading_pattern = r'^(?:\d+[\.\s]+|第\d+[章節]\s+|[\*\#]+\s+)?([A-Za-z\u3040-\u309F\u30A0-\u30FF\u4E00-\u9FAF]{2,}[：:、。])'
        
        # データを作成
        all_data = []
        current_section = "一般情報"
        current_content = []
        for line in all_text.split("\n"):
            line = line.strip()
            if not line:
                continue
            
            # 見出しかどうかを判定
            if re.search(heading_pattern, line):
                # 前のセクションを保存
                if current_content:
                    content_text = "\n".join(current_content)
                    all_data.append({
                        'section': current_section,
                        'content': content_text,
                        'source': 'PDF',
                        'file': filename,
                        'url': None
                    })
                
                # 新しいセクションを開始
                current_section = line
                current_content = []
            else:
                current_content.append(line)
        
        # 最後のセクションを保存
        if current_content:
            content_text = "\n".join(current_content)
            all_data.append({
                'section': current_section,
                'content': content_text,
                'source': 'PDF',
                'file': filename,
                'url': None
            })
        
        if all_text == "":
            all_text = await ocr_pdf_to_text_from_bytes(contents)
            result_df = pd.DataFrame(all_data) if all_data else pd.DataFrame({
                'section': ["一般情報"],
                'content': [all_text],
                'source': ['PDF'],
                'file': [filename],
                'url': [None]
            })
            extracted_text += all_text
        else: 
            # データフレームを作成
            result_df = pd.DataFrame(all_data) if all_data else pd.DataFrame({
                'section': ["一般情報"],
                'content': [all_text],
                'source': ['PDF'],
                'file': [filename],
                'url': [None]
            })
        
        return result_df, sections, extracted_text
    except Exception as e:
        print(f"PDFファイル処理エラー: {str(e)}")
        import traceback
        print(traceback.format_exc())
        raise

# テキストファイルを処理する内部関数
def _process_txt_file(contents, filename):
    """テキストファイルを処理してデータフレーム、セクション、テキストを返す"""
    try:
        # テキストを抽出
        try:
            text = contents.decode('utf-8')
        except UnicodeDecodeError:
            try:
                text = contents.decode('shift-jis')
            except UnicodeDecodeError:
                text = contents.decode('latin-1')
        
        # テキストをセクションに分割
        import re
        # 見出しパターン
        heading_pattern = r'^(?:\d+[\.\s]+|第\d+[章節]\s+|[\*\#]+\s+)?([A-Za-z\u3040-\u309F\u30A0-\u30FF\u4E00-\u9FAF]{2,}[：:、。])'
        
        # データを作成
        all_data = []
        sections = {}
        extracted_text = f"=== ファイル: {filename} ===\n\n"
        
        current_section = "一般情報"
        current_content = []
        
        for line in text.split("\n"):
            line = line.strip()
            if not line:
                continue
            
            # 見出しかどうかを判定
            if re.search(heading_pattern, line):
                # 前のセクションを保存
                if current_content:
                    content_text = "\n".join(current_content)
                    sections[current_section] = content_text
                    extracted_text += f"=== {current_section} ===\n{content_text}\n\n"
                    all_data.append({
                        'section': current_section,
                        'content': content_text,
                        'source': 'TXT',
                        'file': filename,
                        'url': None
                    })
                
                # 新しいセクションを開始
                current_section = line
                current_content = []
            else:
                current_content.append(line)
        
        # 最後のセクションを保存
        if current_content:
            content_text = "\n".join(current_content)
            sections[current_section] = content_text
            extracted_text += f"=== {current_section} ===\n{content_text}\n\n"
            all_data.append({
                'section': current_section,
                'content': content_text,
                'source': 'TXT',
                'file': filename,
                'url': None
            })
        
        # データフレームを作成
        result_df = pd.DataFrame(all_data) if all_data else pd.DataFrame({
            'section': ["一般情報"],
            'content': [text],
            'source': ['TXT'],
            'file': [filename],
            'url': [None]
        })
        
        return result_df, sections, extracted_text
    except Exception as e:
        print(f"テキストファイル処理エラー: {str(e)}")
        import traceback
        print(traceback.format_exc())
        raise
# 知識ベースを更新する内部関数
def _update_knowledge_base(df, text, is_file=True, source_name=None, company_id=None):
    """知識ベースを更新する内部関数"""
    # 元のデータを保存
    if source_name:
        knowledge_base.original_data[source_name] = {
            'df': df.copy(),
            'text': text,
            'company_id': company_id
        }
        
        # 会社のソースリストに追加
        if company_id:
            if company_id not in knowledge_base.company_sources:
                knowledge_base.company_sources[company_id] = []
            if source_name not in knowledge_base.company_sources[company_id]:
                knowledge_base.company_sources[company_id].append(source_name)
    
    # ファイルかURLかに応じてデータを保存
    if is_file:
        knowledge_base.file_data.append(df)
        knowledge_base.file_texts.append(text)
    else:
        knowledge_base.url_data.append(df)
        knowledge_base.url_texts.append(text)
    
    # 全データを結合
    all_data = []
    if knowledge_base.file_data:
        all_data.extend(knowledge_base.file_data)
    if knowledge_base.url_data:
        all_data.extend(knowledge_base.url_data)
    
    if all_data:
        # データフレームを結合
        knowledge_base.data = pd.concat(all_data, ignore_index=True)
        
        # 列名を保存
        knowledge_base.columns = knowledge_base.data.columns.tolist()
        
        # 生テキストを結合
        all_texts = []
        if knowledge_base.file_texts:
            all_texts.extend(knowledge_base.file_texts)
        if knowledge_base.url_texts:
            all_texts.extend(knowledge_base.url_texts)
        
        knowledge_base.raw_text = "\n\n".join(all_texts)
    
    print(f"知識ベース更新完了: {len(knowledge_base.data) if knowledge_base.data is not None else 0} 行のデータ")

# リソースのアクティブ状態を切り替える関数
async def toggle_resource_active(resource_name: str):
    """リソースのアクティブ状態を切り替える"""
    if resource_name not in knowledge_base.sources:
        raise HTTPException(
            status_code=404,
            detail=f"リソース '{resource_name}' が見つかりません"
        )
    
    # 現在の状態を取得
    current_state = knowledge_base.source_info.get(resource_name, {}).get('active', True)
    
    # 状態を反転
    new_state = not current_state
    
    # 状態を更新
    if resource_name not in knowledge_base.source_info:
        knowledge_base.source_info[resource_name] = {}
    
    knowledge_base.source_info[resource_name]['active'] = new_state
    
    return {
        "name": resource_name,
        "active": new_state,
        "message": f"リソース '{resource_name}' のアクティブ状態を {new_state} に変更しました"
    }

# アップロードされたリソースを取得する関数
async def get_uploaded_resources():
    """アップロードされたリソース（URL、PDF、Excel、TXT）の情報を取得する"""
    resources = []
    
    for source in knowledge_base.sources:
        info = knowledge_base.source_info.get(source, {})
        
        # リソースタイプを判定
        if source.startswith(('http://', 'https://')):
            resource_type = "URL"
        else:
            extension = source.split('.')[-1].lower() if '.' in source else ""
            if extension in ['xlsx', 'xls']:
                resource_type = "Excel"
            elif extension == 'pdf':
                resource_type = "PDF"
            elif extension == 'txt':
                resource_type = "テキスト"
            if extension in ['avi', 'mp4', 'webp']:
                resource_type = "Video"
            else:
                resource_type = "その他"
        
        resources.append({
            "name": source,
            "type": resource_type,
            "timestamp": info.get('timestamp', datetime.now().isoformat()),
            "active": info.get('active', True)
        })
    
    return {
        "resources": resources,
        "message": f"{len(resources)}件のリソースが見つかりました"
    }

# using gemini ocr 
# def ocr_with_gemini(images, instruction):
#     batch_size = 4 # performance size
#     prompt = f"""
#     {instruction}
#     These are pages from a PDF document. Extract all text content while preserving the structure.
#     Pay special attention to tables, columns, headers, and any structured content.
#     Maintain paragraph breaks and formatting.
#     """
#     # Assuming `model.generate_content` works with images and a prompt
#     # response = model.generate_content([prompt, *images])  # Passing the image objects directly

#     # Combine all text parts if it's a multi-part response
#     full_text = ""
#     for i in range(0, len(images), batch_size):
#         image_batch = images[i:i+batch_size]
#         try:
#             response = model.generate_content([prompt, *image_batch])
#             for part in response.parts:
#                 full_text += part.text
#         except Exception as e:
#             full_text += f"\n\n[Error processing pages {i}–{i+batch_size-1}]: {e}\n"

#     return full_text
# async def ocr_with_gemini(images, instruction):
#     prompt_base = f"""
#     {instruction}
#     This is a page from a PDF document. Extract all text content while preserving the structure.
#     Pay special attention to tables, columns, headers, and any structured content.
#     Maintain paragraph breaks and formatting.
#     """
    
#     full_text = ""
#     for idx, image in enumerate(images):
#         try:
#             prompt = f"{prompt_base}\n\nPage {idx + 1}:"
#             response = model.generate_content([prompt, image])
#             for part in response.parts:
#                 full_text += f"\n\n--- Page {idx + 1} ---\n{part.text}"
#         except Exception as e:
#             full_text += f"\n\n[Error processing page {idx + 1}]: {e}\n"

#     return full_text
async def ocr_with_gemini(images, instruction):
    prompt_base = f"""
    {instruction}
    This is a page from a PDF document. Extract all text content while preserving the structure.
    Pay special attention to tables, columns, headers, and any structured content.
    Maintain paragraph breaks and formatting.
    """

    async def process_page(idx, image):
        def sync_call():
            prompt = f"{prompt_base}\n\nPage {idx + 1}:"
            response = model.generate_content([prompt, image])
            return f"\n\n--- Page {idx + 1} ---\n" + "".join(part.text for part in response.parts)

        try:
            return await asyncio.to_thread(sync_call)
        except Exception as e:
            return f"\n\n[Error processing page {idx + 1}]: {e}\n"

    tasks = [process_page(idx, img) for idx, img in enumerate(images)]
    results = await asyncio.gather(*tasks)

    return "".join(results)

# Main OCR function
async def ocr_pdf_to_text_from_bytes(pdf_content: bytes):
    # Convert PDF to images directly from bytes
    images = convert_pdf_to_images_from_bytes(pdf_content)

    # Define instruction for Gemini OCR
    instruction = """
    Extract ALL text content from these document pages.
    For tables:
    1. Maintain the table structure using markdown table format.
    2. Preserve all column headers and row labels.
    3. Ensure numerical data is accurately captured.
    For multi-column layouts:
    1. Process columns from left to right.
    2. Clearly separate content from different columns.
    For charts and graphs:
    1. Describe the chart type.
    2. Extract any visible axis labels, legends, and data points.
    3. Extract any title or caption.
    Preserve all headers, footers, page numbers, and footnotes.
    """

    # Extract text using Gemini OCR
    extracted_text = await ocr_with_gemini(images, instruction)

    return extracted_text

# Convert PDF to images directly from bytes
def convert_pdf_to_images_from_bytes(pdf_content, dpi=200):
    images = convert_from_bytes(pdf_content, dpi=dpi)
    return images  # This will return a list of PIL Image objects
# 以下は既存の処理関数（_process_excel_file, _process_pdf_file, _process_txt_file, _extract_text_from_image_with_gemini）
# これらの関数は変更せず、そのまま使用します