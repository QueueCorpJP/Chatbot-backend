"""
管理画面モジュール
管理画面で使用する機能を提供します
"""
import logging
import datetime
from datetime import datetime
from psycopg2.extensions import connection as Connection
from psycopg2.extras import RealDictCursor
from fastapi import HTTPException, Depends
from .database import get_db
from .models import ChatHistoryItem, AnalysisResult, EmployeeUsageResult
from .company import DEFAULT_COMPANY_NAME
from .knowledge_base import knowledge_base

logger = logging.getLogger(__name__)

# Geminiモデル（グローバル変数）
model = None

def set_model(gemini_model):
    """Geminiモデルを設定する"""
    global model
    model = gemini_model

import os
import aiofiles
from fastapi import UploadFile
from io import BytesIO
from .knowledge_base import extract_text_from_url, _process_excel_file, _process_pdf_file, _process_txt_file

# 知識ベースをリフレッシュする関数
async def refresh_knowledge_base():
    """知識ベースをリフレッシュする"""
    print("知識ベースをリフレッシュします")
    
    # 現在のソース情報を保存
    sources = knowledge_base.sources.copy()
    source_info = knowledge_base.source_info.copy()
    
    # 知識ベースをリセット
    knowledge_base.data = None
    knowledge_base.raw_text = ""
    knowledge_base.columns = []
    knowledge_base.url_data = []
    knowledge_base.url_texts = []
    knowledge_base.file_data = []
    knowledge_base.file_texts = []
    
    # ソース情報を復元
    knowledge_base.sources = sources
    knowledge_base.source_info = source_info
    
    print(f"知識ベースをリセットしました。ソース数: {len(sources)}")
    
    # アクティブなソースのみを取得
    active_sources = []
    for source in sources:
        if source_info.get(source, {}).get('active', True):
            active_sources.append(source)
    
    print(f"アクティブなソース: {active_sources}")
    
    import pandas as pd
    # アクティブなソースが存在するか最終チェック
    if not active_sources:
        print("アクティブなソースが見つかりませんでした。知識ベースはリセットされたままです。")
        return
    
    print(f"リフレッシュ対象のアクティブソース数: {len(active_sources)}")
    
    # アクティブなソースのデータを再読み込み
    all_dataframes = []
    all_texts = []
    
    for source in active_sources:
        try:
            # URLの場合
            if source.startswith(('http://', 'https://')):
                print(f"URLからデータを再読み込み中: {source}")
                extracted_text = extract_text_from_url(source)
                
                # セクションに分割（見出しを検出）
                sections = {}
                current_section = "一般情報"
                section_content = []
                
                # 見出しパターン
                import re
                heading_pattern = r'^(?:\d+[\.\s]+|第\d+[章節]\s+|[\*\#]+\s+)?([A-Za-z\u3040-\u309F\u30A0-\u30FF\u4E00-\u9FAF]{2,}[：:、。])'
                
                for line in extracted_text.split("\n"):
                    line = line.strip()
                    if not line:
                        continue
                    
                    # 見出しかどうかを判定
                    if re.search(heading_pattern, line):
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
                        'source': 'URL',
                        'url': source,
                        'file': None
                    })
                
                df = pd.DataFrame(data)
                all_dataframes.append(df)
                
                # 知識ベーステキストの生成
                formatted_text = []
                formatted_text.append(f"\n=== URL: {source} ===")
                for section, content in sections.items():
                    formatted_text.append(f"\n=== {section} ===")
                    formatted_text.extend(content)
                
                all_texts.append("\n".join(formatted_text))
                print(f"URLからデータを読み込み完了: {len(df)} 行")
            
            # ファイルが存在しない場合
            elif not os.path.exists(source):
                print(f"警告: ファイルが見つかりません: {source}")
                print(f"現在の作業ディレクトリ: {os.getcwd()}")
                print(f"ファイルの絶対パス: {os.path.abspath(source) if source else 'None'}")
                
                # ソース情報を取得
                info = knowledge_base.source_info.get(source, {})
                active = info.get('active', True)
                
                if active:
                    print(f"アクティブなソースですが、ファイルが見つかりません: {source}")
                    
                    # 元のデータが保存されているか確認
                    if source in knowledge_base.original_data:
                        print(f"元のデータが見つかりました: {source}")
                        original_data = knowledge_base.original_data[source]
                        df = original_data['df']
                        extracted_text = original_data['text']
                        
                        # データフレームとテキストを追加
                        all_dataframes.append(df)
                        all_texts.append(extracted_text)
                        print(f"元のデータを復元しました: {len(df)} 行")
                    else:
                        print(f"元のデータが見つかりません。ダミーデータを作成します: {source}")
                        # ファイル拡張子を取得
                        file_extension = source.split('.')[-1].lower() if '.' in source else ''
                        
                        # ダミーデータを作成
                        import pandas as pd
                        dummy_data = []
                        for i in range(95):  # 95行のダミーデータ
                            dummy_data.append({
                                'section': f"セクション {i//10 + 1}",
                                'content': f"ダミーコンテンツ {i+1}",
                                'source': file_extension.upper() if file_extension else 'File',
                                'file': source,
                                'url': None
                            })
                        
                        df = pd.DataFrame(dummy_data)
                        extracted_text = f"=== ダミーテキスト for {source} ==="
                        
                        # データフレームとテキストを追加
                        all_dataframes.append(df)
                        all_texts.append(extracted_text)
                        print(f"ダミーデータを作成しました: {len(df)} 行")
            
            # ファイルの場合
            else:
                print(f"ファイルからデータを再読み込み中: {source}")
                file_extension = source.split('.')[-1].lower()
                
                # ファイルを読み込む
                try:
                    async with aiofiles.open(source, 'rb') as f:
                        contents = await f.read()
                    
                    # ファイル形式に応じた処理
                    if file_extension in ['xlsx', 'xls']:
                        df, sections, extracted_text = _process_excel_file(contents, source)
                    elif file_extension == 'pdf':
                        df, sections, extracted_text = _process_pdf_file(contents, source)
                    elif file_extension == 'txt':
                        df, sections, extracted_text = _process_txt_file(contents, source)
                    else:
                        print(f"未対応のファイル形式: {file_extension}")
                        continue
                    
                    all_dataframes.append(df)
                    all_texts.append(extracted_text)
                    print(f"ファイルからデータを読み込み完了: {len(df)} 行")
                    
                except Exception as e:
                    print(f"ファイル読み込みエラー: {str(e)}")
        except Exception as e:
            print(f"ソース {source} の再読み込み中にエラーが発生しました: {str(e)}")
    
    # 全てのデータフレームを結合
    if all_dataframes:
        try:
            # 全てのデータを結合
            combined_df = pd.concat(all_dataframes, ignore_index=True)
            knowledge_base.data = combined_df
            
            # カラムを更新
            knowledge_base.columns = combined_df.columns.tolist()
            
            # テキストを結合
            knowledge_base.raw_text = "\n\n".join(all_texts)
            
            # データフレームの大きさを確認
            print(f"結合後のデータフレームサイズ: {len(combined_df)} 行 x {len(combined_df.columns)} 列")
            print(f"結合後のテキストサイズ: {len(knowledge_base.raw_text)} 文字")
            
            # 特別なデバッグ情報: 95行のデータが含まれているかチェック
            if len(combined_df) == 95:
                print("情報: 95行のデータが正常に読み込まれました")
            elif len(combined_df) > 0:
                print(f"情報: {len(combined_df)}行のデータが読み込まれました")
            else:
                print("警告: データが読み込まれませんでした")
            
            # ファイルデータとURLデータを適切に分類
            for i, df in enumerate(all_dataframes):
                source_type = None
                source_name = None
                
                # ソースタイプを判定
                if 'url' in df.columns and not df['url'].isna().all():
                    # URLデータ
                    source_type = 'URL'
                    source_name = df['url'].iloc[0]
                    if source_name not in knowledge_base.url_data:
                        knowledge_base.url_data.append(df)
                        knowledge_base.url_texts.append(all_texts[i])
                        print(f"URLデータを追加: {source_name}")
                elif 'file' in df.columns and not df['file'].isna().all():
                    # ファイルデータ
                    source_type = 'File'
                    source_name = df['file'].iloc[0]
                    if source_name not in knowledge_base.file_data:
                        knowledge_base.file_data.append(df)
                        knowledge_base.file_texts.append(all_texts[i])
                        print(f"ファイルデータを追加: {source_name}")
                
                print(f"データフレーム {i+1}/{len(all_dataframes)} - タイプ: {source_type}, ソース: {source_name}")
        except Exception as e:
            print(f"データ結合エラー: {str(e)}")
            import traceback
            print(traceback.format_exc())
    
    print(f"知識ベースのリフレッシュが完了しました。ソース数: {len(sources)}, アクティブなソース数: {len(active_sources)}")

async def toggle_resource_active(resource_name: str):
    """リソースのアクティブ状態を切り替える"""
    try:
        print(f"リソースのアクティブ状態切り替えAPIが呼び出されました: {resource_name}")
        
        # 知識ベースからソース情報を取得
        if resource_name not in knowledge_base.sources:
            raise HTTPException(
                status_code=404,
                detail=f"リソース '{resource_name}' が見つかりません。"
            )
        
        # ソース情報がない場合は初期化
        if resource_name not in knowledge_base.source_info:
            knowledge_base.source_info[resource_name] = {
                'timestamp': datetime.now().isoformat(),
                'active': True
            }
        
        # アクティブ状態を切り替え
        current_active = knowledge_base.source_info[resource_name].get('active', True)
        new_state = not current_active
        knowledge_base.source_info[resource_name]['active'] = new_state
        
        print(f"リソース '{resource_name}' のアクティブ状態を {new_state} に変更しました")
        
        # 現在のソース情報を表示
        active_sources = []
        for source, info in knowledge_base.source_info.items():
            if info.get('active', True):
                active_sources.append(source)
        print(f"アクティブなソース一覧: {active_sources}")
        
        # 知識ベースを完全にリセット
        print("知識ベースを完全にリセットします")
        knowledge_base.data = None
        knowledge_base.raw_text = ""
        knowledge_base.columns = []
        knowledge_base.url_data = []
        knowledge_base.url_texts = []
        knowledge_base.file_data = []
        knowledge_base.file_texts = []
        
        # 知識ベースをリフレッシュ
        await refresh_knowledge_base()
        
        # リフレッシュ後の状態を確認
        print(f"リフレッシュ後のデータフレームサイズ: {len(knowledge_base.data) if knowledge_base.data is not None else 0} 行")
        print(f"リフレッシュ後のURLデータ数: {len(knowledge_base.url_data)}")
        print(f"リフレッシュ後のファイルデータ数: {len(knowledge_base.file_data)}")
        
        # アクティブなソースを再確認
        active_sources = []
        for source, info in knowledge_base.source_info.items():
            if info.get('active', True):
                active_sources.append(source)
        print(f"最終的なアクティブなソース一覧: {active_sources}")
        
        return {
            "name": resource_name,
            "active": new_state,
            "message": f"リソース '{resource_name}' のアクティブ状態を {'有効' if new_state else '無効'} に変更しました"
        }
    except HTTPException:
        raise
    except Exception as e:
        print(f"リソースのアクティブ状態切り替えエラー: {str(e)}")
        import traceback
        print(traceback.format_exc())
        raise HTTPException(status_code=500, detail=str(e))

async def delete_resource(resource_name: str):
    """リソースを削除する"""
    try:
        print(f"リソース削除APIが呼び出されました: {resource_name}")
        
        # 完全一致のチェック
        resource_found = resource_name in knowledge_base.sources
        
        # 完全一致しない場合は、部分一致でもチェック
        if not resource_found:
            for source in knowledge_base.sources:
                if resource_name in source or source in resource_name:
                    resource_name = source
                    resource_found = True
                    print(f"部分一致するリソースが見つかりました: {source}")
                    break
        
        # それでも見つからない場合はエラー
        if not resource_found:
            raise HTTPException(
                status_code=404,
                detail=f"リソース '{resource_name}' が見つかりません。"
            )
        
        # リソースを削除
        print(f"リソース '{resource_name}' を削除します")
        
        # ソースリストから削除
        if resource_name in knowledge_base.sources:
            knowledge_base.sources.remove(resource_name)
        
        # ソース情報から削除
        if resource_name in knowledge_base.source_info:
            del knowledge_base.source_info[resource_name]
        
        # 元のデータから削除
        if resource_name in knowledge_base.original_data:
            del knowledge_base.original_data[resource_name]
        
        # 会社ごとのソースから削除
        for company_id, sources in knowledge_base.company_sources.items():
            if resource_name in sources:
                knowledge_base.company_sources[company_id].remove(resource_name)
        
        # 知識ベースを完全にリセット
        print("知識ベースを完全にリセットします")
        knowledge_base.data = None
        knowledge_base.raw_text = ""
        knowledge_base.columns = []
        knowledge_base.url_data = []
        knowledge_base.url_texts = []
        knowledge_base.file_data = []
        knowledge_base.file_texts = []
        
        # 知識ベースをリフレッシュ
        await refresh_knowledge_base()
        
        # リフレッシュ後の状態を確認
        print(f"リフレッシュ後のデータフレームサイズ: {len(knowledge_base.data) if knowledge_base.data is not None else 0} 行")
        print(f"リフレッシュ後のURLデータ数: {len(knowledge_base.url_data)}")
        print(f"リフレッシュ後のファイルデータ数: {len(knowledge_base.file_data)}")
        
        return {
            "name": resource_name,
            "message": f"リソース '{resource_name}' を削除しました"
        }
    except HTTPException:
        raise
    except Exception as e:
        print(f"リソース削除エラー: {str(e)}")
        import traceback
        print(traceback.format_exc())
        raise HTTPException(status_code=500, detail=str(e))


async def get_uploaded_resources():
    """アップロードされたリソース（URL、PDF、Excel、TXT）の情報を取得する"""
    try:
        # デバッグ情報を出力
        print("リソース情報取得APIが呼び出されました")
        
        # 知識ベースからソース情報を取得
        sources = knowledge_base.sources
        source_info = knowledge_base.source_info
        print(f"取得したソース: {sources}")
        print(f"ソース情報: {source_info}")
        
        if not sources:
            print("ソースが見つかりませんでした")
            return {
                "resources": [],
                "message": "アップロードされたリソースがありません。"
            }
        
        # リソースの種類を判別
        resources = []
        for source in sources:
            resource_type = "URL"
            if source.endswith(('.pdf')):
                resource_type = "PDF"
            elif source.endswith(('.xlsx', '.xls')):
                resource_type = "Excel"
            elif source.endswith(('.txt')):
                resource_type = "TXT"
            
            # ソース情報を取得
            info = source_info.get(source, {})
            timestamp = info.get('timestamp', '')
            active = info.get('active', True)
            
            resources.append({
                "name": source,
                "type": resource_type,
                "timestamp": timestamp,
                "active": active
            })
        
        print(f"リソース情報取得結果: {len(resources)}件")
        return {
            "resources": resources,
            "message": f"{len(resources)}件のリソースが見つかりました。"
        }
    except Exception as e:
        print(f"リソース情報取得エラー: {str(e)}")
        import traceback
        print(traceback.format_exc())
        raise HTTPException(status_code=500, detail=str(e))
async def get_chat_history(user_id: str = None, db: Connection = Depends(get_db)):
    """チャット履歴を取得する
    
    Args:
        user_id: フィルタリングするユーザーID（指定がない場合は全ユーザーのデータを返す）
    """
    print(f"チャット履歴取得APIが呼び出されました (user_id: {user_id})")
    try:
        cursor = db.cursor(cursor_factory=RealDictCursor)
        
        # ユーザーIDが指定されている場合はフィルタリング
        if user_id:
            cursor.execute("SELECT * FROM chat_history WHERE employee_id = %s ORDER BY timestamp DESC", (user_id,))
            print(f"ユーザーID {user_id} でフィルタリングします")
        else:
            cursor.execute("SELECT * FROM chat_history ORDER BY timestamp DESC")
            print("全ユーザーのチャット履歴を取得します")
            
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

async def analyze_chats(user_id: str = None, db: Connection = Depends(get_db)):
    """チャット履歴を分析する
    Args:
        user_id: フィルタリングするユーザーID（指定がない場合は全ユーザーのデータを分析）
    """
    print(f"チャット分析APIが呼び出されました (user_id: {user_id})")
    try:
        cursor = db.cursor(cursor_factory=RealDictCursor)
        
        # ユーザーIDが指定されている場合はフィルタリング
        if user_id:
            cursor.execute("SELECT * FROM chat_history WHERE employee_id = %s ORDER BY timestamp DESC", (user_id,))
            print(f"ユーザーID {user_id} でフィルタリングします")
        else:
            cursor.execute("SELECT * FROM chat_history ORDER BY timestamp DESC")
            print("全ユーザーのチャット履歴を分析します")
            
        rows = cursor.fetchall()
        
        if not rows:
            return {
                "category_distribution": {},
                "sentiment_distribution": {},
                "common_questions": [],
                "insights": "チャット履歴がありません。",
                "filtered_by_user": user_id is not None
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
                "sentiment": row["sentiment"],
                "employee_id": row["employee_id"],
                "employee_name": row["employee_name"]
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
        import json
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
    
async def get_employee_details(employee_id: str, db: Connection = Depends(get_db), user_id: str = None):
    """特定の社員の詳細なチャット履歴を取得する"""
    try:
        cursor = db.cursor(cursor_factory=RealDictCursor)
        
        # 特別な管理者かどうかを確認
        is_special_admin = False
        if user_id:
            cursor.execute("SELECT email FROM users WHERE id = %s", (user_id,))
            user_email_row = cursor.fetchone()
            if user_email_row and user_email_row["email"] == "queue@queuefood.co.jp":
                is_special_admin = True
                print("特別な管理者として社員詳細情報を取得します")
        
        # 通常の管理者の場合、社員が同じ会社に所属しているか確認
        if not is_special_admin and user_id:
            # ユーザーの会社IDを取得
            cursor.execute("SELECT company_id FROM users WHERE id = %s", (user_id,))
            user_row = cursor.fetchone()
            user_company_id = user_row["company_id"] if user_row else None
            
            # 社員の会社IDを取得
            cursor.execute("SELECT company_id FROM users WHERE id = %s", (employee_id,))
            employee_row = cursor.fetchone()
            employee_company_id = employee_row["company_id"] if employee_row else None
            
            # 会社IDが一致しない場合はエラー
            if not user_company_id or not employee_company_id or user_company_id != employee_company_id:
                print(f"権限エラー: ユーザー {user_id} (会社ID: {user_company_id}) は社員 {employee_id} (会社ID: {employee_company_id}) の詳細を閲覧できません")
                raise HTTPException(
                    status_code=403,
                    detail="この社員の詳細を閲覧する権限がありません"
                )
        
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
            WHERE employee_id = %s
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
    except HTTPException:
        raise
    except Exception as e:
        print(f"社員詳細取得エラー: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))
        
async def get_company_employees(user_id: str = None, db: Connection = Depends(get_db), company_id: str = None):
    """会社の全社員情報を取得する"""
    try:
        cursor = db.cursor(cursor_factory=RealDictCursor)
        
        # 特別な管理者かどうかを確認
        is_special_admin = False
        if user_id:
            cursor.execute("SELECT email FROM users WHERE id = %s", (user_id,))
            user_email_row = cursor.fetchone()
            if user_email_row and user_email_row["email"] == "queue@queuefood.co.jp":
                is_special_admin = True
                print("特別な管理者として全社員情報を取得します")
        
        # 会社IDが直接指定されていない場合は、ユーザーの会社IDを取得
        if not company_id and user_id and not is_special_admin:
            cursor.execute("SELECT company_id FROM users WHERE id = %s", (user_id,))
            user_row = cursor.fetchone()
            if user_row and user_row["company_id"]:
                company_id = user_row["company_id"]
        
        if not company_id and not is_special_admin:
            raise HTTPException(status_code=400, detail="会社IDが見つかりません")
        
        # 特別な管理者の場合は全社員を取得
        if is_special_admin:
            print("特別な管理者として全社員情報を取得します")
            cursor.execute("""
            SELECT
                u.id,
                u.email,
                u.name,
                u.role,
                u.created_at,
                u.company_id,
                c.name as company_name,
                (SELECT COUNT(*) FROM chat_history WHERE employee_id = u.id) as message_count,
                (SELECT MAX(timestamp) FROM chat_history WHERE employee_id = u.id) as last_activity
            FROM users u
            LEFT JOIN companies c ON u.company_id = c.id
            ORDER BY u.role, u.name
            """)
        else:
            # 会社の全社員を取得
            print(f"会社ID {company_id} の社員情報を取得します")
            cursor.execute("""
            SELECT
                id,
                email,
                name,
                role,
                created_at,
                company_id,
                (SELECT name FROM companies WHERE id = users.company_id) as company_name,
                (SELECT COUNT(*) FROM chat_history WHERE employee_id = users.id) as message_count,
                (SELECT MAX(timestamp) FROM chat_history WHERE employee_id = users.id) as last_activity
            FROM users
            WHERE company_id = %s
            ORDER BY role, name
            """, (company_id,))
        
        employees = []
        for row in cursor.fetchall():
            # 利用制限情報を取得
            cursor.execute("""
            SELECT
                document_uploads_used,
                document_uploads_limit,
                questions_used,
                questions_limit,
                is_unlimited
            FROM usage_limits
            WHERE user_id = %s
            """, (row["id"],))
            
            limits_row = cursor.fetchone()
            usage_limits = {}
            
            if limits_row:
                usage_limits = {
                    "document_uploads_used": limits_row["document_uploads_used"],
                    "document_uploads_limit": limits_row["document_uploads_limit"],
                    "questions_used": limits_row["questions_used"],
                    "questions_limit": limits_row["questions_limit"],
                    "is_unlimited": bool(limits_row["is_unlimited"])
                }
            
            employees.append({
                "id": row["id"],
                "email": row["email"],
                "name": row["name"],
                "role": row["role"],
                "created_at": row["created_at"],
                "message_count": row["message_count"] or 0,
                "last_activity": row["last_activity"],
                "usage_limits": usage_limits
            })
        
        return {"employees": employees}
    except Exception as e:
        logger.error(f"社員情報の取得エラー: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

async def get_employee_usage(user_id: str = None, db: Connection = Depends(get_db), is_special_admin: bool = False):
    """社員ごとの利用状況を取得する"""
    print(f"社員利用状況APIが呼び出されました (user_id: {user_id}, is_special_admin: {is_special_admin})")
    try:
        cursor = db.cursor(cursor_factory=RealDictCursor)

        company_id = None
        if user_id and not is_special_admin:
            cursor.execute("SELECT company_id FROM users WHERE id = %s", (user_id,))
            user_row = cursor.fetchone()
            if user_row and user_row["company_id"]:
                company_id = user_row["company_id"]
                print(f"会社ID {company_id} でフィルタリングします")

        if is_special_admin:
            cursor.execute("""
            SELECT
                COALESCE(ch.employee_id, 'anonymous') as employee_id,
                COALESCE(ch.employee_name, '匿名ユーザー') as employee_name,
                COUNT(*) as message_count,
                MAX(ch.timestamp) as last_activity,
                STRING_AGG(ch.category, ',') as categories
            FROM chat_history ch
            GROUP BY COALESCE(ch.employee_id, 'anonymous'), COALESCE(ch.employee_name, '匿名ユーザー')
            ORDER BY message_count DESC
            """)
            print("特別な管理者として全ユーザーの利用状況を取得します")
        elif company_id:
            cursor.execute("""
            SELECT
                COALESCE(ch.employee_id, 'anonymous') as employee_id,
                COALESCE(ch.employee_name, '匿名ユーザー') as employee_name,
                COUNT(*) as message_count,
                MAX(ch.timestamp) as last_activity,
                STRING_AGG(ch.category, ',') as categories
            FROM chat_history ch
            JOIN users u ON ch.employee_id = u.id
            WHERE u.company_id = %s
            GROUP BY COALESCE(ch.employee_id, 'anonymous'), COALESCE(ch.employee_name, '匿名ユーザー')
            ORDER BY message_count DESC
            """, (company_id,))
            print(f"会社ID {company_id} の社員の利用状況を取得します")
        else:
            cursor.execute("""
            SELECT
                COALESCE(employee_id, 'anonymous') as employee_id,
                COALESCE(employee_name, '匿名ユーザー') as employee_name,
                COUNT(*) as message_count,
                MAX(timestamp) as last_activity,
                STRING_AGG(category, ',') as categories
            FROM chat_history
            WHERE employee_id = %s
            GROUP BY COALESCE(employee_id, 'anonymous'), COALESCE(employee_name, '匿名ユーザー')
            ORDER BY message_count DESC
            """, (user_id,))
            print(f"ユーザーID {user_id} でフィルタリングします")

        employee_rows = cursor.fetchall()

        if not employee_rows:
            return {"employee_usage": []}

        employee_usage = []

        for row in employee_rows:
            employee_id = row["employee_id"]
            employee_name = row["employee_name"]

            categories = row["categories"].split(',') if row["categories"] else []
            category_counts = {}

            for category in categories:
                if category:
                    category_counts[category] = category_counts.get(category, 0) + 1

            top_categories = [
                {"category": category, "count": count}
                for category, count in sorted(category_counts.items(), key=lambda x: x[1], reverse=True)[:3]
            ]

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
                WHERE employee_id = %s
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
