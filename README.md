# GitHub to Snowflake Data Ingestion Pipeline

A Python-based data pipeline that extracts GitHub repository metadata via the GitHub API using a **two-step process**, validates data quality, and uploads to AWS S3 for further processing and loading into Snowflake.

## 🏗️ Architecture

```
GitHub API (2-Step) → Python Script → AWS S3 → Snowflake (Future)
     │                      │
     ├─ Step 1: List       │
     └─ Step 2: Details    └─ Flattened JSON with owner fields
```

## 📋 Features

- ✅ **Two-Step Extraction**: List repos then fetch detailed metadata for complete data
- ✅ **Flattened Data Structure**: Owner fields at top level for easier Snowflake queries
- ✅ **Resume Capability**: Automatically resume from last position if interrupted
- ✅ **4 Storage Methods**: File, Environment, S3, or DynamoDB for state tracking
- ✅ **Rate Limiting**: Smart handling of API limits (60 req/hour unauthenticated)
- ✅ **Smart Caching**: Minimize API usage during development and testing
- ✅ **Data Validation**: Comprehensive quality checks on all extracted data
- ✅ **S3 Upload**: Date-partitioned uploads (yyyy/mm/dd/) with timestamped filenames
- ✅ **Test Mode**: Quick validation with 100 repos
- ✅ **Comprehensive Logging**: Dual logging (console + timestamped file)

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

3. Configure environment variables:
```bash
cp .env.example .env
# Edit .env with your settings (optional - defaults work fine)
```

### Usage

**Test Mode** (recommended first run - 100 repos, no upload):
```bash
python src/extract_github_data.py --test-mode --skip-upload --use-cache
```

**Production Mode** (59 repos per hour with 60 req/hour limit):
```bash
python src/extract_github_data.py --use-cache
```

**With GitHub Token** (4999 repos per hour with 5000 req/hour limit):
```bash
export GITHUB_TOKEN=ghp_your_token_here
export MAX_REQUESTS_PER_RUN=5000
python src/extract_github_data.py --use-cache
```

**Resume After Interruption** (automatic):
```bash
# First run (interrupted)
python src/extract_github_data.py --test-mode
^C  # Ctrl+C

# Second run (auto-resumes from last position)
python src/extract_github_data.py --test-mode
# Output: "Resuming from repo ID: 364 (file storage)"
```

## 🔄 Two-Step Process Explained

### Why Two Steps?

The `/repositories` endpoint returns minimal data for old repositories (pre-2011):
- ❌ Missing: `stargazers_count`, `language`, `created_at`, etc.
- ✅ Present: `id`, `name`, `full_name`, `owner`, `html_url`

**Solution**: Fetch list first, then get full details for each repo.

### How It Works

**Step 1: Fetch Repository List** (1 API call)
```bash
GET /repositories?since=0&per_page=100
# Returns 100 repository IDs and basic info
```

**Step 2: Fetch Detailed Information** (up to 59 API calls with 60 req/hour limit)
```bash
GET /repos/mojombo/grit
GET /repos/wycats/merb-core
... (59 repos total to stay within 60 req/hour limit)
```

**Result**: Complete metadata with flattened owner fields

### Flattened Data Structure

```json
{
  "id": 1,
  "name": "grit",
  "full_name": "mojombo/grit",
  "html_url": "https://github.com/mojombo/grit",
  "description": "Grit is a Ruby library for...",
  "stargazers_count": 1920,
  "language": "Ruby",
  "created_at": "2007-10-29T14:37:16Z",
  "updated_at": "2024-11-15T10:23:45Z",

  "owner_login": "mojombo",
  "owner_id": 1,
  "owner_type": "User",
  "owner_avatar_url": "https://avatars.githubusercontent.com/u/1?v=4",
  "owner_url": "https://github.com/mojombo"
}
```

**Benefits**:
- No nested queries in Snowflake
- Direct access: `SELECT owner_login, owner_type FROM repos`
- Easy filtering: `WHERE owner_type = 'Organization'`

## ⚙️ Configuration

Configuration via environment variables or `.env` file:

| Variable | Description | Default |
|----------|-------------|---------|
| `AWS_S3_BUCKET` | S3 bucket name | `github-api0-upload` |
| `AWS_REGION` | AWS region | `us-east-2` |
| `S3_USE_DATE_PARTITIONING` | Enable yyyy/mm/dd folders | `true` |
| `GITHUB_TOKEN` | GitHub PAT (optional) | `` |
| `MAX_REQUESTS_PER_RUN` | API request budget | `60` |
| `USE_CACHE` | Enable response caching | `true` |
| `CACHE_DIR` | Cache directory | `cache` |
| `SINCE_STORAGE_METHOD` | Resume state storage | `file` |
| `SINCE_FILE_PATH` | State file location | `last_repo_id.txt` |
| `LOG_LEVEL` | Logging level | `INFO` |
| `LOG_DIR` | Log directory | `logs` |

### Resume Capability - 4 Storage Methods

| Method | Use Case | Auto-Persist | Setup Complexity |
|--------|----------|--------------|------------------|
| **file** | Dev/Test | ✅ Yes | ⭐ Simple |
| **env** | Containers | ❌ Manual | ⭐⭐ Moderate |
| **s3** | Distributed | ✅ Yes | ⭐⭐⭐ Complex |
| **dynamo** | Production | ✅ Yes | ⭐⭐⭐⭐ Most Complex |

**File Storage** (default):
```bash
SINCE_STORAGE_METHOD=file
SINCE_FILE_PATH=last_repo_id.txt
```

**S3 Storage** (for distributed systems):
```bash
SINCE_STORAGE_METHOD=s3
# Stores at: s3://github-api0-upload/github_extraction_state/last_repo_id.txt
```

See [TWO_STEP_EXTRACTION.md](TWO_STEP_EXTRACTION.md) for detailed documentation on all storage methods.

## 📊 Output

### S3 Upload Structure

With date partitioning enabled (default):
```
s3://github-api0-upload/
├── 2025/
│   └── 12/
│       └── 07/
│           ├── github_repos_2025-12-07_10-41-17.json
│           ├── github_repos_2025-12-07_11-45-23.json
│           └── github_repos_2025-12-07_12-50-39.json
```

### File Contents

```json
{
  "metadata": {
    "extraction_date": "2025-12-07T10:41:17",
    "start_repo_id": 0,
    "last_repo_id": 370,
    "total_processed": 100,
    "valid_count": 89,
    "invalid_count": 6,
    "failed_count": 5,
    "api_calls": 95,
    "cache_hits": 5,
    "test_mode": true,
    "duration_seconds": 125.3
  },
  "repositories": [
    {
      "id": 1,
      "name": "grit",
      "full_name": "mojombo/grit",
      "stargazers_count": 1920,
      "language": "Ruby",
      "owner_login": "mojombo",
      "owner_type": "User",
      ...
    },
    ...
  ]
}
```

### Logs

Timestamped log files in `logs/` directory:
```
logs/github_extract_20251207_104101.log
```

### Cache

API responses cached by repo ID:
```
cache/detail_repo_1.json
cache/detail_repo_26.json
cache/detail_repo_27.json
```

### State Tracking

Resume state saved to:
```
last_repo_id.txt  # Contains: 364
```

## 🔐 API Rate Limiting

### Unauthenticated (60 req/hour)

**Production Mode**:
- 1 request for list (100 repo IDs)
- 59 requests for details
- **Total: 59 repos per hour**

**Test Mode**:
- 1 request for list (100 repo IDs)
- 100 requests for details (will hit rate limit ~60)
- **Use --skip-upload to avoid wasting quota**

### Authenticated (5000 req/hour)

Get a GitHub Personal Access Token:
1. GitHub Settings → Developer settings → Personal access tokens
2. Generate new token (no special scopes needed for public repos)
3. Set environment variable:

```bash
export GITHUB_TOKEN=ghp_your_token_here
export MAX_REQUESTS_PER_RUN=5000
python src/extract_github_data.py
```

**Result**: 4999 repos per hour (1 list + 4999 details)

## 🧪 Testing

### Test Mode (100 repos)

```bash
# Test without S3 upload (recommended first run)
python src/extract_github_data.py --test-mode --skip-upload --use-cache

# Output:
# TEST MODE: Extracting 1 page (100 repositories)
# STEP 1: Fetching repository list...
# Fetched 100 repositories (last ID: 370)
# STEP 2: Fetching detailed information...
# [1/100] Processing mojombo/grit (ID: 1)
# ...
# Valid repositories: 89
# Cache hits: 95
```

### Production Mode (59 repos)

```bash
# Production with S3 upload
python src/extract_github_data.py --use-cache

# Output:
# PRODUCTION MODE: Max 59 repositories
# Rate limit: 60 requests/hour
# Starting extraction from repo ID: 370
# ...
# Successfully uploaded to s3://github-api0-upload/2025/12/07/github_repos_2025-12-07_11-45-23.json
```

### Resume After Interruption

```bash
# First run (interrupted after 30 repos)
python src/extract_github_data.py --test-mode
^C  # Interrupt

# Check saved state
cat last_repo_id.txt
# Output: 164

# Second run (auto-resumes from 164)
python src/extract_github_data.py --test-mode
# Output: "Resuming from repo ID: 164 (file storage)"
```

### Reset State

```bash
# Start fresh from repo ID 0
rm last_repo_id.txt
python src/extract_github_data.py --test-mode
```

## 📈 Analysis Queries

With the flattened data structure, you can answer these questions in Snowflake:

### 1. Total Repositories
```sql
SELECT COUNT(DISTINCT id) as total_repos FROM github_repos;
```

### 2. Top 10 Most-Starred
```sql
SELECT full_name, stargazers_count, language, owner_login
FROM github_repos
ORDER BY stargazers_count DESC
LIMIT 10;
```

### 3. Popular Languages
```sql
SELECT language,
       AVG(stargazers_count) as avg_stars,
       COUNT(*) as repo_count
FROM github_repos
WHERE language IS NOT NULL
GROUP BY language
ORDER BY avg_stars DESC;
```

### 4. Repos by Owner Type
```sql
SELECT owner_type, COUNT(*) as repo_count
FROM github_repos
GROUP BY owner_type;
```

### 5. Trending by Creation Date
```sql
SELECT full_name, created_at, stargazers_count, language
FROM github_repos
WHERE created_at >= '2025-01-01'
ORDER BY stargazers_count DESC;
```

### 6. Language Popularity Over Time
```sql
SELECT
  DATE_TRUNC('year', created_at) as year,
  language,
  COUNT(*) as repo_count
FROM github_repos
WHERE language IS NOT NULL
GROUP BY year, language
ORDER BY year DESC, repo_count DESC;
```

## 🔍 Script Architecture

### Main Components

1. **Configuration** ([src/extract_github_data.py:76-107](src/extract_github_data.py:76-107))
   - Environment variable loading
   - API endpoints and rate limits
   - Storage method configuration

2. **Logging Setup** ([src/extract_github_data.py:114-156](src/extract_github_data.py:114-156))
   - Dual logging (console + file)
   - Timestamped log files
   - Formatted output

3. **Since Tracking** ([src/extract_github_data.py:163-285](src/extract_github_data.py:163-285))
   - `get_last_repo_id()`: Load resume state (4 methods)
   - `save_last_repo_id()`: Save progress
   - File/Env/S3/DynamoDB support

4. **Caching Functions** ([src/extract_github_data.py:292-343](src/extract_github_data.py:292-343))
   - `save_to_cache()`: Cache API responses
   - `load_from_cache()`: Load cached data
   - Repo-level caching

5. **GitHub API - Step 1** ([src/extract_github_data.py:393-434](src/extract_github_data.py:393-434))
   - `fetch_repository_list()`: Get 100 repo IDs
   - Uses `since` parameter for pagination
   - Returns lightweight list

6. **GitHub API - Step 2** ([src/extract_github_data.py:437-490](src/extract_github_data.py:437-490))
   - `fetch_repository_details()`: Get full metadata
   - Individual repo endpoint
   - Rate limit handling

7. **Data Flattening** ([src/extract_github_data.py:493-526](src/extract_github_data.py:493-526))
   - `flatten_repository_data()`: Extract owner fields
   - Top-level structure for Snowflake
   - Validation-ready format

8. **Validation** ([src/extract_github_data.py:529-546](src/extract_github_data.py:529-546))
   - `validate_repository()`: Check required fields
   - Filters out invalid repos
   - Reports missing fields

9. **S3 Upload** ([src/extract_github_data.py:553-599](src/extract_github_data.py:553-599))
   - `upload_to_s3()`: Upload to S3 with metadata
   - Date partitioning support
   - Timestamped filenames

10. **Main Extraction** ([src/extract_github_data.py:606-760](src/extract_github_data.py:606-760))
    - `extract_repositories()`: Orchestrates two-step process
    - Request budget management
    - Progress tracking and logging

## 📚 Documentation

- **[TWO_STEP_EXTRACTION.md](TWO_STEP_EXTRACTION.md)**: Comprehensive guide to two-step process, storage methods, and usage
- **[IMPROVEMENTS.md](IMPROVEMENTS.md)**: Changelog and improvement history
- **[cloude.md](cloude.md)**: Project overview and status

## 🛠️ Development Workflow

1. Pull latest from develop:
```bash
git checkout develop
git pull origin develop
```

2. Create feature branch:
```bash
git checkout -b feature/your-feature-name
```

3. Make changes and test:
```bash
python src/extract_github_data.py --test-mode --skip-upload --use-cache
```

4. Commit and merge to develop:
```bash
git checkout develop
git merge feature/your-feature-name
git commit -m "Your commit message"
git push origin develop
```

## 🚀 Next Steps

### Immediate
- [ ] Push to remote develop
- [ ] Scale up with GitHub token (5000 req/hour)
- [ ] Schedule daily runs (cron or AWS Lambda)

### Short-term
- [ ] Snowflake table creation with flattened schema
- [ ] Implement COPY INTO from S3
- [ ] Add MERGE for deduplication
- [ ] Set up monitoring and alerts

### Long-term
- [ ] Add more repository fields (forks, issues, etc.)
- [ ] Implement incremental updates (track modified repos)
- [ ] Add commit history extraction
- [ ] Create dashboard for metrics

## 🤝 Contributing

This is a personal project, but suggestions and improvements are welcome!

## 📄 License

MIT License

## 👤 Author

Alex G

---

**Latest Update**: 2025-12-07 - Implemented two-step extraction with resume capability and 4 storage methods
