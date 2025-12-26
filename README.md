# YouTube to Whisper SRT Serverless Worker

A Runpod Serverless endpoint that transcribes YouTube videos to SRT/VTT format using OpenAI's Whisper model.

## Features

- Downloads audio from YouTube URLs using `yt-dlp`
- Transcribes audio using `whisper` with configurable language support
- **Multilingual support**: Transcribe in any Whisper-supported language (en, ko, ja, zh, etc.)
- Generates SRT subtitle files with timestamps
- Generates VTT files for web playback
- Uploads results to S3-compatible object storage (e.g., Railway S3-compatible bucket)
- Async job queue mode with status polling

## Input Specification

```json
{
  "input": {
    "youtube_url": "https://www.youtube.com/watch?v=...",
    "request_id": "unique-job-id",
    "language": "en",
    "s3_bucket": "my-bucket",
    "s3_key_prefix": "transcriptions/",
    "s3_endpoint_url": "https://s3.example.com",
    "aws_access_key": "...",
    "aws_secret_key": "..."
  }
}
```

### Input Parameters

- **youtube_url** (required): Full YouTube URL to transcribe
- **request_id** (required): Unique identifier for this job
- **language** (optional, default: `en`): ISO 639-1 language code for transcription
  - Supported languages: `en` (English), `ko` (Korean), `ja` (Japanese), `zh` (Chinese), and all other [Whisper-supported languages](https://github.com/openai/whisper#available-models-and-languages)
- **s3_bucket** (required): S3 bucket name for output
- **s3_key_prefix** (optional, default: `transcriptions/`): Prefix path in S3 bucket
- **s3_endpoint_url** (optional): Custom S3 endpoint URL for non-AWS S3-compatible storage
- **aws_access_key** (optional): AWS access key (can also be set via environment variable `AWS_ACCESS_KEY_ID`)
- **aws_secret_key** (optional): AWS secret key (can also be set via environment variable `AWS_SECRET_ACCESS_KEY`)

S3 credentials can be provided via input parameters or environment variables.

## Output Specification

```json
{
  "status": "done",
  "request_id": "unique-job-id",
  "language": "en",
  "srt_path": "s3://my-bucket/transcriptions/unique-job-id.srt",
  "srt_key": "transcriptions/unique-job-id.srt",
  "srt_bucket": "my-bucket",
  "raw_vtt_key": "storage/raw/VIDEO_ID.en.vtt",
  "raw_vtt_path": "s3://my-bucket/storage/raw/VIDEO_ID.en.vtt"
}
```

**Note:** The VTT filename includes the language code (e.g., `VIDEO_ID.ko.vtt` for Korean).

Or on error:

```json
{
  "status": "error",
  "request_id": "unique-job-id",
  "error": "error message"
}
```

## Environment Variables

Optional environment variables for S3 configuration:

- `AWS_ACCESS_KEY_ID`: AWS access key
- `AWS_SECRET_ACCESS_KEY`: AWS secret key
- `S3_BUCKET`: Default S3 bucket name
- `S3_ENDPOINT_URL`: Custom S3 endpoint URL

## Building

```bash
docker build -t hellergodric/yt-whisper-worker:latest .
```

The `--platform linux/amd64` flag is required for Runpod Serverless.

## Running Locally for Testing

```bash
docker run --gpus all \
  -e AWS_ACCESS_KEY_ID="your-key" \
  -e AWS_SECRET_ACCESS_KEY="your-secret" \
  -e S3_BUCKET="your-bucket" \
  hellergodric/yt-whisper-worker:latest
```

## Deployment to Runpod

1. Push the Docker image to Docker Hub (or your private registry)
2. In the [Runpod Console](https://www.console.runpod.io/serverless):
   - Click "New Endpoint"
   - Choose "Import Docker Image"
   - Enter the image URL: `docker.io/hellergodric/yt-whisper-worker:latest` (or your private registry URL)
   - Configure:
     - **Endpoint Name**: Choose a name (e.g., "yt-whisper")
     - **GPU Type**: A100, RTX 4090, or any GPU with CUDA 12.1 support
     - **Min vCPU**: 4
     - **Min Memory**: 20 GB
     - **Container Disk**: 50 GB
   - Add environment variables if using defaults for S3 configuration
   - Click "Create Endpoint"
3. Copy the Endpoint ID and save it to `~/yt_jobs/config/runpod_endpoint_id.txt`

## Local Job Runner Scripts

Once the endpoint is deployed, use these scripts to manage jobs:

### Start a Job
```bash
export RUNPOD_API_KEY="your-api-key"
JOB_ID=$(run_yt_job "https://www.youtube.com/watch?v=...")
echo "Started job: $JOB_ID"
```

### Check Job Status
```bash
check_yt_job "$JOB_ID"
```

### View Full Job Logs
```bash
dump_yt_job_log "$JOB_ID"
```

## Performance Notes

- First request will take ~2-3 minutes (model download and initialization)
- Subsequent requests are faster (~30-90 seconds depending on video length)
- Model caching happens at the worker level across multiple job invocations
- Max recommended video length: ~4 hours (tested up to this length)

## Dependencies

- **faster-whisper**: Efficient Whisper implementation
- **yt-dlp**: YouTube video downloader (better maintained than youtube-dl)
- **boto3**: AWS S3 client
- **runpod**: Runpod SDK

## License

MIT
