# GitHub to Snowflake Data Ingestion Pipeline

Extract GitHub repository metadata via API and upload to AWS S3 for Snowflake analysis.

## 🏗️ Architecture

```
GitHub API → Python Script → AWS S3 → Snowflake (manual COPY INTO)
```

**Two-Step Process:**
1. Fetch repository list (100 IDs per request)
2. Fetch detailed metadata for each repository

**Data Structure:** Flattened JSON with owner fields at top level for easier Snowflake querying.

## 📋 Features

- ✅ Two-step extraction for complete metadata
- ✅ Flattened data structure (owner fields at top level)
- ✅ Resume capability (tracks last processed repo ID)
- ✅ Multiple storage options for state tracking (file/env/s3/dynamo)
- ✅ Rate limit handling (60 req/hour unauthenticated, 5000 with token)
- ✅ Smart caching to minimize API usage
- ✅ Data validation and quality checks
- ✅ S3 upload with date partitioning (yyyy/mm/dd/)
- ✅ Comprehensive logging (console + timestamped files)

## 🚀 Quick Start

### Prerequisites

**For Docker (Recommended):**
- Docker Engine installed
- AWS credentials (Access Key ID and Secret Access Key)
- S3 bucket access (default: `github-api0-upload` in us-east-2)

**For Local Python:**
- Python 3.8+
- AWS CLI configured with credentials
- S3 bucket access

### Option 1: Docker Setup (Recommended)

Docker provides a portable, consistent environment with automatic S3 state tracking.

```bash
# 1. Clone repository
git clone https://github.com/AlexG-Mtl/ag-data-ingestion-github-to-snowflake.git
cd ag-data-ingestion-github-to-snowflake

# 2. Set up AWS credentials
cp .env.docker.example .env.docker
# Edit .env.docker and add your AWS credentials

# 3. Migrate state to S3 (first time only)
echo "0" | aws s3 cp - s3://github-api0-upload/github_extraction_state/last_repo_id.txt

# 4. Build Docker image
docker-compose build

# 5. Test run (no S3 upload)
./run-docker.sh test
# OR: docker-compose run --rm github-extractor --test-mode --skip-upload

# 6. Production run
./run-docker.sh prod
# OR: docker-compose up
```

**Docker Commands:**
```bash
./run-docker.sh test     # Test mode (59 repos, no S3 upload)
./run-docker.sh prod     # Production mode (59 repos, upload to S3)
./run-docker.sh custom "--use-cache --skip-upload"  # Custom flags
./run-docker.sh clean    # Remove containers and volumes
./run-docker.sh shell    # Interactive bash shell
./run-docker.sh logs     # View container logs
```

**Docker Features:**
- ✅ S3-based state tracking (portable across machines)
- ✅ No local file dependencies
- ✅ Consistent environment
- ✅ Persistent cache and logs via volumes
- ✅ Runs as non-root user for security

### Option 2: Local Python Setup

```bash
# Clone repository
git clone https://github.com/AlexG-Mtl/ag-data-ingestion-github-to-snowflake.git
cd ag-data-ingestion-github-to-snowflake

# Install dependencies
pip install -r requirements.txt

# Configure (optional - defaults work)
cp .env.example .env
```

**Basic Usage:**

**Test run** (59 repos, no S3 upload):
```bash
python src/extract_github_data.py --test-mode --skip-upload --use-cache
```

**Production run** (59 repos, uploads to S3):
```bash
python src/extract_github_data.py --use-cache
```

**With GitHub token** (4999 repos per hour):
```bash
export GITHUB_TOKEN=ghp_your_token_here
export MAX_REQUESTS_PER_RUN=5000
python src/extract_github_data.py --use-cache
```

**Resume after interruption** (automatic):
```bash
# First run
python src/extract_github_data.py --test-mode
^C  # Interrupted

# Second run - automatically resumes from last position
python src/extract_github_data.py --test-mode
```

## ⚙️ Configuration

Configure via environment variables or `.env` file:

| Variable | Description | Default |
|----------|-------------|---------|
| `AWS_S3_BUCKET` | S3 bucket name | `github-api0-upload` |
| `AWS_REGION` | AWS region | `us-east-2` |
| `S3_USE_DATE_PARTITIONING` | Enable yyyy/mm/dd folders | `true` |
| `GITHUB_TOKEN` | GitHub Personal Access Token | `` |
| `MAX_REQUESTS_PER_RUN` | API request budget per run | `60` |
| `SINCE_STORAGE_METHOD` | State storage (file/env/s3/dynamo) | `file` |
| `SINCE_FILE_PATH` | State file location | `last_repo_id.txt` |
| `USE_CACHE` | Enable response caching | `true` |
| `LOG_LEVEL` | Logging level | `INFO` |

## 📊 Output

### S3 Structure

```
s3://github-api0-upload/
├── 2025/12/07/
│   ├── github_repos_2025-12-07_10-41-17.json
│   └── github_repos_2025-12-07_11-45-23.json
```

### JSON Format

```json
{
  "metadata": {
    "extraction_date": "2025-12-07T10:41:17",
    "start_repo_id": 0,
    "last_repo_id": 370,
    "total_processed": 59,
    "valid_count": 54,
    "invalid_count": 3,
    "failed_count": 2
  },
  "repositories": [
    {
      "id": 1,
      "name": "grit",
      "full_name": "mojombo/grit",
      "description": "...",
      "stargazers_count": 1920,
      "language": "Ruby",
      "created_at": "2007-10-29T14:37:16Z",
      "updated_at": "2024-11-15T10:23:45Z",
      "owner_login": "mojombo",
      "owner_id": 1,
      "owner_type": "User",
      "owner_avatar_url": "...",
      "owner_url": "https://github.com/mojombo"
    }
  ]
}
```

### Flattened Structure Benefits

- No nested queries in Snowflake
- Direct field access: `SELECT owner_login, owner_type FROM repos`
- Easy filtering: `WHERE owner_type = 'Organization'`

## 🔄 How It Works

### Two-Step Process

**Step 1:** Get repository list (1 API call)
```
GET /repositories?since=0&per_page=100
→ Returns 100 repository IDs
```

**Step 2:** Get details for each repo (59 API calls with 60 req/hour limit)
```
GET /repos/mojombo/grit
GET /repos/wycats/merb-core
... (59 repos total)
```

**Total:** 60 API calls = 59 repositories with complete metadata

### Resume Capability

Progress is automatically saved. If interrupted:
```bash
# Check last position
cat last_repo_id.txt  # Shows: 164

# Resume automatically
python src/extract_github_data.py --test-mode
# Output: "Resuming from repo ID: 164"
```

**Storage Options:**
- **file** (default): Local text file
- **env**: Environment variable (for containers)
- **s3**: S3 object (for distributed systems)
- **dynamo**: DynamoDB table (for production)

## 🔐 Rate Limits

| Authentication | Limit | Repos/Hour |
|----------------|-------|------------|
| None | 60 req/hour | 59 |
| GitHub Token | 5000 req/hour | 4999 |

**Get a token:** GitHub Settings → Developer settings → Personal access tokens (no special scopes needed for public repos)

## 🧪 Testing

**Reset state and start fresh:**
```bash
rm last_repo_id.txt
python src/extract_github_data.py --test-mode --skip-upload
```

**Check logs:**
```bash
tail -f logs/github_extract_*.log
```

**View latest S3 upload:**
```bash
aws s3 ls s3://github-api0-upload/2025/12/07/ --human-readable
```

## 📈 Next Steps

### Snowflake Integration

1. **Create Snowflake table:**
```sql
CREATE TABLE github_repos (
    id INTEGER PRIMARY KEY,
    name VARCHAR,
    full_name VARCHAR,
    html_url VARCHAR,
    description VARCHAR,
    stargazers_count INTEGER,
    language VARCHAR,
    created_at TIMESTAMP,
    updated_at TIMESTAMP,
    owner_login VARCHAR,
    owner_id INTEGER,
    owner_type VARCHAR,
    owner_avatar_url VARCHAR,
    owner_url VARCHAR
);
```

2. **Load data from S3:**
```sql
COPY INTO github_repos
FROM 's3://github-api0-upload/2025/12/07/'
CREDENTIALS = (AWS_KEY_ID='...' AWS_SECRET_KEY='...')
FILE_FORMAT = (TYPE = JSON);
```

3. **Query examples:**
```sql
-- Top 10 most-starred repos
SELECT full_name, stargazers_count, language
FROM github_repos
ORDER BY stargazers_count DESC
LIMIT 10;

-- Repos by owner type
SELECT owner_type, COUNT(*) as count
FROM github_repos
GROUP BY owner_type;

-- Popular languages
SELECT language, AVG(stargazers_count) as avg_stars
FROM github_repos
WHERE language IS NOT NULL
GROUP BY language
ORDER BY avg_stars DESC;
```

## 🛠️ Development

**Workflow:**
```bash
# Pull latest
git checkout develop
git pull origin develop

# Create feature branch
git checkout -b feature/your-feature

# Test changes
python src/extract_github_data.py --test-mode --skip-upload

# Commit
git checkout develop
git merge feature/your-feature
git push origin develop
```

## 📄 Files

**Core Files:**
- `src/extract_github_data.py` - Main extraction script
- `requirements.txt` - Python dependencies
- `README.md` - This file

**Configuration:**
- `.env.example` - Local Python configuration template
- `.env.docker.example` - Docker configuration template

**Docker Files:**
- `Dockerfile` - Container image definition
- `docker-compose.yml` - Service orchestration
- `.dockerignore` - Build optimization
- `run-docker.sh` - Helper script for Docker operations

**Documentation:**
- `cloude.md` - Project overview

## 📄 License

MIT License

## 👤 Author

Alex G

---

**Status:** Production-ready for GitHub API → S3 pipeline. Snowflake integration requires manual COPY INTO commands.
