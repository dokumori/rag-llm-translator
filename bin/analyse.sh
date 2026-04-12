#!/bin/bash
set -e

# Define paths
LOG_FILE_HOST="data/logs/translation.jsonl"
LOG_FILE_CONTAINER="/app/data/logs/translation.jsonl"
ANALYSER_SCRIPT="/app/src/analyse_logs.py"

# 0. Check if .env is newer than the container
if [ -f .env ]; then
  # Grab the Create time of the container as a UNIX Epoch
  # Use python to do the comparison across standard library so it works perfectly on Mac/Linux without date util dependency issues.
  if command -v docker &> /dev/null && command -v python3 &> /dev/null; then
    python3 -c '
import os, json, datetime
try:
    env_mtime = os.path.getmtime(".env")
    out = os.popen("docker inspect rag-proxy 2>/dev/null").read()
    if out:
        data = json.loads(out)
        created_str = data[0].get("Created", "")
        dt = datetime.datetime.fromisoformat(created_str.replace("Z", "+00:00"))
        container_time = dt.timestamp()
        if env_mtime > container_time:
            print("\u26a0\ufe0f  Warning: Your .env file is newer than the rag-proxy container.")
            print("   If you changed RAG thresholds, the current logs reflect outdated settings.")
            print("   See docs/3_RAG_performance_analysis.md for the manual tuning workflow.\n")
except Exception:
    pass'
  fi
fi

# 1. Capture Logs (Disable colour codes to fix parsing issues)
echo "📊 Capturing logs from rag-proxy..."
mkdir -p data/logs
docker compose logs --no-color --no-log-prefix rag-proxy > "$LOG_FILE_HOST"

# 2. Check if logs are empty
if [ ! -s "$LOG_FILE_HOST" ]; then
  echo "❌ Error: Log file is empty. No traffic captured."
  exit 1
fi

# 3. Send logs to toolbox
echo "🚚 Sending logs to toolbox container..."
docker compose exec -u 0 toolbox mkdir -p /app/data/logs

# 4. Run Analysis
echo "🚀 Running analysis inside toolbox..."
# We capture the output to extract the generated report filename
OUTPUT=$(docker compose exec toolbox python3 "$ANALYSER_SCRIPT" "$LOG_FILE_CONTAINER")
echo "$OUTPUT"

# 5. Verify and Retrieve Reports
REPORT_FILE_CONTAINER=$(echo "$OUTPUT" | grep "REPORT_FILE=" | cut -d'=' -f2 | tr -d '\r')

if [ -n "$REPORT_FILE_CONTAINER" ]; then
  # Although volume mapped, we explicitly confirm the file exists on host
  REPORT_FILE_HOST="data/rag-analysis/$(basename "$REPORT_FILE_CONTAINER")"
  
  if [ -f "$REPORT_FILE_HOST" ]; then
    echo "✅ Success! New report generated: $REPORT_FILE_HOST"
    echo "📂 All artifacts are ready at: data/rag-analysis/"
  else
    echo "⚠️ Report generated in container but not found on host. Check volume mounts."
  fi
else
  echo "❌ Error: Analysis failed to generate a report file."
  exit 1
fi

# 6. Optional: Purge Logs
if [ -t 0 ]; then
  # Interactive mode 
  echo ""
  read -p "Purge logs for a clean next run? This will recreate the rag-proxy container. Any running translation process will be stopped. (y/N) " prompt
  if [[ "$prompt" =~ ^[Yy]$ ]]; then
    echo "🔄 Recreating rag-proxy container..."
    if docker compose up -d --force-recreate rag-proxy; then
      echo -n "⏳ Waiting for rag-proxy to become healthy"
      
      # Healthcheck polling loop (up to 90 seconds)
      timeout=90
      elapsed=0
      while [ $elapsed -lt $timeout ]; do
        STATUS=$(docker inspect --format='{{.State.Health.Status}}' rag-proxy 2>/dev/null || echo "error")
        if [ "$STATUS" = "healthy" ]; then
          echo -e "\n✅ rag-proxy is back online and healthy. Logs have been purged."
          rm -f "$LOG_FILE_HOST"
          break
        fi
        echo -n "."
        sleep 2
        elapsed=$((elapsed + 2))
      done

      if [ "$STATUS" != "healthy" ]; then
        echo -e "\n⚠️ Warning: rag-proxy did not become healthy within $timeout seconds. Current status: $STATUS"
        echo "You may need to check container logs or manually recreate it."
      fi
    else
      echo "⚠️ Failed to recreate rag-proxy. You can purge manually with:"
      echo "  docker compose up -d --force-recreate rag-proxy"
    fi
  else
    echo "ℹ️ Logs kept. Remember to purge them before your next analysis run to avoid mixed data."
  fi
else
  # Non-interactive mode (e.g. CI)
  echo ""
  echo "ℹ️ Non-interactive mode detected. Logs were kept."
  echo "Remember to purge them before your next analysis run to avoid mixed data."
  echo "Manual purge: docker compose up -d --force-recreate rag-proxy"
fi
