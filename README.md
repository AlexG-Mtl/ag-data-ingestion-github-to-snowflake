# GitHub to Snowflake Data Ingestion Pipeline

A Python-based data pipeline that extracts GitHub repository metadata via the GitHub API, validates data quality, and uploads to AWS S3 for further processing and loading into Snowflake.

## 🏗️ Architecture

```
GitHub API → Python Script → AWS S3 → Snowflake (Future)
```

## 📋 Features

- ✅ **GitHub API Integration**: Fetch repository metadata with pagination support
- ✅ **Rate Limiting**: Automatic detection and handling of API rate limits
- ✅ **Smart Caching**: Cache API responses locally to minimize API usage during development
- ✅ **Data Validation**: Comprehensive data quality checks on all extracted data
- ✅ **S3 Upload**: Automated upload to AWS S3 with timestamped filenames
- ✅ **Logging**: Detailed logging to both console and file
- ✅ **Error Handling**: Robust error handling with retry logic

## 🚀 Quick Start

### Prerequisites

- Python 3.8+
- AWS CLI configured with credentials
- Access to S3 bucket: `github-api0-upload` (us-east-2)

### Installation

1. Clone the repository:
```bash
git clone https://github.com/AlexG-Mtl/ag-data-ingestion-github-to-snowflake.git
cd ag-data-ingestion-github-to-snowflake
```

2. Install required packages:
```bash
pip install -r requirements.txt
```

3. Configure environment variables (optional):
```bash
cp .env.example .env
# Edit .env with your settings
```

### Usage

**Basic usage (with defaults):**
```bash
python src/extract_github_data.py
```

**Use cached responses (recommended for development):**
```bash
python src/extract_github_data.py --use-cache
```

**Test without uploading to S3:**
```bash
python src/extract_github_data.py --skip-upload
```

**Combine options:**
```bash
python src/extract_github_data.py --use-cache --skip-upload
```

## ⚙️ Configuration

Configuration can be set via environment variables or by editing `.env` file:

| Variable | Description | Default |
|----------|-------------|---------|
| `AWS_S3_BUCKET` | S3 bucket name | `github-api0-upload` |
| `AWS_REGION` | AWS region | `us-east-2` |
| `GITHUB_TOKEN` | GitHub Personal Access Token (optional) | `` |
| `PAGES_TO_EXTRACT` | Number of pages to extract | `2` |
| `REPOS_PER_PAGE` | Repositories per page | `50` |
| `USE_CACHE` | Enable response caching | `true` |
| `CACHE_DIR` | Cache directory | `cache` |
| `LOG_LEVEL` | Logging level | `INFO` |
| `LOG_DIR` | Log directory | `logs` |

## 📊 Output

### S3 Upload Format

Files are uploaded to S3 with the following structure:

```json
{
  "metadata": {
    "extraction_timestamp": "2025-12-06_15-30-45",
    "total_repositories": 100,
    "pages_extracted": 2,
    "repos_per_page": 50,
    "validation": {
      "total_repositories": 100,
      "valid_repositories": 100,
      "invalid_repositories": 0,
      "validation_rate": "100.00%"
    },
    "statistics": {
      "total_stars": 15234,
      "top_10_languages": {...}
    }
  },
  "repositories": [...]
}
```

### Logs

Logs are stored in the `logs/` directory with format:
```
logs/github_extract_YYYYMMDD_HHMMSS.log
```

### Cache

API responses are cached in `cache/` directory:
```
cache/github_repos_page_1.json
cache/github_repos_page_2.json
```

## 🔍 Script Explanation

### Main Components

1. **Configuration (lines 33-71)**
   - Loads settings from environment variables
   - Sets defaults for all parameters
   - Manages API endpoints and rate limiting settings

2. **Logging Setup (lines 76-123)**
   - Configures dual logging (console + file)
   - Creates timestamped log files
   - Formats log messages for readability

3. **Caching Functions (lines 129-178)**
   - `save_to_cache()`: Saves API responses to local JSON files
   - `load_from_cache()`: Loads previously cached responses
   - Minimizes API usage during development and testing

4. **GitHub API Functions (lines 184-328)**
   - `get_api_headers()`: Builds request headers (with optional auth)
   - `check_rate_limit()`: Monitors API rate limit status
   - `fetch_repositories_page()`: Fetches single page with error handling
   - `extract_all_repositories()`: Orchestrates multi-page extraction

5. **Data Validation (lines 334-478)**
   - `validate_repository()`: Validates individual repository data
   - `validate_all_repositories()`: Validates entire dataset
   - `get_data_statistics()`: Calculates data statistics

6. **S3 Upload (lines 484-542)**
   - `upload_to_s3()`: Uploads data package to S3
   - Includes metadata and statistics
   - Uses timestamped filenames

7. **Main Execution (lines 548-622)**
   - Orchestrates complete pipeline
   - Handles command-line arguments
   - Provides detailed progress logging

## 🔐 API Rate Limiting

### Unauthenticated Requests
- **Limit**: 60 requests per hour
- **Coverage**: With 2 pages × 50 repos = 100 repositories
- **API Calls**: 2 requests (well within limit)

### Authenticated Requests (Optional)
To increase rate limit to 5000 requests/hour:

1. Create a GitHub Personal Access Token:
   - Go to GitHub Settings → Developer settings → Personal access tokens
   - Generate new token (no special scopes needed for public repo metadata)

2. Set the token:
```bash
export GITHUB_TOKEN=your_token_here
```

## 🧪 Testing

### Initial Test (2 pages, ~100 repos)
```bash
# Test with cache and S3 upload
python src/extract_github_data.py --use-cache

# Test without S3 upload
python src/extract_github_data.py --use-cache --skip-upload
```

### Development Testing
When modifying the script, use cached data to avoid API calls:
```bash
python src/extract_github_data.py --use-cache --skip-upload
```

## 📈 Future Enhancements

- [ ] Snowflake integration for automated data loading
- [ ] Incremental load strategy for daily updates
- [ ] Scheduling via cron or AWS Lambda
- [ ] Data deduplication logic
- [ ] Compression for S3 uploads (gzip)
- [ ] Email notifications on success/failure

## 🤝 Development Workflow

1. Pull latest from develop:
```bash
git checkout develop
git pull origin develop
```

2. Create feature branch:
```bash
git checkout -b feature/your-feature-name
```

3. Make changes and test

4. Commit to develop:
```bash
git checkout develop
git merge feature/your-feature-name
git push origin develop
```

## 📄 License

MIT License

## 👤 Author

Alex G