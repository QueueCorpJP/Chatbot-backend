import requests
import re
from bs4 import BeautifulSoup
from youtube_transcript_api import YouTubeTranscriptApi
from youtube_transcript_api.proxies import WebshareProxyConfig
from io import BytesIO
import pandas as pd
import time
from dotenv import load_dotenv
import os
from playwright.async_api import async_playwright
import fitz
import tempfile

load_dotenv()

WEBSHAREPROXY_USERNAME = os.getenv("WEBSHAREPROXY_USERNAME")
WEBSHAREPROXY_PASSWORD = os.getenv("WEBSHAREPROXY_PASSWORD")
ASSEMBLYAI_API_KEY = os.getenv("ASSEMBLYAI_API_KEY")

ytt_api = YouTubeTranscriptApi(
    proxy_config=WebshareProxyConfig(
        proxy_username=WEBSHAREPROXY_USERNAME,
        proxy_password=WEBSHAREPROXY_PASSWORD,
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

        return full_text
    except Exception as e:
        print(f"Error: {str(e)}")
        return f"Error: {str(e)}"

async def extract_text_from_html(url: str) -> str:
    # headers = {
    #     'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
    # }
    # response = requests.get(url, headers=headers, timeout=10)
    # response.raise_for_status()  # エラーがあれば例外を発生
    # response.encoding = response.apparent_encoding
    # # HTMLをパース
    # soup = BeautifulSoup(response.text, 'html.parser')
    
    # # 不要なタグを削除
    # for tag in soup(['script', 'style', 'meta', 'link', 'noscript', 'header', 'footer', 'nav']):
    #     tag.decompose()
    
    # # テキストを抽出
    # text = soup.get_text(separator='\n')
    #  # 余分な空白と改行を整理
    # text = re.sub(r'\n+', '\n', text)
    # text = re.sub(r' +', ' ', text)
    
    # # タイトルを取得
    # title = soup.title.string if soup.title else "タイトルなし"
    # print("xxxxxxxxxxx")
    # print(text)
    # # URLとタイトルを含めたテキストを返す
    # return f"=== URL: {url} ===\n=== タイトル: {title} ===\n\n{text}"
   
    playwright = await async_playwright().start()  # ✅ await before using
    browser = await playwright.chromium.launch(headless=True)
    page = await browser.new_page()
    await page.goto(url, timeout=45000, wait_until="domcontentloaded")
    await page.wait_for_timeout(3000)

    html = await page.content()
    await browser.close()
    await playwright.stop() 
    # Check for permission-denied indicators before parsing
    
    if any(msg in html for msg in [
        "You need access", 
        "Request access", 
        "You don’t have access", 
        "Sign in to continue", 
        "Sign into continue", 
        "To view this document",
        "Use a private browsing window to sign in"
    ]):
        raise PermissionError(f"Permission denied: You don't have access to this Google Doc → {url}")

    soup = BeautifulSoup(html, "html.parser")

    for tag in soup(['script', 'style', 'meta', 'link', 'noscript', 'header', 'footer', 'nav']):
        tag.decompose()

    text = soup.get_text(separator='\n')
    text = re.sub(r'\n+', '\n', text)
    text = re.sub(r' +', ' ', text)

    title = soup.title.string.strip() if soup.title and soup.title.string else "No Title"
    return f"=== URL: {url} ===\n=== Title: {title} ===\n\n{text}"

async def extract_text_from_pdf(url: str) -> str:
    response = requests.get(url)
    if response.status_code != 200:
        raise Exception(f"Failed to download PDF: {url}")

    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
        tmp.write(response.content)
        tmp_path = tmp.name

    try:
        text = ""
        with fitz.open(tmp_path) as doc:
            for page in doc:
                text += page.get_text()
    finally:
        os.remove(tmp_path)  # Clean up the file after reading

    return f"=== URL: {url} ===\n=== Title: PDF Document ===\n\n{text.strip()}"

def _process_video_file(contents, filename):
    """Excelファイルを処理してデータフレーム、セクション、テキストを返す"""
    try:
        video_file = BytesIO(contents)
        
        df_dict = transcribe_video_file(video_file)
        sections = {}
        extracted_text = f"=== ファイル: {filename} ===\n\n"

        result_df = pd.DataFrame({
            'section': ["一般情報"], 'content': [df_dict], 'source': ['Video'], 'file': [filename], 'url': [None]
        })
        
        return result_df, sections, extracted_text
    except Exception as e:
        print(f"Videoファイル処理エラー: {str(e)}")
        import traceback
        print(traceback.format_exc())
        raise

# Headers for AssemblyAI API
HEADERS = {
    "authorization": ASSEMBLYAI_API_KEY,
    "content-type": "application/json"
}

def upload_to_assemblyai(video_file: BytesIO) -> str:
    """
    Uploads video file to AssemblyAI and returns the upload URL.
    """
    upload_url = "https://api.assemblyai.com/v2/upload"

    response = requests.post(
        upload_url,
        headers={"authorization": ASSEMBLYAI_API_KEY},
        data=video_file
    )

    response.raise_for_status()
    return response.json()['upload_url']

def start_transcription(upload_url: str) -> str:
    """
    Starts the transcription job and returns the transcript ID.
    """
    transcript_endpoint = "https://api.assemblyai.com/v2/transcript"
    json_data = {
        "audio_url": upload_url
    }

    response = requests.post(transcript_endpoint, json=json_data, headers=HEADERS)
    response.raise_for_status()
    return response.json()["id"]

def poll_transcription(transcript_id: str) -> dict:
    """
    Polls the transcript endpoint until transcription is completed.
    """
    polling_endpoint = f"https://api.assemblyai.com/v2/transcript/{transcript_id}"

    while True:
        response = requests.get(polling_endpoint, headers=HEADERS)
        response.raise_for_status()
        data = response.json()

        if data["status"] == "completed":
            return data
        elif data["status"] == "error":
            raise RuntimeError(f"Transcription failed: {data['error']}")

        time.sleep(3)  # Wait a few seconds before checking again

def transcribe_video_file(video_file: BytesIO) -> str:
    """
    Main function to handle the full transcription pipeline.
    """
    print("Uploading video...")
    upload_url = upload_to_assemblyai(video_file)

    print("Starting transcription...")
    transcript_id = start_transcription(upload_url)

    print("Waiting for transcription to complete...")
    transcript_data = poll_transcription(transcript_id)

    return transcript_data["text"]

