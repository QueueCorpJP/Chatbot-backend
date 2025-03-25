"""
チャットモジュール
チャット機能とAI応答生成を管理します
"""
import json
import re
import uuid
from datetime import datetime
import logging
from sqlite3 import Connection
from fastapi import HTTPException, Depends
from .company import DEFAULT_COMPANY_NAME
from .models import ChatMessage, ChatResponse
from .database import get_db, update_usage_count, get_usage_limits
from .knowledge_base import knowledge_base, get_active_resources
from .auth import check_usage_limits

logger = logging.getLogger(__name__)

# Geminiモデル（グローバル変数）
model = None

def set_model(gemini_model):
    """Geminiモデルを設定する"""
    global model
    model = gemini_model

async def process_chat(message: ChatMessage, db: Connection = Depends(get_db)):
    """チャットメッセージを処理してGeminiからの応答を返す"""
    try:
        # 最新の会社名を取得（モジュールからの直接インポートではなく、関数内で再取得）
        from .company import DEFAULT_COMPANY_NAME as current_company_name
        
        # ユーザーIDがある場合は利用制限をチェック
        remaining_questions = None
        limit_reached = False
        
        if message.user_id:
            # 質問の利用制限をチェック
            limits_check = check_usage_limits(message.user_id, "question", db)
            
            if not limits_check["is_unlimited"] and not limits_check["allowed"]:
                response_text = f"申し訳ございません。デモ版の質問回数制限（{limits_check['limit']}回）に達しました。"
                return {
                    "response": response_text,
                    "remaining_questions": 0,
                    "limit_reached": True
                }
            
            # 無制限でない場合は残り回数を計算
            if not limits_check["is_unlimited"]:
                remaining_questions = limits_check["remaining"]
        
        if knowledge_base.data is None or len(knowledge_base.data) == 0:
            response_text = f"申し訳ございません。{current_company_name}の情報が設定されていません。まずはExcelファイルをアップロードするか、URLを送信してください。"
            
            # チャット履歴を保存
            chat_id = str(uuid.uuid4())
            cursor = db.cursor()
            cursor.execute(
                "INSERT INTO chat_history (id, user_message, bot_response, timestamp, category, sentiment, employee_id, employee_name) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (chat_id, message.text, response_text, datetime.now().isoformat(), "設定エラー", "neutral", message.employee_id, message.employee_name)
            )
            db.commit()
            
            return {
                "response": response_text,
                "remaining_questions": remaining_questions,
                "limit_reached": limit_reached
            }

        # ユーザーの会社IDを取得
        company_id = None
        if message.user_id:
            cursor = db.cursor()
            cursor.execute("SELECT company_id FROM users WHERE id = ?", (message.user_id,))
            user = cursor.fetchone()
            if user and user['company_id']:
                company_id = user['company_id']
        
        # 最新の会社名を取得
        from .company import DEFAULT_COMPANY_NAME as current_company_name
        
        # 会社固有のアクティブなリソースを取得
        active_sources = get_active_resources(company_id)
        print(f"アクティブなリソース (会社ID: {company_id}): {', '.join(active_sources)}")
        
        # アクティブなリソースがない場合はエラーメッセージを返す
        if not active_sources:
            response_text = f"申し訳ございません。現在、アクティブな知識ベースがありません。管理画面でリソースを有効にしてください。"
            
            # チャット履歴を保存
            chat_id = str(uuid.uuid4())
            cursor = db.cursor()
            cursor.execute(
                "INSERT INTO chat_history (id, user_message, bot_response, timestamp, category, sentiment, employee_id, employee_name) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (chat_id, message.text, response_text, datetime.now().isoformat(), "設定エラー", "neutral", message.employee_id, message.employee_name)
            )
            db.commit()
            
            return {
                "response": response_text,
                "remaining_questions": remaining_questions,
                "limit_reached": limit_reached
            }
        
        # pandas をインポート
        import pandas as pd
        import traceback
        
        # 選択されたリソースを使用して知識ベースを作成
        active_knowledge_text = ""
        source_info = {}  # ソース情報を保存する辞書
        
        print(f"知識ベースの生データ長: {len(knowledge_base.raw_text) if knowledge_base.raw_text else 0}")
        print(f"アクティブなソース: {active_sources}")
        
        # 方法1: データフレームからアクティブなリソースのデータを抽出
        try:
            if knowledge_base.data is not None and not knowledge_base.data.empty:
                print(f"知識ベースのデータフレーム列: {knowledge_base.data.columns.tolist()}")
                print(f"アクティブなソース: {active_sources}")
                
                # データフレームをコピーして作業する（元のデータを変更しないため）
                filtered_data = knowledge_base.data.copy()
                
                # フィルタリング条件を準備
                mask = pd.Series(False, index=filtered_data.index)
                
                # URLカラムがある場合、アクティブなURLでフィルタリング
                if 'url' in filtered_data.columns:
                    # 完全一致でフィルタリング
                    url_mask = filtered_data['url'].notna() & filtered_data['url'].isin(active_sources)
                    
                    # 部分一致でもフィルタリング（URLの一部がactive_sourcesに含まれる場合）
                    for source in active_sources:
                        partial_url_mask = filtered_data['url'].notna() & filtered_data['url'].str.contains(source, na=False)
                        url_mask = url_mask | partial_url_mask
                    
                    mask = mask | url_mask
                    print(f"URLフィルタリングマッチ数: {url_mask.sum()}")
                
                # fileカラムがある場合、アクティブなファイルでフィルタリング
                if 'file' in filtered_data.columns:
                    # 完全一致でフィルタリング
                    file_mask = filtered_data['file'].notna() & filtered_data['file'].isin(active_sources)
                    
                    # 部分一致でもフィルタリング（ファイル名の一部がactive_sourcesに含まれる場合）
                    for source in active_sources:
                        partial_file_mask = filtered_data['file'].notna() & filtered_data['file'].str.contains(source, na=False)
                        file_mask = file_mask | partial_file_mask
                    
                    mask = mask | file_mask
                    print(f"ファイルフィルタリングマッチ数: {file_mask.sum()}")
                
                # フィルタリングしたデータを取得
                active_data = filtered_data[mask]
                print(f"アクティブなデータ行数: {len(active_data)}")
                
                # アクティブなデータが空の場合、もう一度試行
                if active_data.empty and active_sources:
                    print("アクティブなデータが見つかりませんでした。別の方法で試行します。")
                    
                    # 全てのデータを確認
                    for idx, row in filtered_data.iterrows():
                        source_found = False
                        
                        # URLカラムをチェック
                        if 'url' in row and pd.notna(row['url']):
                            for source in active_sources:
                                if source in str(row['url']):
                                    source_found = True
                                    break
                        
                        # fileカラムをチェック
                        if not source_found and 'file' in row and pd.notna(row['file']):
                            for source in active_sources:
                                if source in str(row['file']):
                                    source_found = True
                                    break
                        
                        if source_found:
                            # 行を追加
                            active_data = pd.concat([active_data, pd.DataFrame([row])], ignore_index=True)
                    
                    print(f"2回目の試行後のアクティブなデータ行数: {len(active_data)}")
                
                # 各セクションのコンテンツをテキストに追加
                if not active_data.empty:
                    for _, row in active_data.iterrows():
                        try:
                            section = str(row.get('section', '')) if 'section' in row else 'セクション情報なし'
                            content = str(row.get('content', '')) if 'content' in row else ''
                            
                            # ソース情報の取得
                            source_type = str(row.get('source', '')) if 'source' in row else ''
                            source_name = ''
                            page_info = str(row.get('page', '')) if 'page' in row else ''
                            
                            if 'url' in row and pd.notna(row['url']):
                                source_name = str(row['url'])
                            elif 'file' in row and pd.notna(row['file']):
                                source_name = str(row['file'])
                            
                            # ソース情報を保存
                            source_key = f"{source_name}:{section}"
                            if source_key not in source_info:
                                source_info[source_key] = {
                                    "name": source_name,
                                    "section": section,
                                    "page": page_info
                                }
                            
                            # テキストに追加 (ソース情報は別途返すので、ここでは含めない)
                            active_knowledge_text += f"\n=== {section} ===\n"
                            active_knowledge_text += f"{content}\n\n"
                        except Exception as row_e:
                            print(f"行の処理中にエラー: {str(row_e)}")
        except Exception as e:
            print(f"データフレーム処理エラー: {str(e)}")
            print(traceback.format_exc())
        
        # 方法2: 従来の方法でテキストベースのフィルタリングを試行
        if not active_knowledge_text.strip() and knowledge_base.raw_text:
            print("従来の方法で知識ベーステキストを処理します")
            try:
                # 全テキストを行に分割
                lines = knowledge_base.raw_text.split('\n')
                current_source = None
                current_section = None
                include_section = False
                
                print(f"アクティブソース一覧: {active_sources}")
                
                for line in lines:
                    # URLセクションの開始を検出
                    if "=== URL:" in line:
                        url = line.replace("=== URL:", "").strip()
                        current_source = url
                        current_section = "URL情報"
                        # 完全一致のチェック
                        include_section = current_source in active_sources
                        # 完全一致しない場合は、部分一致でもチェック
                        if not include_section:
                            include_section = any(active_source in url for active_source in active_sources)
                        print(f"URLセクション検出: {url}, アクティブ: {include_section}")
                        
                        # ソース情報を保存
                        if include_section:
                            source_key = f"{current_source}:{current_section}"
                            if source_key not in source_info:
                                source_info[source_key] = {
                                    "name": current_source,
                                    "section": current_section,
                                    "page": ""
                                }
                    
                    # ファイル名を含むセクションの開始を検出（PDFやExcelなど）
                    elif "===" in line:
                        # セクション名を抽出
                        section_match = re.search(r'=== (.*?) \(', line)
                        if section_match:
                            current_section = section_match.group(1)
                        
                        # ページ情報を抽出
                        page_match = re.search(r'ページ: (\d+)', line)
                        page_info = page_match.group(1) if page_match else ""
                        
                        # アクティブソースとの部分一致をチェック
                        matched_source = None
                        for source in active_sources:
                            if source in line:
                                matched_source = source
                                break
                                
                        if matched_source:
                            current_source = matched_source
                            include_section = True
                            print(f"ファイルセクション検出: {matched_source}, アクティブ: True")
                            
                            # ソース情報を保存
                            source_key = f"{current_source}:{current_section}"
                            if source_key not in source_info:
                                source_info[source_key] = {
                                    "name": current_source,
                                    "section": current_section,
                                    "page": page_info
                                }
                        elif current_source and "===" in line:  # 新しいセクションの開始だが、アクティブソースではない
                            print(f"新しいセクション検出、現在のソースを維持: {current_source}")
                    
                    # 選択されたソースの場合のみテキストを追加
                    if include_section:
                        active_knowledge_text += line + '\n'
                
                print(f"従来の方法で抽出したテキスト長: {len(active_knowledge_text)}")
            except Exception as text_e:
                print(f"テキスト処理エラー: {str(text_e)}")
                print(traceback.format_exc())
        
        # アクティブな知識ベースが空の場合はエラーメッセージを返す
        if not active_knowledge_text.strip():
            response_text = f"申し訳ございません。アクティブな知識ベースの内容が空です。管理画面で別のリソースを有効にしてください。"
            
            # チャット履歴を保存
            chat_id = str(uuid.uuid4())
            cursor = db.cursor()
            cursor.execute(
                "INSERT INTO chat_history (id, user_message, bot_response, timestamp, category, sentiment, employee_id, employee_name) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (chat_id, message.text, response_text, datetime.now().isoformat(), "設定エラー", "neutral", message.employee_id, message.employee_name)
            )
            db.commit()
            
            return {
                "response": response_text,
                "remaining_questions": remaining_questions,
                "limit_reached": limit_reached
            }
            
        # プロンプトの作成
        prompt = f"""
        あなたは親切で丁寧な対応ができる{current_company_name}のアシスタントです。
        以下の知識ベースを参考に、ユーザーの質問に対して可能な限り具体的で役立つ回答を提供してください。

        回答の際の注意点：
        1. 常に丁寧な言葉遣いを心がけ、ユーザーに対して敬意を持って接してください
        2. 知識ベースに情報がない場合でも、一般的な文脈で回答できる場合は適切に対応してください
        3. 具体的な情報が必要な場合は、どのような情報があれば回答できるかを説明してください
        4. 可能な限り具体的で実用的な情報を提供してください
        5. 知識ベースにOCRで抽出されたテキスト（PDF (OCR)と表示されている部分）が含まれている場合は、それが画像から抽出されたテキストであることを考慮してください
        6. OCRで抽出されたテキストには多少の誤りがある可能性がありますが、文脈から適切に解釈して回答してください
        7. 回答の最後に、情報の出典を「情報ソース: [ドキュメント名]（[セクション名]、[ページ番号]）」の形式で必ず記載してください。複数のソースを参照した場合は、それぞれを記載してください。

        利用可能なデータ列：
        {', '.join(knowledge_base.columns)}

        知識ベース内容（アクティブなリソースのみ）：
        {active_knowledge_text}

        {f"画像情報：PDFから抽出された画像が{len(knowledge_base.images)}枚あります。" if hasattr(knowledge_base, 'images') and knowledge_base.images else ""}

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
        3. 参照ソース: 回答に使用した主なソース情報を1つ選んでください。以下のソース情報から選択してください：
        {json.dumps(list(source_info.values()))}

        回答は以下のJSON形式で返してください：
        {{
            "category": "カテゴリ名",
            "sentiment": "感情",
            "source": {{
                "name": "ソース名",
                "section": "セクション名",
                "page": "ページ番号"
            }}
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
            json_match = re.search(r'```json\s*(.*?)\s*```', analysis_text, re.DOTALL)
            if json_match:
                analysis_json = json.loads(json_match.group(1))
            else:
                # コードブロックがない場合は直接パース
                analysis_json = json.loads(analysis_text)
                
            category = analysis_json.get("category", "未分類")
            sentiment = analysis_json.get("sentiment", "neutral")
            source_doc = analysis_json.get("source", {}).get("name", "")
            source_page = analysis_json.get("source", {}).get("page", "")
        except Exception as json_error:
            print(f"JSON解析エラー: {str(json_error)}")
            category = "未分類"
            sentiment = "neutral"
            source_doc = ""
            source_page = ""
        
        # チャット履歴を保存
        chat_id = str(uuid.uuid4())
        cursor = db.cursor()
        cursor.execute(
            "INSERT INTO chat_history (id, user_message, bot_response, timestamp, category, sentiment, employee_id, employee_name, source_document, source_page) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (chat_id, message.text, response_text, datetime.now().isoformat(), category, sentiment, message.employee_id, message.employee_name, source_doc, source_page)
        )
        db.commit()
        
        # ユーザーIDがある場合は質問カウントを更新
        if message.user_id and not limits_check.get("is_unlimited", False):
            updated_limits = update_usage_count(message.user_id, "questions_used", db)
            remaining_questions = updated_limits["questions_limit"] - updated_limits["questions_used"]
            limit_reached = remaining_questions <= 0
        
        return {
            "response": response_text,
            "source": source_doc + (f" (P.{source_page})" if source_page else ""),
            "remaining_questions": remaining_questions,
            "limit_reached": limit_reached
        }
    except Exception as e:
        print(f"チャットエラー: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))