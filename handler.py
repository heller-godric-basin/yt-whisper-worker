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


def transcribe_to_srt(audio_path: str, model_name: str = "large") -> str:
    """
    Transcribe audio file to SRT format
    Returns the SRT content as a string
    """
    print(f"Transcribing audio file: {audio_path}")

    model = get_model(model_name)
    result = model.transcribe(audio_path, language="en", fp16=True)

    srt_content = []
    for idx, segment in enumerate(result["segments"], 1):
        start_time = format_timestamp(segment["start"])
        end_time = format_timestamp(segment["end"])
        text = segment["text"].strip()

        srt_content.append(f"{idx}\n{start_time} --> {end_time}\n{text}\n")

    return "\n".join(srt_content)


def download_youtube_audio(youtube_url: str, output_dir: str) -> str:
    """Download YouTube video and extract audio as MP3"""
    print(f"Downloading audio from: {youtube_url}")

    try:
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
            raise Exception("No MP3 file found after download")

        audio_path = str(mp3_files[0])
        print(f"Downloaded audio to: {audio_path}")
        return audio_path

    except Exception as e:
        raise Exception(f"Failed to download YouTube audio: {str(e)}")


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

        if not youtube_url:
            return {
                "status": "error",
                "error": "Missing required input: youtube_url",
                "request_id": request_id
            }

        # S3 configuration (can come from input or environment)
        s3_bucket = job_input.get("s3_bucket") or os.getenv("RUNPOD_SECRET_S3_BUCKET")
        s3_endpoint = job_input.get("s3_endpoint_url") or os.getenv("RUNPOD_SECRET_S3_ENDPOINT_URL")
        s3_key_prefix = job_input.get("s3_key_prefix", "transcriptions/")
        aws_access_key = job_input.get("aws_access_key") or os.getenv("RUNPOD_SECRET_AWS_ACCESS_KEY_ID")
        aws_secret_key = job_input.get("aws_secret_key") or os.getenv("RUNPOD_SECRET_AWS_SECRET_ACCESS_KEY")

        if not s3_bucket:
            return {
                "status": "error",
                "error": "S3 bucket not configured",
                "request_id": request_id
            }

        with tempfile.TemporaryDirectory() as tmpdir:
            # Step 1: Download audio from YouTube
            audio_path = download_youtube_audio(youtube_url, tmpdir)

            # Step 2: Transcribe to SRT
            srt_content = transcribe_to_srt(audio_path)

            # Step 3: Save SRT locally and upload to S3
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

        return {
            "status": "done",
            "request_id": request_id,
            "srt_path": s3_path,
            "srt_key": s3_key,
            "srt_bucket": s3_bucket
        }

    except Exception as e:
        print(f"Handler error: {str(e)}", file=sys.stderr)
        return {
            "status": "error",
            "error": str(e),
            "request_id": event.get("input", {}).get("request_id", "unknown")
        }


if __name__ == "__main__":
    print("Starting Runpod Serverless handler for YouTube Whisper transcription")
    runpod.serverless.start({"handler": handler})
