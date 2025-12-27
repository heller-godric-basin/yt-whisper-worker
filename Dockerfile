FROM nvidia/cuda:12.1.1-runtime-ubuntu22.04

WORKDIR /

RUN apt-get update && apt-get install -y \
    python3.11 \
    python3-pip \
    ffmpeg \
    git \
    curl \
    && rm -rf /var/lib/apt/lists/*

ADD requirements.txt /requirements.txt
RUN pip install --no-cache-dir -r /requirements.txt

ADD handler.py /handler.py

CMD ["python3", "-u", "/handler.py"]
