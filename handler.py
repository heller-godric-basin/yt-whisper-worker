#!/usr/bin/env python3
"""
Runpod Serverless Handler for YouTube → Whisper → SRT pipeline
Transcribes YouTube videos to English and uploads SRT files to S3-compatible storage
"""

import os
import sys
import json
import tempfile
import subprocess
import re
from pathlib import Path
from datetime import timedelta
from typing import Optional, Dict, Any

import runpod
import boto3
import whisper

# Global model cache
current_model = None
current_model_name = None


def get_model(model_name: str = "large"):
    """Load and cache Whisper model"""
    global current_model, current_model_name

    if current_model is not None and current_model_name == model_name:
        return current_model

    print(f"Loading Whisper model: {model_name}")
    current_model = whisper.load_model(model_name, device="cuda")
    current_model_name = model_name
    return current_model


def format_timestamp(seconds: float) -> str:
    """Convert seconds to SRT timestamp format (HH:MM:SS,mmm)"""
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    millis = int((seconds % 1) * 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


def transcribe_to_srt(audio_path: str, model_name: str = "large", language: str = "en") -> str:
    """
    Transcribe audio file to SRT format
    Returns the SRT content as a string

    Args:
        audio_path: Path to audio file
        model_name: Whisper model name (default: "large")
        language: ISO 639-1 language code for transcription (default: "en")
                  Supported: en, ko, ja, zh, etc. (all Whisper-supported languages)
    """
    print(f"Transcribing audio file: {audio_path} (language: {language})")

    model = get_model(model_name)
    result = model.transcribe(audio_path, language=language, fp16=True)

    srt_content = []
    for idx, segment in enumerate(result["segments"], 1):
        start_time = format_timestamp(segment["start"])
        end_time = format_timestamp(segment["end"])
        text = segment["text"].strip()

        srt_content.append(f"{idx}\n{start_time} --> {end_time}\n{text}\n")

    return "\n".join(srt_content)


def srt_to_vtt(srt_content: str) -> str:
    """
    Convert SRT format to WebVTT format
    WebVTT header + SRT content with timestamp adjustments
    """
    vtt_lines = ["WEBVTT", "", ""]

    for line in srt_content.split("\n"):
        if line.strip() == "":
            vtt_lines.append("")
        elif "-->" in line:
            # Convert SRT timestamp (HH:MM:SS,mmm) to VTT timestamp (HH:MM:SS.mmm)
            vtt_timestamp = line.replace(",", ".")
            vtt_lines.append(vtt_timestamp)
        else:
            vtt_lines.append(line)

    return "\n".join(vtt_lines)


def extract_video_id(youtube_url: str) -> str:
    """
    Extract YouTube video ID from various URL formats
    Supports: youtube.com/watch?v=... and youtu.be/...
    """
    pattern = r'(?:youtube\.com\/watch\?v=|youtu\.be\/)([0-9A-Za-z_-]{11})'
    match = re.search(pattern, youtube_url)
    if match:
        return match.group(1)
    raise ValueError(f"Could not extract video ID from URL: {youtube_url}")


def _download_with_ytdlp(youtube_url: str, output_dir: str) -> str:
    """Download YouTube audio using yt-dlp"""
    output_template = os.path.join(output_dir, "%(title)s.%(ext)s")
    result = subprocess.run(
        [
            "yt-dlp",
            "-f", "bestaudio/best",
            "-x",
            "--audio-format", "mp3",
            "--audio-quality", "192",
            "-o", output_template,
            youtube_url
        ],
        capture_output=True,
        text=True,
        timeout=300
    )

    if result.returncode != 0:
        raise Exception(f"yt-dlp failed: {result.stderr}")

    # Find the downloaded audio file
    mp3_files = list(Path(output_dir).glob("*.mp3"))
    if not mp3_files:
        raise Exception("No MP3 file found after yt-dlp download")

    return str(mp3_files[0])


def _download_with_pytube(youtube_url: str, output_dir: str) -> str:
    """Download YouTube audio using pytubefix (fallback)"""
    from pytubefix import YouTube

    yt = YouTube(youtube_url)

    # Get audio-only stream (highest bitrate)
    audio_stream = yt.streams.filter(only_audio=True).order_by('abr').desc().first()

    if not audio_stream:
        raise Exception("No audio stream found via pytube")

    # Download to output directory
    downloaded_path = audio_stream.download(output_path=output_dir)
    print(f"pytube downloaded: {downloaded_path}")

    # Convert to mp3 if needed (pytube downloads as m4a/webm)
    output_path = Path(downloaded_path)
    if output_path.suffix.lower() != '.mp3':
        mp3_path = output_path.with_suffix('.mp3')
        # Use ffmpeg to convert
        result = subprocess.run(
            ['ffmpeg', '-i', str(output_path), '-vn', '-acodec', 'libmp3lame', '-q:a', '2', str(mp3_path)],
            capture_output=True,
            text=True,
            timeout=120
        )
        if result.returncode != 0:
            # If ffmpeg fails, try using pydub
            from pydub import AudioSegment
            audio = AudioSegment.from_file(str(output_path))
            audio.export(str(mp3_path), format='mp3', bitrate='192k')

        # Remove original file
        output_path.unlink()
        return str(mp3_path)

    return downloaded_path


def download_youtube_audio(youtube_url: str, output_dir: str) -> str:
    """Download YouTube video audio - tries yt-dlp first, falls back to pytube"""
    print(f"Downloading audio from: {youtube_url}")

    # Try yt-dlp first (generally more reliable and faster)
    try:
        audio_path = _download_with_ytdlp(youtube_url, output_dir)
        print(f"Downloaded audio via yt-dlp: {audio_path}")
        return audio_path
    except Exception as e:
        print(f"yt-dlp failed: {e}")
        print("Attempting pytube fallback...")

    # Fallback to pytube
    try:
        audio_path = _download_with_pytube(youtube_url, output_dir)
        print(f"Downloaded audio via pytube fallback: {audio_path}")
        return audio_path
    except Exception as e:
        raise Exception(f"All download methods failed. yt-dlp and pytube both failed. Last error: {str(e)}")


def upload_to_s3(
    file_path: str,
    bucket: str,
    key: str,
    endpoint_url: Optional[str] = None,
    aws_access_key: Optional[str] = None,
    aws_secret_key: Optional[str] = None
) -> str:
    """Upload file to S3-compatible storage and return the S3 path"""
    print(f"Uploading to S3: s3://{bucket}/{key}")

    s3_kwargs = {}
    if endpoint_url:
        s3_kwargs["endpoint_url"] = endpoint_url
    if aws_access_key and aws_secret_key:
        s3_kwargs["aws_access_key_id"] = aws_access_key
        s3_kwargs["aws_secret_access_key"] = aws_secret_key

    s3_client = boto3.client("s3", **s3_kwargs)

    try:
        s3_client.upload_file(file_path, bucket, key)
        print(f"Successfully uploaded to s3://{bucket}/{key}")
        return f"s3://{bucket}/{key}"
    except Exception as e:
        raise Exception(f"S3 upload failed: {str(e)}")


def handler(event: Dict[str, Any]) -> Dict[str, Any]:
    """
    Runpod handler function

    Input format:
    {
        "youtube_url": "https://www.youtube.com/watch?v=...",
        "request_id": "job-id",
        "language": "en",  // ISO 639-1 code: en, ko, ja, zh, etc. (default: "en")
        "s3_bucket": "my-bucket",
        "s3_key_prefix": "transcriptions/",
        "s3_endpoint_url": "https://s3.example.com",
        "aws_access_key": "...",
        "aws_secret_key": "..."
    }
    """
    try:
        job_input = event.get("input", {})

        youtube_url = job_input.get("youtube_url")
        request_id = job_input.get("request_id", "unknown")
        language = job_input.get("language", "en")  # ISO 639-1 code (default: English)

        print(f"Processing request: {request_id}, language: {language}")

        if not youtube_url:
            return {
                "status": "error",
                "error": "Missing required input: youtube_url",
                "request_id": request_id
            }

        # Debug: Print all RUNPOD_SECRET_ environment variables
        print("DEBUG: Checking for RUNPOD_SECRET_ environment variables:")
        for key, value in os.environ.items():
            if key.startswith("RUNPOD_SECRET_"):
                print(f"  {key}: {'***' if 'SECRET' in key or 'KEY' in key else value}")

        # S3 configuration (can come from input or environment)
        s3_bucket = job_input.get("s3_bucket") or os.getenv("RUNPOD_SECRET_S3_BUCKET")
        s3_endpoint = job_input.get("s3_endpoint_url") or os.getenv("RUNPOD_SECRET_S3_ENDPOINT_URL")
        s3_key_prefix = job_input.get("s3_key_prefix", "transcriptions/")
        aws_access_key = job_input.get("aws_access_key") or os.getenv("RUNPOD_SECRET_AWS_ACCESS_KEY_ID")
        aws_secret_key = job_input.get("aws_secret_key") or os.getenv("RUNPOD_SECRET_AWS_SECRET_ACCESS_KEY")

        print(f"DEBUG: s3_bucket = {s3_bucket}")
        print(f"DEBUG: s3_endpoint = {s3_endpoint}")
        print(f"DEBUG: aws_access_key = {'***' if aws_access_key else None}")
        print(f"DEBUG: aws_secret_key = {'***' if aws_secret_key else None}")

        if not s3_bucket:
            return {
                "status": "error",
                "error": "S3 bucket not configured",
                "request_id": request_id
            }

        with tempfile.TemporaryDirectory() as tmpdir:
            # Step 1: Download audio from YouTube
            audio_path = download_youtube_audio(youtube_url, tmpdir)

            # Step 2: Transcribe to SRT in specified language
            srt_content = transcribe_to_srt(audio_path, language=language)

            # Step 3: Extract video_id from YouTube URL
            video_id = extract_video_id(youtube_url)
            print(f"Extracted video_id: {video_id}")

            # Step 4: Save SRT locally and upload to S3
            srt_filename = f"{request_id}.srt"
            srt_local_path = os.path.join(tmpdir, srt_filename)
            with open(srt_local_path, "w") as f:
                f.write(srt_content)

            s3_key = f"{s3_key_prefix}{srt_filename}"
            s3_path = upload_to_s3(
                srt_local_path,
                s3_bucket,
                s3_key,
                endpoint_url=s3_endpoint,
                aws_access_key=aws_access_key,
                aws_secret_key=aws_secret_key
            )

            # Step 5: Convert SRT to VTT and upload raw VTT to storage/raw/
            vtt_content = srt_to_vtt(srt_content)
            vtt_filename = f"{video_id}.{language}.vtt"  # Use language code in filename
            vtt_local_path = os.path.join(tmpdir, vtt_filename)
            with open(vtt_local_path, "w") as f:
                f.write(vtt_content)

            raw_vtt_key = f"storage/raw/{vtt_filename}"
            raw_vtt_path = upload_to_s3(
                vtt_local_path,
                s3_bucket,
                raw_vtt_key,
                endpoint_url=s3_endpoint,
                aws_access_key=aws_access_key,
                aws_secret_key=aws_secret_key
            )
            print(f"Uploaded raw VTT to: {raw_vtt_path}")

        return {
            "status": "done",
            "request_id": request_id,
            "language": language,
            "srt_path": s3_path,
            "srt_key": s3_key,
            "srt_bucket": s3_bucket,
            "raw_vtt_key": raw_vtt_key,
            "raw_vtt_path": raw_vtt_path
        }

    except Exception as e:
        print(f"Handler error: {str(e)}", file=sys.stderr)
        return {
            "status": "error",
            "error": str(e),
            "request_id": event.get("input", {}).get("request_id", "unknown")
        }


if __name__ == "__main__":
    print("Starting Runpod Serverless handler for YouTube Whisper transcription v1")
    runpod.serverless.start({"handler": handler})
