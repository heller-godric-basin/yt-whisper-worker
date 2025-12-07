FROM nvidia/cuda:12.1.1-runtime-ubuntu22.04

WORKDIR /

RUN apt-get update && apt-get install -y \
    python3.11 \
    python3-pip \
    ffmpeg \
    git \
    curl \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir \
    openai-whisper==20240930 \
    yt-dlp==2024.12.6 \
    pydub==0.25.1 \
    boto3==1.28.85 \
    runpod==1.5.4 \
    requests==2.31.0 \
    torch==2.4.1

ADD handler.py /handler.py

CMD ["python3", "-u", "/handler.py"]
