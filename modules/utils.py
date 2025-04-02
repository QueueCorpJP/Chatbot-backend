import requests
import re
from bs4 import BeautifulSoup
from youtube_transcript_api import YouTubeTranscriptApi
from youtube_transcript_api.proxies import WebshareProxyConfig

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
        transcript = ytt_api.get_transcript(video_id)
        full_text = "\n".join([item['text'] for item in transcript])
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
