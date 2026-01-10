# Quality Analysis Guide

To ensure high-quality translations, it is important to monitor how well the Retrieval-Augmented Generation (RAG) system performs. I have included a script, `analyze_logs.py`, to help you evaluate the system's accuracy and the relevance of the retrieved data.

## 1. Running the Analysis
The RAG proxy logs its activities, including the distance scores for every retrieved segment. You can parse these logs to generate statistical reports and CSV exports.

**Command:**
```bash
docker compose exec toolbox python3 /app/src/analyze_logs.py <path_to_log_file>
