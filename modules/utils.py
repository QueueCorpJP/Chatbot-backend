import requests
import re
from bs4 import BeautifulSoup
from youtube_transcript_api import YouTubeTranscriptApi
from youtube_transcript_api.proxies import WebshareProxyConfig
from io import BytesIO

ytt_api = YouTubeTranscriptApi(
    proxy_config=WebshareProxyConfig(
        proxy_username="xvxgfoll",
        proxy_password="t629a21sw1rt",
    )
)
# Function to extract video ID from a full YouTube URL
def get_video_id(youtube_url):
    import re
    match = re.search(r'(?:v=|\/)([0-9A-Za-z_-]{11}).*', youtube_url)
    return match.group(1) if match else None

def transcribe_youtube_video(youtube_url: str) -> str:
    video_id = get_video_id(youtube_url)
    if not video_id:
        return "Invalid YouTube URL."
    
    try:
        transcript = ytt_api.fetch(video_id, languages=['ja', 'en', 'ja-Hira', 'a.en'])

        full_text = "\n".join([snippet.text for snippet in transcript.snippets])

        print(full_text)
        return full_text
    except Exception as e:
        print(f"Error: {str(e)}")
        return f"Error: {str(e)}"

def extract_text_from_html(url: str) -> str:
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
    }
    response = requests.get(url, headers=headers, timeout=10)
    response.raise_for_status()  # エラーがあれば例外を発生
    
    # HTMLをパース
    soup = BeautifulSoup(response.text, 'html.parser')
    
    # 不要なタグを削除
    for tag in soup(['script', 'style', 'meta', 'link', 'noscript', 'header', 'footer', 'nav']):
        tag.decompose()
    
    # テキストを抽出
    text = soup.get_text(separator='\n')
     # 余分な空白と改行を整理
    text = re.sub(r'\n+', '\n', text)
    text = re.sub(r' +', ' ', text)
    
    # タイトルを取得
    title = soup.title.string if soup.title else "タイトルなし"
    
    # URLとタイトルを含めたテキストを返す
    return f"=== URL: {url} ===\n=== タイトル: {title} ===\n\n{text}"


# Excelファイルを処理する内部関数
def _process_video_file(contents, filename):
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
