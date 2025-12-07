# Two-Step Extraction Process - Documentation

## Overview

The GitHub data extraction pipeline now uses a **two-step process** to get complete repository metadata:

1. **STEP 1**: Fetch repository list from `/repositories` endpoint (lightweight)
2. **STEP 2**: Fetch detailed information for each repository from `/repos/{owner}/{name}` endpoint

This solves the limitation where the `/repositories` endpoint only returns basic fields for old repositories.

---

## Why Two-Step Process?

### Problem with Old Approach
The `/repositories` endpoint returns minimal data for repositories created before 2011:
- ❌ Missing: `stargazers_count`, `language`, `created_at`, `updated_at`
- ✅ Present: `id`, `name`, `full_name`, `owner`, `html_url`

### Solution with Two-Step Approach
1. Get list of 100 repo IDs (1 API call)
2. Fetch full details for each repo (up to 59 API calls with 60 req/hour limit)
3. Extract complete metadata including stars, language, dates, etc.

---

## Flattened Data Structure

Repository data is flattened to make Snowflake queries easier:

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
- No nested queries needed in Snowflake
- Direct access to owner fields: `SELECT owner_login, owner_type FROM repos`
- Easier filtering: `WHERE owner_type = 'Organization'`

---

## Resume Capability - 'Since' Parameter

The script saves the last processed repository ID and resumes from there if interrupted.

### How It Works

1. Before extraction: Read last repo ID from storage
2. Use `since` parameter in API call: `/repositories?since=364`
3. Process repositories starting from ID 365
4. After each repo: Save current ID to storage

### 4 Storage Methods

#### Method 1: Local File (Default - Simplest)

**Best for**: Single server, development, testing

**Configuration**:
```bash
SINCE_STORAGE_METHOD=file
SINCE_FILE_PATH=last_repo_id.txt
```

**How it works**:
- Saves last repo ID to `last_repo_id.txt`
- Reads from file on next run
- Automatic resume if script crashes

**Pros**:
- ✅ Simplest setup (no dependencies)
- ✅ Works out of the box
- ✅ Easy to inspect (`cat last_repo_id.txt`)
- ✅ Easy to reset (`rm last_repo_id.txt`)

**Cons**:
- ❌ Not suitable for distributed systems
- ❌ File can be lost if server dies

**Example**:
```bash
# First run
python src/extract_github_data.py --test-mode --skip-upload
# Saves: last_repo_id.txt = 364

# Script crashes or interrupted

# Second run (auto-resumes from 364)
python src/extract_github_data.py --test-mode --skip-upload
# Loads: last_repo_id.txt = 364
# Starts: since=364
```

---

#### Method 2: Environment Variable

**Best for**: Docker containers, Kubernetes with ConfigMaps

**Configuration**:
```bash
SINCE_STORAGE_METHOD=env
LAST_REPO_ID=0  # Starting value
```

**How it works**:
- Reads `LAST_REPO_ID` from environment
- Logs the value you need to set for next run
- Manual update required

**Pros**:
- ✅ Works in containerized environments
- ✅ Easy integration with K8s ConfigMaps
- ✅ No file system dependencies

**Cons**:
- ❌ Manual update required between runs
- ❌ Cannot auto-persist state
- ❌ Requires external orchestration

**Example**:
```bash
# First run
export LAST_REPO_ID=0
python src/extract_github_data.py --test-mode --skip-upload
# Output: "Set LAST_REPO_ID=364 before next run"

# Second run (manual update)
export LAST_REPO_ID=364
python src/extract_github_data.py --test-mode --skip-upload
```

**Kubernetes ConfigMap Example**:
```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: github-extraction-config
data:
  SINCE_STORAGE_METHOD: "env"
  LAST_REPO_ID: "364"
```

---

#### Method 3: S3 Storage

**Best for**: Distributed systems, multiple extraction servers, AWS infrastructure

**Configuration**:
```bash
SINCE_STORAGE_METHOD=s3
AWS_S3_BUCKET=github-api0-upload
AWS_REGION=us-east-2
```

**How it works**:
- Saves last repo ID to S3: `s3://bucket/github_extraction_state/last_repo_id.txt`
- Reads from S3 on next run
- Multiple servers can coordinate using same S3 state

**Pros**:
- ✅ Shared state across multiple servers
- ✅ Highly available (S3 durability: 99.999999999%)
- ✅ Works with AWS Lambda, EC2, ECS
- ✅ Automatic persistence

**Cons**:
- ❌ Requires AWS credentials
- ❌ Network dependency
- ❌ Slightly slower than local file

**Example**:
```bash
# Configure
export SINCE_STORAGE_METHOD=s3
export AWS_S3_BUCKET=github-api0-upload
export AWS_REGION=us-east-2

# First run
python src/extract_github_data.py --test-mode --skip-upload
# Saves: s3://github-api0-upload/github_extraction_state/last_repo_id.txt = 364

# Second run (from different server - auto-resumes)
python src/extract_github_data.py --test-mode --skip-upload
# Loads: s3://github-api0-upload/github_extraction_state/last_repo_id.txt = 364
```

**S3 State Check**:
```bash
aws s3 cp s3://github-api0-upload/github_extraction_state/last_repo_id.txt -
# Output: 364
```

---

#### Method 4: DynamoDB Storage

**Best for**: Production systems requiring ACID compliance, high concurrency

**Configuration**:
```bash
SINCE_STORAGE_METHOD=dynamo
DYNAMO_STATE_TABLE=github_extraction_state
AWS_REGION=us-east-2
```

**DynamoDB Table Schema**:
```
Table: github_extraction_state
Partition Key: extraction_id (String)

Item structure:
{
  "extraction_id": "github_repos",
  "last_repo_id": 364,
  "updated_at": "2025-12-07T10:41:17Z"
}
```

**How it works**:
- Saves state to DynamoDB with timestamp
- Provides ACID compliance
- Best for production with multiple concurrent extractors

**Pros**:
- ✅ ACID compliance (atomic updates)
- ✅ Best for high concurrency
- ✅ Can store additional metadata (updated_at)
- ✅ Fast reads/writes
- ✅ Built-in versioning possible

**Cons**:
- ❌ Most complex setup
- ❌ Requires DynamoDB table creation
- ❌ Additional AWS costs

**Setup DynamoDB Table**:
```bash
aws dynamodb create-table \
  --table-name github_extraction_state \
  --attribute-definitions AttributeName=extraction_id,AttributeType=S \
  --key-schema AttributeName=extraction_id,KeyType=HASH \
  --billing-mode PAY_PER_REQUEST \
  --region us-east-2
```

**Example**:
```bash
# Configure
export SINCE_STORAGE_METHOD=dynamo
export DYNAMO_STATE_TABLE=github_extraction_state
export AWS_REGION=us-east-2

# First run
python src/extract_github_data.py --test-mode --skip-upload
# Saves to DynamoDB: extraction_id="github_repos", last_repo_id=364

# Check state
aws dynamodb get-item \
  --table-name github_extraction_state \
  --key '{"extraction_id": {"S": "github_repos"}}' \
  --region us-east-2
```

---

## Storage Method Comparison

| Feature | File | Env | S3 | DynamoDB |
|---------|------|-----|-----|----------|
| **Complexity** | ⭐ Simple | ⭐⭐ Moderate | ⭐⭐⭐ Complex | ⭐⭐⭐⭐ Most Complex |
| **Auto-persist** | ✅ Yes | ❌ No | ✅ Yes | ✅ Yes |
| **Distributed** | ❌ No | ⚠️ Manual | ✅ Yes | ✅ Yes |
| **ACID** | ❌ No | ❌ No | ❌ No | ✅ Yes |
| **Dependencies** | None | None | AWS S3 | AWS DynamoDB |
| **Cost** | Free | Free | ~$0.01/mo | ~$0.25/mo |
| **Best For** | Dev/Test | Containers | AWS Multi-Server | Production |

---

## Usage Examples

### Test Mode (100 repos, no upload)

```bash
python src/extract_github_data.py --test-mode --skip-upload --use-cache
```

**Output**:
```
TEST MODE: Extracting 1 page (100 repositories)
Starting extraction from repo ID: 0

STEP 1: Fetching repository list...
Fetched 100 repositories (last ID: 370)

STEP 2: Fetching detailed information for each repository...
[1/100] Processing mojombo/grit (ID: 1)
[2/100] Processing wycats/merb-core (ID: 26)
...
[100/100] Processing collectiveidea/imap_authenticatable (ID: 370)

EXTRACTION COMPLETE
Total repositories processed: 100
Valid repositories: 89
Invalid repositories: 6
Failed to fetch: 5
API calls made: 5
Cache hits: 95
Last repo ID: 370
```

### Production Mode (59 repos, with upload)

```bash
python src/extract_github_data.py --use-cache
```

**Output**:
```
PRODUCTION MODE: Max 59 repositories
Rate limit: 60 requests/hour
Starting extraction from repo ID: 370

STEP 1: Fetching repository list...
Fetched 100 repositories (last ID: 570)

STEP 2: Fetching detailed information for each repository...
Processing 59 repositories (budget: 59)
...

Uploading to S3...
Successfully uploaded to s3://github-api0-upload/2025/12/07/github_repos_2025-12-07_10-45-23.json
```

### Resume After Interruption

```bash
# First run (interrupted after 30 repos)
python src/extract_github_data.py --test-mode
^C  # Ctrl+C to interrupt
# Progress saved: last_repo_id.txt = 164

# Second run (auto-resumes from 164)
python src/extract_github_data.py --test-mode
# Output: "Resuming from repo ID: 164 (file storage)"
```

### Reset State and Start Fresh

```bash
# Method 1: File storage
rm last_repo_id.txt

# Method 2: Env storage
export LAST_REPO_ID=0

# Method 3: S3 storage
aws s3 rm s3://github-api0-upload/github_extraction_state/last_repo_id.txt

# Method 4: DynamoDB storage
aws dynamodb delete-item \
  --table-name github_extraction_state \
  --key '{"extraction_id": {"S": "github_repos"}}'
```

---

## Rate Limit Management

### Unauthenticated (60 req/hour)

**Production Mode**:
- 1 request for list (100 repos)
- 59 requests for details
- **Total: 59 repos per hour**

**Test Mode**:
- 1 request for list (100 repos)
- Up to 100 requests for details (will hit rate limit at ~60)
- **Use --skip-upload to avoid wasting quota**

### Authenticated with GitHub Token (5000 req/hour)

```bash
export GITHUB_TOKEN=ghp_your_token_here
export MAX_REQUESTS_PER_RUN=5000
python src/extract_github_data.py
```

**Production Mode with Token**:
- 1 request for list
- 4999 requests for details
- **Total: 4999 repos per hour**

---

## Data Quality

### Valid Repository Example
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
✅ All required fields present

### Invalid Repository Example
```json
{
  "id": 63,
  "name": "starling",
  "full_name": "defunkt/starling",
  "html_url": "https://github.com/defunkt/starling",
  "description": null,  // ❌ Missing
  "stargazers_count": 450,
  "language": "Ruby",
  "created_at": "2008-01-15T12:30:00Z",
  "updated_at": "2020-03-10T08:15:00Z",
  "owner_login": "defunkt",
  "owner_id": 2,
  "owner_type": "User",
  "owner_avatar_url": "https://avatars.githubusercontent.com/u/2?v=4",
  "owner_url": "https://github.com/defunkt"
}
```
❌ Invalid: Missing `description`

**Validation Results** (from test run):
- ✅ 89/100 valid repositories (89%)
- ❌ 6/100 invalid (missing description or language)
- ⚠️ 5/100 failed to fetch (rate limit or 404)

---

## S3 Upload Structure

### With Date Partitioning (Default)
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
    "api_calls": 5,
    "cache_hits": 95,
    "test_mode": true,
    "duration_seconds": 125.3
  },
  "repositories": [
    { /* repo 1 */ },
    { /* repo 2 */ },
    ...
    { /* repo 89 */ }
  ]
}
```

---

## Analysis Questions Supported

With the flattened data structure, you can now answer all 6 analysis questions:

### 1. Total repositories on GitHub
```sql
SELECT COUNT(DISTINCT id) as total_repos FROM github_repos;
```

### 2. Top 10 most-starred repositories
```sql
SELECT full_name, stargazers_count, language
FROM github_repos
ORDER BY stargazers_count DESC
LIMIT 10;
```

### 3. Most popular repositories by language
```sql
SELECT language, AVG(stargazers_count) as avg_stars, COUNT(*) as repo_count
FROM github_repos
WHERE language IS NOT NULL
GROUP BY language
ORDER BY avg_stars DESC;
```

### 4. Repository count by owner type
```sql
SELECT owner_type, COUNT(*) as repo_count
FROM github_repos
GROUP BY owner_type;
```

### 5. Trending repositories by creation date
```sql
SELECT full_name, created_at, stargazers_count
FROM github_repos
WHERE created_at >= '2025-01-01'
ORDER BY stargazers_count DESC;
```

### 6. Language popularity over time
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

---

## Troubleshooting

### Issue: Rate limit exceeded immediately

**Solution**: Use cache
```bash
python src/extract_github_data.py --test-mode --skip-upload --use-cache
```

### Issue: Want to reset and start from beginning

**Solution**: Remove state file
```bash
rm last_repo_id.txt
python src/extract_github_data.py --test-mode
```

### Issue: Script interrupted, lost progress

**Solution**: Progress is auto-saved! Just run again
```bash
python src/extract_github_data.py  # Auto-resumes
```

### Issue: Need to change storage method mid-run

**Solution**: Migrate state manually
```bash
# From file to S3
cat last_repo_id.txt | aws s3 cp - s3://bucket/github_extraction_state/last_repo_id.txt

# Update config
export SINCE_STORAGE_METHOD=s3

# Continue
python src/extract_github_data.py
```

---

## Next Steps

1. **Scale up extraction**:
   ```bash
   # Get GitHub token for 5000 req/hour
   export GITHUB_TOKEN=ghp_your_token
   export MAX_REQUESTS_PER_RUN=5000
   python src/extract_github_data.py
   ```

2. **Set up daily scheduling** (cron):
   ```bash
   # Add to crontab
   0 2 * * * cd /path/to/project && python src/extract_github_data.py
   ```

3. **Implement Snowflake integration**:
   - Create Snowflake table with flattened schema
   - Use COPY INTO from S3
   - Implement MERGE for deduplication

4. **Monitor extraction**:
   - Check logs: `tail -f logs/github_extract_*.log`
   - Check state: `cat last_repo_id.txt`
   - Check S3: `aws s3 ls s3://github-api0-upload/2025/12/07/`

---

## Summary

✅ **Two-step extraction** gets complete metadata
✅ **Flattened structure** makes Snowflake queries easier
✅ **Resume capability** prevents data loss
✅ **4 storage methods** for different use cases
✅ **Test mode** for quick validation
✅ **Rate limit management** respects API limits
✅ **Comprehensive logging** for debugging
✅ **S3 date partitioning** for better organization

**Ready for production!** 🚀
