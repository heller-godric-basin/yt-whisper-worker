# Deployment Guide for Runpod Serverless

## Step 1: Prepare the Repository

This repository contains everything needed to deploy a YouTube → Whisper → SRT serverless endpoint on Runpod.

## Step 2: Deploy via Runpod Console

1. **Create New Endpoint**
   - Go to https://www.console.runpod.io/serverless
   - Click **"New Endpoint"**

2. **Choose Deployment Source**
   - Select **"Import from Docker Registry"** (or **"GitHub"** if integrated)
   - Use the Docker image from Docker Hub or your private registry

3. **Configure Docker Image**
   - **Docker Image URL**:
     - Public: `docker.io/hellergodric/yt-whisper-worker:latest`
     - Private: Your private registry URL
   - **Image Credentials**: Only needed for private registries

4. **Configure Endpoint Settings**
   - **Endpoint Name**: e.g., `yt-whisper` or `youtube-transcriber`
   - **Endpoint Type**: `Queue` (recommended for async jobs)
   - **Min Workers**: 1
   - **Max Workers**: 3-5 (adjust based on budget)

5. **Configure GPU and Hardware**
   - **GPU Type**:
     - Recommended: NVIDIA A100 (best performance)
     - Budget-friendly: NVIDIA RTX 4090 or RTX 3090
   - **GPU Count**: 1
   - **Min vCPU Count**: 4
   - **Min Memory (GB)**: 20
   - **Container Disk (GB)**: 50
   - **Volume Disk (GB)**: 0 (not needed)

6. **Set Environment Variables** (optional, can also pass via API)
   - `AWS_ACCESS_KEY_ID`: Your AWS/S3 access key
   - `AWS_SECRET_ACCESS_KEY`: Your AWS/S3 secret key
   - `S3_BUCKET`: Default S3 bucket name
   - `S3_ENDPOINT_URL`: Custom S3 endpoint (if using non-AWS S3)

7. **Configure Container Entrypoint** (if needed)
   - Default should work: `python -u /handler.py`

8. **Review and Create**
   - Review all settings
   - Click **"Create Endpoint"**
   - Wait for the endpoint to become active (usually 2-3 minutes)

## Step 3: Get Your Endpoint ID

Once the endpoint is active:
1. Copy the **Endpoint ID** from the endpoint details
2. Save it to your local machine:
   ```bash
   echo "your-endpoint-id-here" > ~/yt_jobs/config/runpod_endpoint_id.txt
   ```

## Step 4: Test the Endpoint

Export your Runpod API key and test a job:

```bash
export RUNPOD_API_KEY="your-runpod-api-key"

# Start a test job
JOB_ID=$(run_yt_job "https://www.youtube.com/watch?v=dQw4w9WgXcQ")
echo "Job ID: $JOB_ID"

# Check status
check_yt_job "$JOB_ID"

# Wait a moment, then check again
sleep 60
check_yt_job "$JOB_ID"

# View full logs
dump_yt_job_log "$JOB_ID"
```

## Step 5: Monitor and Manage

### Check Endpoint Health
- Visit https://www.console.runpod.io/serverless
- Your endpoint should show active worker count and request queue

### View Logs
- Click on your endpoint in the console
- View worker logs and request history

### Adjust Configuration
- Go to endpoint settings to adjust:
  - Min/max workers
  - GPU type or count
  - Environment variables
  - Bid price (for interruptible instances)

## Troubleshooting

### Endpoint Won't Start
- Check that the Docker image exists and is accessible
- Verify GPU availability (some GPU types may be out of stock)
- Check container resource requirements aren't too high

### Jobs Timeout
- Increase container disk if model download is timing out
- Check that S3 credentials are correct
- Verify network connectivity to S3

### Image Pull Failures
- For private images, ensure credentials are provided
- Check image URL format: `registry.io/username/image:tag`
- Verify image exists in registry

### Model Download Takes Too Long
- First job load may take 2-3 minutes (normal)
- Subsequent jobs cache the model and are faster
- Consider pre-downloading model during image build (increases build time)

## Cost Optimization

### Choose Right GPU
- A100: Most expensive but fastest
- RTX 4090: Good balance of price and performance
- RTX 3090: Budget option but slower

### Use Interruptible Instances
- Set lower bid prices to save 50-80% on costs
- Runpod automatically retries failed jobs
- Good for non-time-sensitive batch processing

### Monitor Usage
- Check dashboard for actual hourly costs
- Adjust worker scaling based on queue depth
- Consider scheduled jobs during off-peak hours

## Next Steps

After deployment:
1. Create n8n workflows to invoke the endpoint
2. Set up monitoring/alerting for job failures
3. Build UI dashboard to track transcription jobs
4. Integrate with downstream translation services
