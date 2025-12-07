#!/usr/bin/env python3
"""
GitHub Data Extraction Script - Two-Step Process
=================================================
Step 1: Fetch repository list from /repositories endpoint
Step 2: Fetch detailed information for each repository

Features:
- Two-step extraction (list + details) for complete metadata
- Resume capability using 'since' parameter
- Rate limiting handling (60 requests/hour unauthenticated)
- Response caching to minimize API usage
- Flattened owner fields for easier analysis
- S3 upload with date partitioning
- Comprehensive logging
- Test mode for quick validation

Usage:
    # Test mode (1 page = 100 repos)
    python extract_github_data.py --test-mode

    # Production mode (60 requests/hour)
    python extract_github_data.py

    # Skip S3 upload
    python extract_github_data.py --skip-upload

    # Use cache
    python extract_github_data.py --use-cache
"""

import os
import sys
import json
import logging
import requests
import boto3
from datetime import datetime
from typing import Dict, List, Optional, Tuple
from pathlib import Path
import time
import argparse


# ============================================================================
# REQUIRED FIELDS - Flattened structure for Snowflake
# ============================================================================
# These fields are extracted from the detailed repo endpoint
# Owner fields are flattened to top level for easier querying

REQUIRED_FIELDS = [
    # Repository fields
    'id',
    'name',
    'full_name',
    'html_url',
    'description',
    'stargazers_count',
    'language',
    'created_at',
    'updated_at',

    # Owner fields (flattened from owner object)
    'owner_login',
    'owner_id',
    'owner_type',
    'owner_avatar_url',
    'owner_url',
]


# ============================================================================
# CONFIGURATION
# ============================================================================

class Config:
    """Configuration management - loads from environment variables or defaults"""

    # AWS S3 Settings
    AWS_S3_BUCKET = os.getenv('AWS_S3_BUCKET', 'github-api0-upload')
    AWS_REGION = os.getenv('AWS_REGION', 'us-east-2')
    S3_USE_DATE_PARTITIONING = os.getenv('S3_USE_DATE_PARTITIONING', 'true').lower() == 'true'

    # GitHub API Settings
    GITHUB_API_BASE_URL = 'https://api.github.com'
    GITHUB_TOKEN = os.getenv('GITHUB_TOKEN', '')

    # Extraction Settings
    REPOS_PER_PAGE = 100  # Maximum allowed by GitHub API
    MAX_REQUESTS_PER_RUN = int(os.getenv('MAX_REQUESTS_PER_RUN', '60'))  # Rate limit
    TEST_MODE_PAGES = 1  # Test mode: 1 page = 100 repos

    # Cache Settings
    USE_CACHE = os.getenv('USE_CACHE', 'true').lower() == 'true'
    CACHE_DIR = os.getenv('CACHE_DIR', 'cache')

    # Since tracking (where to resume from)
    SINCE_STORAGE_METHOD = os.getenv('SINCE_STORAGE_METHOD', 'file')  # Options: file, env, s3, dynamo
    SINCE_FILE_PATH = os.getenv('SINCE_FILE_PATH', 'last_repo_id.txt')

    # Logging Settings
    LOG_LEVEL = os.getenv('LOG_LEVEL', 'INFO')
    LOG_DIR = os.getenv('LOG_DIR', 'logs')

    # Rate Limiting
    RATE_LIMIT_SLEEP = 60  # Sleep time when rate limited (seconds)
    REQUEST_DELAY = 1.0  # Delay between requests to avoid hitting limits (seconds)


# ============================================================================
# LOGGING SETUP
# ============================================================================

def setup_logging() -> logging.Logger:
    """
    Configure logging to both console and file.
    Creates log directory if it doesn't exist.
    Log file is named with timestamp for each run.

    Returns:
        logging.Logger: Configured logger instance
    """
    Path(Config.LOG_DIR).mkdir(parents=True, exist_ok=True)

    logger = logging.getLogger('GitHubExtractor')
    logger.setLevel(getattr(logging, Config.LOG_LEVEL))

    # Create formatters
    file_formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    console_formatter = logging.Formatter(
        '%(levelname)s - %(message)s'
    )

    # File handler with timestamp
    log_filename = f"{Config.LOG_DIR}/github_extract_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
    file_handler = logging.FileHandler(log_filename)
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(file_formatter)

    # Console handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(getattr(logging, Config.LOG_LEVEL))
    console_handler.setFormatter(console_formatter)

    # Add handlers to logger
    logger.addHandler(file_handler)
    logger.addHandler(console_handler)

    logger.info(f"Logging initialized. Log file: {log_filename}")
    return logger


# Initialize logger globally
logger = setup_logging()


# ============================================================================
# SINCE TRACKING - Multiple Storage Options
# ============================================================================

def get_last_repo_id() -> int:
    """
    Get the last processed repository ID to resume from.
    Supports multiple storage methods configured via SINCE_STORAGE_METHOD.

    Storage Methods:
    - 'file': Store in local text file (default, simplest)
    - 'env': Read from environment variable (for containerized environments)
    - 's3': Store in S3 object (for distributed systems)
    - 'dynamo': Store in DynamoDB (for production systems)

    Returns:
        int: Last processed repository ID (0 if starting fresh)
    """
    method = Config.SINCE_STORAGE_METHOD

    if method == 'file':
        # Method 1: Local file storage (simplest, good for single-server)
        if os.path.exists(Config.SINCE_FILE_PATH):
            with open(Config.SINCE_FILE_PATH, 'r') as f:
                last_id = int(f.read().strip())
                logger.info(f"Resuming from repo ID: {last_id} (file storage)")
                return last_id
        logger.info("Starting fresh from repo ID: 0 (no file found)")
        return 0

    elif method == 'env':
        # Method 2: Environment variable (good for Docker/K8s with config management)
        last_id = int(os.getenv('LAST_REPO_ID', '0'))
        logger.info(f"Resuming from repo ID: {last_id} (environment variable)")
        return last_id

    elif method == 's3':
        # Method 3: S3 storage (good for distributed systems, multiple instances)
        try:
            s3_client = boto3.client('s3', region_name=Config.AWS_REGION)
            response = s3_client.get_object(
                Bucket=Config.AWS_S3_BUCKET,
                Key='github_extraction_state/last_repo_id.txt'
            )
            last_id = int(response['Body'].read().decode('utf-8').strip())
            logger.info(f"Resuming from repo ID: {last_id} (S3 storage)")
            return last_id
        except s3_client.exceptions.NoSuchKey:
            logger.info("Starting fresh from repo ID: 0 (no S3 state found)")
            return 0
        except Exception as e:
            logger.warning(f"Error reading from S3: {e}. Starting from 0")
            return 0

    elif method == 'dynamo':
        # Method 4: DynamoDB storage (best for production, ACID compliance)
        try:
            dynamodb = boto3.resource('dynamodb', region_name=Config.AWS_REGION)
            table_name = os.getenv('DYNAMO_STATE_TABLE', 'github_extraction_state')
            table = dynamodb.Table(table_name)

            response = table.get_item(Key={'extraction_id': 'github_repos'})
            if 'Item' in response:
                last_id = int(response['Item']['last_repo_id'])
                logger.info(f"Resuming from repo ID: {last_id} (DynamoDB storage)")
                return last_id
            else:
                logger.info("Starting fresh from repo ID: 0 (no DynamoDB state)")
                return 0
        except Exception as e:
            logger.warning(f"Error reading from DynamoDB: {e}. Starting from 0")
            return 0

    else:
        logger.warning(f"Unknown SINCE_STORAGE_METHOD: {method}. Starting from 0")
        return 0


def save_last_repo_id(repo_id: int) -> None:
    """
    Save the last processed repository ID for future resumption.
    Uses the same storage method as get_last_repo_id().

    Args:
        repo_id: Repository ID to save
    """
    method = Config.SINCE_STORAGE_METHOD

    if method == 'file':
        # Method 1: Local file storage
        with open(Config.SINCE_FILE_PATH, 'w') as f:
            f.write(str(repo_id))
        logger.debug(f"Saved last repo ID {repo_id} to file")

    elif method == 'env':
        # Method 2: Environment variable (informational only - cannot persist)
        logger.warning(f"Last repo ID: {repo_id} (env method - manual update required)")
        logger.warning(f"Set LAST_REPO_ID={repo_id} before next run")

    elif method == 's3':
        # Method 3: S3 storage
        try:
            s3_client = boto3.client('s3', region_name=Config.AWS_REGION)
            s3_client.put_object(
                Bucket=Config.AWS_S3_BUCKET,
                Key='github_extraction_state/last_repo_id.txt',
                Body=str(repo_id).encode('utf-8')
            )
            logger.debug(f"Saved last repo ID {repo_id} to S3")
        except Exception as e:
            logger.error(f"Failed to save to S3: {e}")

    elif method == 'dynamo':
        # Method 4: DynamoDB storage
        try:
            dynamodb = boto3.resource('dynamodb', region_name=Config.AWS_REGION)
            table_name = os.getenv('DYNAMO_STATE_TABLE', 'github_extraction_state')
            table = dynamodb.Table(table_name)

            table.put_item(Item={
                'extraction_id': 'github_repos',
                'last_repo_id': repo_id,
                'updated_at': datetime.now().isoformat()
            })
            logger.debug(f"Saved last repo ID {repo_id} to DynamoDB")
        except Exception as e:
            logger.error(f"Failed to save to DynamoDB: {e}")


# ============================================================================
# CACHING FUNCTIONS
# ============================================================================

def get_cache_filename(repo_id: int, cache_type: str = 'detail') -> str:
    """
    Generate cache filename for a specific repository.

    Args:
        repo_id: Repository ID
        cache_type: Type of cache ('list' or 'detail')

    Returns:
        str: Cache file path
    """
    return f"{Config.CACHE_DIR}/{cache_type}_repo_{repo_id}.json"


def save_to_cache(repo_id: int, data: Dict, cache_type: str = 'detail') -> None:
    """
    Save API response to cache file.

    Args:
        repo_id: Repository ID
        data: Repository data to cache
        cache_type: Type of cache ('list' or 'detail')
    """
    Path(Config.CACHE_DIR).mkdir(parents=True, exist_ok=True)
    cache_file = get_cache_filename(repo_id, cache_type)

    with open(cache_file, 'w') as f:
        json.dump(data, f, indent=2)

    logger.debug(f"Cached {cache_type} for repo {repo_id}")


def load_from_cache(repo_id: int, cache_type: str = 'detail') -> Optional[Dict]:
    """
    Load API response from cache if available.

    Args:
        repo_id: Repository ID
        cache_type: Type of cache ('list' or 'detail')

    Returns:
        Optional[Dict]: Cached data if available, None otherwise
    """
    cache_file = get_cache_filename(repo_id, cache_type)

    if os.path.exists(cache_file):
        with open(cache_file, 'r') as f:
            data = json.load(f)
        logger.debug(f"Loaded {cache_type} for repo {repo_id} from cache")
        return data

    return None


# ============================================================================
# GITHUB API FUNCTIONS
# ============================================================================

def get_api_headers() -> Dict[str, str]:
    """
    Build headers for GitHub API requests.

    Returns:
        Dict[str, str]: Request headers
    """
    headers = {
        'Accept': 'application/vnd.github.v3+json',
        'User-Agent': 'GitHub-Data-Extractor'
    }

    if Config.GITHUB_TOKEN:
        headers['Authorization'] = f'token {Config.GITHUB_TOKEN}'
        logger.debug("Using authenticated API requests (5000 req/hour)")
    else:
        logger.warning("Using unauthenticated API requests (60 req/hour limit)")

    return headers


def check_rate_limit(response: requests.Response) -> None:
    """
    Check GitHub API rate limit from response headers.

    Args:
        response: Response object from requests
    """
    remaining = response.headers.get('X-RateLimit-Remaining')
    limit = response.headers.get('X-RateLimit-Limit')
    reset_time = response.headers.get('X-RateLimit-Reset')

    if remaining and limit:
        logger.debug(f"Rate limit: {remaining}/{limit} remaining")

        if int(remaining) < 5:
            logger.warning(f"Low rate limit: {remaining}/{limit} requests remaining")

            if reset_time:
                reset_dt = datetime.fromtimestamp(int(reset_time))
                logger.warning(f"Rate limit resets at: {reset_dt}")


def fetch_repository_list(since: int, per_page: int = 100) -> Tuple[List[Dict], int]:
    """
    STEP 1: Fetch repository list from /repositories endpoint.
    This is lightweight and returns basic repo info.

    Args:
        since: Repository ID to start from
        per_page: Number of repos per page (max 100)

    Returns:
        Tuple of (list of repo summaries, last repo ID in batch)
    """
    url = f"{Config.GITHUB_API_BASE_URL}/repositories"
    params = {
        'since': since,
        'per_page': per_page
    }

    headers = get_api_headers()

    logger.info(f"Fetching repository list (since={since}, per_page={per_page})")

    try:
        response = requests.get(url, headers=headers, params=params, timeout=30)
        response.raise_for_status()

        check_rate_limit(response)

        repos = response.json()

        if not repos:
            logger.info("No more repositories to fetch")
            return [], since

        last_id = repos[-1]['id']
        logger.info(f"Fetched {len(repos)} repositories (last ID: {last_id})")

        return repos, last_id

    except requests.exceptions.RequestException as e:
        logger.error(f"Failed to fetch repository list: {e}")
        return [], since


def fetch_repository_details(owner: str, repo_name: str, repo_id: int, use_cache: bool = True) -> Optional[Dict]:
    """
    STEP 2: Fetch detailed repository information.
    This endpoint provides complete metadata including stars, language, dates, etc.

    Args:
        owner: Repository owner login
        repo_name: Repository name
        repo_id: Repository ID (for caching)
        use_cache: Whether to use cached data if available

    Returns:
        Optional[Dict]: Detailed repository data or None if failed
    """
    # Check cache first
    if use_cache:
        cached_data = load_from_cache(repo_id, 'detail')
        if cached_data:
            return cached_data

    url = f"{Config.GITHUB_API_BASE_URL}/repos/{owner}/{repo_name}"
    headers = get_api_headers()

    logger.debug(f"Fetching details for {owner}/{repo_name}")

    try:
        # Rate limiting: wait between requests
        time.sleep(Config.REQUEST_DELAY)

        response = requests.get(url, headers=headers, timeout=30)
        response.raise_for_status()

        check_rate_limit(response)

        repo_data = response.json()

        # Cache the response
        if use_cache:
            save_to_cache(repo_id, repo_data, 'detail')

        return repo_data

    except requests.exceptions.HTTPError as e:
        if e.response.status_code == 404:
            logger.warning(f"Repository not found: {owner}/{repo_name} (may be deleted)")
        elif e.response.status_code == 403:
            logger.error(f"Rate limit exceeded or access forbidden")
        else:
            logger.error(f"HTTP error fetching {owner}/{repo_name}: {e}")
        return None

    except requests.exceptions.RequestException as e:
        logger.error(f"Failed to fetch details for {owner}/{repo_name}: {e}")
        return None


def flatten_repository_data(repo: Dict) -> Dict:
    """
    Flatten repository data with owner fields at top level.
    This makes it easier to query in Snowflake.

    Args:
        repo: Raw repository data from GitHub API

    Returns:
        Dict: Flattened repository data
    """
    try:
        return {
            # Repository fields
            'id': repo.get('id'),
            'name': repo.get('name'),
            'full_name': repo.get('full_name'),
            'html_url': repo.get('html_url'),
            'description': repo.get('description'),
            'stargazers_count': repo.get('stargazers_count'),
            'language': repo.get('language'),
            'created_at': repo.get('created_at'),
            'updated_at': repo.get('updated_at'),

            # Owner fields (flattened)
            'owner_login': repo.get('owner', {}).get('login'),
            'owner_id': repo.get('owner', {}).get('id'),
            'owner_type': repo.get('owner', {}).get('type'),
            'owner_avatar_url': repo.get('owner', {}).get('avatar_url'),
            'owner_url': repo.get('owner', {}).get('html_url'),
        }
    except Exception as e:
        logger.error(f"Error flattening repository data: {e}")
        return {}


def validate_repository(repo: Dict) -> Tuple[bool, List[str]]:
    """
    Validate that repository has all required fields.

    Args:
        repo: Flattened repository data

    Returns:
        Tuple of (is_valid, list of missing fields)
    """
    missing_fields = []

    for field in REQUIRED_FIELDS:
        if field not in repo or repo[field] is None:
            missing_fields.append(field)

    is_valid = len(missing_fields) == 0
    return is_valid, missing_fields


# ============================================================================
# S3 UPLOAD
# ============================================================================

def upload_to_s3(data: List[Dict], metadata: Dict) -> Optional[str]:
    """
    Upload repository data to S3 bucket.

    Args:
        data: List of repository dictionaries
        metadata: Metadata about the extraction

    Returns:
        Optional[str]: S3 key if successful, None otherwise
    """
    try:
        s3_client = boto3.client('s3', region_name=Config.AWS_REGION)

        now = datetime.now()
        timestamp = now.strftime('%Y-%m-%d_%H-%M-%S')

        # Build S3 key with optional date partitioning
        if Config.S3_USE_DATE_PARTITIONING:
            year = now.strftime('%Y')
            month = now.strftime('%m')
            day = now.strftime('%d')
            s3_key = f"{year}/{month}/{day}/github_repos_{timestamp}.json"
        else:
            s3_key = f"github_repos_{timestamp}.json"

        # Prepare upload data
        upload_data = {
            'metadata': metadata,
            'repositories': data
        }

        # Upload to S3
        logger.info(f"Uploading {len(data)} repositories to S3...")
        s3_client.put_object(
            Bucket=Config.AWS_S3_BUCKET,
            Key=s3_key,
            Body=json.dumps(upload_data, indent=2),
            ContentType='application/json'
        )

        logger.info(f"Successfully uploaded to s3://{Config.AWS_S3_BUCKET}/{s3_key}")
        return s3_key

    except Exception as e:
        logger.error(f"Failed to upload to S3: {e}")
        return None


# ============================================================================
# MAIN EXTRACTION LOGIC
# ============================================================================

def extract_repositories(test_mode: bool = False, use_cache: bool = True, skip_upload: bool = False) -> Dict:
    """
    Main extraction function implementing two-step process.

    STEP 1: Fetch repository list (lightweight, gets IDs)
    STEP 2: Fetch detailed info for each repository

    Args:
        test_mode: If True, only extract 1 page (100 repos)
        use_cache: Whether to use cached data
        skip_upload: If True, skip S3 upload

    Returns:
        Dict: Extraction summary and statistics
    """
    start_time = datetime.now()

    # Get last processed repo ID (resume capability)
    since = get_last_repo_id()

    # Calculate request budget
    if test_mode:
        max_repos = Config.REPOS_PER_PAGE * Config.TEST_MODE_PAGES  # 100 repos
        logger.info("=" * 80)
        logger.info("TEST MODE: Extracting 1 page (100 repositories)")
        logger.info("=" * 80)
    else:
        # In production: 1 request for list + N requests for details
        # With 60 req/hour limit: 1 list + 59 details = 59 repos
        max_repos = Config.MAX_REQUESTS_PER_RUN - 1
        logger.info("=" * 80)
        logger.info(f"PRODUCTION MODE: Max {max_repos} repositories")
        logger.info(f"Rate limit: {Config.MAX_REQUESTS_PER_RUN} requests/hour")
        logger.info("=" * 80)

    logger.info(f"Starting extraction from repo ID: {since}")

    # STEP 1: Fetch repository list
    logger.info("")
    logger.info("STEP 1: Fetching repository list...")
    logger.info("-" * 80)

    repo_list, last_id = fetch_repository_list(since, Config.REPOS_PER_PAGE)

    if not repo_list:
        logger.warning("No repositories fetched. Exiting.")
        return {
            'success': False,
            'message': 'No repositories to process'
        }

    logger.info(f"Retrieved {len(repo_list)} repositories from list endpoint")

    # Limit to request budget
    repos_to_process = repo_list[:max_repos]
    logger.info(f"Processing {len(repos_to_process)} repositories (budget: {max_repos})")

    # STEP 2: Fetch detailed information for each repo
    logger.info("")
    logger.info("STEP 2: Fetching detailed information for each repository...")
    logger.info("-" * 80)

    detailed_repos = []
    valid_count = 0
    invalid_count = 0
    failed_count = 0
    api_calls = 0
    cache_hits = 0

    for i, repo_summary in enumerate(repos_to_process, 1):
        repo_id = repo_summary['id']
        owner = repo_summary['owner']['login']
        name = repo_summary['name']

        logger.info(f"[{i}/{len(repos_to_process)}] Processing {owner}/{name} (ID: {repo_id})")

        # Fetch detailed information
        repo_detail = fetch_repository_details(owner, name, repo_id, use_cache)

        if repo_detail is None:
            failed_count += 1
            api_calls += 1
            continue

        # Track API usage
        if load_from_cache(repo_id, 'detail') and use_cache:
            cache_hits += 1
        else:
            api_calls += 1

        # Flatten the data
        flattened = flatten_repository_data(repo_detail)

        # Validate
        is_valid, missing = validate_repository(flattened)

        if is_valid:
            detailed_repos.append(flattened)
            valid_count += 1
            logger.debug(f"  ✓ Valid repository")
        else:
            invalid_count += 1
            if invalid_count <= 5:  # Only log first 5
                logger.warning(f"  ✗ Invalid repository (missing: {', '.join(missing)})")

        # Update last processed ID after each repo
        save_last_repo_id(repo_id)

    # Summary
    logger.info("")
    logger.info("=" * 80)
    logger.info("EXTRACTION COMPLETE")
    logger.info("=" * 80)
    logger.info(f"Total repositories processed: {len(repos_to_process)}")
    logger.info(f"Valid repositories: {valid_count}")
    logger.info(f"Invalid repositories: {invalid_count}")
    logger.info(f"Failed to fetch: {failed_count}")
    logger.info(f"API calls made: {api_calls}")
    logger.info(f"Cache hits: {cache_hits}")
    logger.info(f"Last repo ID: {repo_id}")

    # Prepare metadata
    metadata = {
        'extraction_date': datetime.now().isoformat(),
        'start_repo_id': since,
        'last_repo_id': repo_id,
        'total_processed': len(repos_to_process),
        'valid_count': valid_count,
        'invalid_count': invalid_count,
        'failed_count': failed_count,
        'api_calls': api_calls,
        'cache_hits': cache_hits,
        'test_mode': test_mode,
        'duration_seconds': (datetime.now() - start_time).total_seconds()
    }

    # Upload to S3
    s3_key = None
    if not skip_upload and detailed_repos:
        logger.info("")
        logger.info("Uploading to S3...")
        s3_key = upload_to_s3(detailed_repos, metadata)
    elif skip_upload:
        logger.info("")
        logger.info("Skipping S3 upload (--skip-upload flag)")
    else:
        logger.warning("")
        logger.warning("No valid repositories to upload")

    return {
        'success': True,
        'metadata': metadata,
        's3_key': s3_key,
        'repositories_count': len(detailed_repos)
    }


# ============================================================================
# MAIN ENTRY POINT
# ============================================================================

def main():
    """Main entry point for the script"""

    parser = argparse.ArgumentParser(
        description='Extract GitHub repository data with two-step process'
    )
    parser.add_argument(
        '--test-mode',
        action='store_true',
        help='Test mode: Extract only 1 page (100 repos)'
    )
    parser.add_argument(
        '--use-cache',
        action='store_true',
        default=Config.USE_CACHE,
        help='Use cached data if available'
    )
    parser.add_argument(
        '--skip-upload',
        action='store_true',
        help='Skip S3 upload (for testing)'
    )

    args = parser.parse_args()

    try:
        logger.info("GitHub Data Extraction Script - Two-Step Process")
        logger.info(f"Configuration:")
        logger.info(f"  - S3 Bucket: {Config.AWS_S3_BUCKET}")
        logger.info(f"  - S3 Region: {Config.AWS_REGION}")
        logger.info(f"  - Date Partitioning: {Config.S3_USE_DATE_PARTITIONING}")
        logger.info(f"  - Cache Enabled: {args.use_cache}")
        logger.info(f"  - Since Storage: {Config.SINCE_STORAGE_METHOD}")
        logger.info("")

        result = extract_repositories(
            test_mode=args.test_mode,
            use_cache=args.use_cache,
            skip_upload=args.skip_upload
        )

        if result['success']:
            logger.info("")
            logger.info("✓ Extraction completed successfully")
            if result.get('s3_key'):
                logger.info(f"✓ Data uploaded to: {result['s3_key']}")
            sys.exit(0)
        else:
            logger.error("✗ Extraction failed")
            sys.exit(1)

    except KeyboardInterrupt:
        logger.warning("")
        logger.warning("Extraction interrupted by user")
        logger.info("Progress has been saved. Run again to resume.")
        sys.exit(130)
    except Exception as e:
        logger.error(f"Unexpected error: {e}", exc_info=True)
        sys.exit(1)


if __name__ == '__main__':
    main()
