# GitHub to Snowflake Data Ingestion Pipeline

## Project Overview
Data pipeline to extract GitHub repository metadata via GitHub API, upload to S3, and load into Snowflake for analysis.

## Architecture
```
GitHub API → Python Script → S3 Bucket → Snowflake
```

## Data Source
- **Source**: GitHub REST API
- **Endpoint**: https://api.github.com/repositories
- **Data Type**: JSON
- **Rate Limit**: 60 requests/hour (unauthenticated), 5000 requests/hour (authenticated)

## Infrastructure
- **S3 Bucket**: github-api0-upload (us-east-2)
- **AWS CLI**: Configured locally
- **Target**: Snowflake data warehouse

## Project Phases

### Phase 1: GitHub Data Extraction
- Implement GitHub API calls with pagination
- Handle rate limiting
- Error handling and logging
- Test with 2 pages initially

### Phase 2: S3 Upload
- Upload JSON data to S3
- Timestamped file naming convention
- Data validation before upload

### Phase 3: Data Quality
- JSON structure validation
- Required field checks
- Data quality rules

### Phase 4: Snowflake Integration (Future)
- Create Snowflake tables
- Implement incremental load strategy
- Daily scheduling for new repositories

## Development Workflow
1. Always pull from remote `develop` branch before starting
2. Create feature branch for each new development
3. Test and validate
4. Commit to local `develop`
5. Push to remote `develop`

## Current Status
- Initial setup phase
- AWS CLI configured
- S3 bucket ready
