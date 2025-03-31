import requests
import time
from dotenv import load_dotenv
import os
import re
from bs4 import BeautifulSoup
import boto3
from io import BytesIO
from urllib.parse import quote
import yt_dlp
import subprocess

# 環境変数の読み込み
load_dotenv()

assemble_api_key = os.getenv("ASSEMBLE_API_KEY")

S3_BUCKET_NAME = "chatbot-v-script"
S3_REGION = "ap-northeast-1"

s3_client = boto3.client(
    "s3",
    aws_access_key_id = "AKIAXZ5NGNP32W27TK4R",
    aws_secret_access_key = "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",
    region_name = S3_REGION
)

def upload_youtube_audio_to_s3(youtube_url: str, s3_key: str) -> str:
    """Download YouTube audio and upload to S3, return public URL."""
    try:
        print(f"Downloading audio from: {youtube_url}")
        buffer = BytesIO()
        ydl_opts = {
            'format': 'bestaudio/best',
            'quiet': True,
            'noplaylist': True,
            'cookiefile': '/cookies_txt-0.8.xpi',
            'postprocessors': [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '192',
            }],
            'logtostderr': False,
        }

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(youtube_url, download=False)
            audio_url = info['url']

        buffer = BytesIO()
        # ffmpeg_cmd = [
        #     r'C:\ffmpeg\bin\ffmpeg.exe', '-i', audio_url,
        #     '-f', 'mp3', '-ab', '192k',
        #     '-hide_banner', '-loglevel', 'error',
        #     'pipe:1'  # Output to stdout
        # ]
        ffmpeg_cmd = [
            'ffmpeg', '-i', audio_url,
            '-f', 'mp3', '-ab', '192k',
            '-hide_banner', '-loglevel', 'error',
            'pipe:1'  # Output to stdout
        ]

        process = subprocess.Popen(ffmpeg_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        stdout, stderr = process.communicate()  # Capture both stdout and stderr
        
        if process.returncode != 0:
            print(f"FFmpeg stderr: {stderr.decode('utf-8', errors='ignore')}")
            return 'null'
        buffer.write(process.communicate()[0])
        buffer.seek(0)

        print(f"before boto3")
        s3_client.upload_fileobj(
            Fileobj=buffer,
            Bucket=S3_BUCKET_NAME,
            Key=s3_key,
            ExtraArgs={
                'ContentType': 'audio/mp3'
            }
        )
        return f"https://{S3_BUCKET_NAME}.s3.{S3_REGION}.amazonaws.com/{quote(s3_key)}"
    except Exception as e:
        print('Error in upload_youtube_audio_to_s3:::', e)
        return 'null'


def transcribe_from_audio_url(audio_url: str) -> str:
    """Send audio URL to AssemblyAI and return transcript text."""
    headers = {
        "authorization": assemble_api_key,
        "content-type": "application/json"
    }

    response = requests.post(
        "https://api.assemblyai.com/v2/transcript",
        headers=headers,
        json={"audio_url": audio_url}
    )
    response.raise_for_status()
    transcript_id = response.json()["id"]

    while True:
        poll = requests.get(f"https://api.assemblyai.com/v2/transcript/{transcript_id}", headers=headers)
        poll.raise_for_status()
        status = poll.json()["status"]

        if status == "completed":
            return poll.json()["text"]
        elif status == "error":
            raise Exception("Transcription failed: " + poll.json()["error"])

        time.sleep(3)

def transcribe_youtube_video(youtube_url: str) -> str:
    """Complete flow: YouTube → S3 → AssemblyAI → Transcript"""
    video_id = YouTube(youtube_url).video_id
    s3_key = f"youtube_audio/{video_id}.mp3"

    print("Uploading to S3...")
    s3_url = upload_youtube_audio_to_s3(youtube_url, s3_key)
    print("Uploaded to:", s3_url)
    print("Transcribing...")
    transcript = transcribe_from_audio_url(s3_url)
    print("Transcription completed.")
    return transcript

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