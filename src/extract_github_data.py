#!/usr/bin/env python3
"""
GitHub Data Extraction Script
==============================
Extracts repository metadata from GitHub API, validates data quality,
and uploads to AWS S3 bucket for further processing.

Features:
- Pagination support with configurable limits
- Rate limiting detection and handling
- Response caching to minimize API usage during development
- Data quality validation
- S3 upload with timestamped filenames
- Comprehensive logging

Usage:
    python extract_github_data.py [--use-cache] [--skip-upload]
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
# REQUIRED FIELDS - Edit this list to customize data validation
# ============================================================================
# These fields are required for each repository to be considered valid.
# Repositories missing any of these fields will be filtered out.
#
# To answer analysis questions like:
# - Total repositories on GitHub: need 'id'
# - Most-starred repos: need 'stargazers_count', 'name', 'full_name'
# - Popular repos by language: need 'language', 'stargazers_count'
# - User/org repo count: need 'owner'
# - Trending by creation date: need 'created_at'
# - Language popularity over time: need 'language', 'created_at'

REQUIRED_FIELDS = [
    # Minimal required fields (always present in /repositories endpoint)
    'id',                  # Unique repository ID (required for counting)
    'name',                # Repository name
    'full_name',           # Full name (owner/repo)
    'owner',               # Owner information (user or organization)
    'html_url',            # Repository URL
    # NOTE: The /repositories endpoint returns minimal data for old repos.
    # If you need full metadata (created_at, stars, language, etc.),
    # consider using /search/repositories or individual repo API calls.
    # Uncomment fields below if you're using a different endpoint:
    # 'description',
    # 'created_at',
    # 'updated_at',
    # 'pushed_at',
    # 'stargazers_count',
    # 'watchers_count',
    # 'forks_count',
    # 'language',
    # 'open_issues_count',
    # 'default_branch',
    # 'size',
]


# ============================================================================
# CONFIGURATION
# ============================================================================

class Config:
    """Configuration management - loads from environment variables or defaults"""

    # AWS S3 Settings
    AWS_S3_BUCKET = os.getenv('AWS_S3_BUCKET', 'github-api0-upload')
    AWS_REGION = os.getenv('AWS_REGION', 'us-east-2')
    # Enable S3 folder partitioning by date (yyyy/mm/dd/)
    S3_USE_DATE_PARTITIONING = os.getenv('S3_USE_DATE_PARTITIONING', 'true').lower() == 'true'

    # GitHub API Settings
    GITHUB_API_BASE_URL = 'https://api.github.com'
    GITHUB_REPOS_ENDPOINT = '/repositories'
    GITHUB_TOKEN = os.getenv('GITHUB_TOKEN', '')  # Empty for unauthenticated

    # Extraction Settings
    PAGES_TO_EXTRACT = int(os.getenv('PAGES_TO_EXTRACT', '2'))
    REPOS_PER_PAGE = int(os.getenv('REPOS_PER_PAGE', '50'))  # Max is 100

    # Cache Settings
    USE_CACHE = os.getenv('USE_CACHE', 'true').lower() == 'true'
    CACHE_DIR = os.getenv('CACHE_DIR', 'cache')

    # Logging Settings
    LOG_LEVEL = os.getenv('LOG_LEVEL', 'INFO')
    LOG_DIR = os.getenv('LOG_DIR', 'logs')

    # Rate Limiting
    RATE_LIMIT_SLEEP = 60  # Sleep time when rate limited (seconds)


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
    # Create logs directory if it doesn't exist
    Path(Config.LOG_DIR).mkdir(parents=True, exist_ok=True)

    # Create logger
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
# CACHING FUNCTIONS
# ============================================================================

def get_cache_filename(page_number: int) -> str:
    """
    Generate cache filename for a specific page.

    Args:
        page_number: Page number being cached

    Returns:
        str: Cache file path
    """
    return f"{Config.CACHE_DIR}/github_repos_page_{page_number}.json"


def save_to_cache(page_number: int, data: List[Dict]) -> None:
    """
    Save API response to cache file for later use.
    This helps minimize API calls during development and testing.

    Args:
        page_number: Page number being cached
        data: Repository data to cache
    """
    Path(Config.CACHE_DIR).mkdir(parents=True, exist_ok=True)
    cache_file = get_cache_filename(page_number)

    with open(cache_file, 'w') as f:
        json.dump(data, f, indent=2)

    logger.debug(f"Cached page {page_number} to {cache_file}")


def load_from_cache(page_number: int) -> Optional[List[Dict]]:
    """
    Load API response from cache if available.

    Args:
        page_number: Page number to load from cache

    Returns:
        Optional[List[Dict]]: Cached data if available, None otherwise
    """
    cache_file = get_cache_filename(page_number)

    if os.path.exists(cache_file):
        with open(cache_file, 'r') as f:
            data = json.load(f)
        logger.info(f"Loaded page {page_number} from cache ({len(data)} repos)")
        return data

    return None


# ============================================================================
# GITHUB API FUNCTIONS
# ============================================================================

def get_api_headers() -> Dict[str, str]:
    """
    Build headers for GitHub API requests.
    Includes authentication token if available.

    Returns:
        Dict[str, str]: Request headers
    """
    headers = {
        'Accept': 'application/vnd.github.v3+json',
        'User-Agent': 'GitHub-Data-Extractor'
    }

    # Add authentication if token is provided
    if Config.GITHUB_TOKEN:
        headers['Authorization'] = f'token {Config.GITHUB_TOKEN}'
        logger.debug("Using authenticated API requests")
    else:
        logger.warning("Using unauthenticated API requests (60 req/hour limit)")

    return headers


def check_rate_limit(response: requests.Response) -> None:
    """
    Check GitHub API rate limit from response headers.
    Logs current rate limit status.

    Args:
        response: Response object from requests library
    """
    remaining = response.headers.get('X-RateLimit-Remaining')
    limit = response.headers.get('X-RateLimit-Limit')
    reset_time = response.headers.get('X-RateLimit-Reset')

    if remaining and limit:
        logger.info(f"Rate limit: {remaining}/{limit} remaining")

        if int(remaining) < 5:
            logger.warning(f"Low rate limit! Only {remaining} requests remaining")

        if reset_time:
            reset_datetime = datetime.fromtimestamp(int(reset_time))
            logger.info(f"Rate limit resets at: {reset_datetime}")


def fetch_repositories_page(page_number: int, use_cache: bool = True) -> Tuple[Optional[List[Dict]], bool]:
    """
    Fetch a single page of repositories from GitHub API.
    Uses cache if available and enabled.

    Args:
        page_number: Page number to fetch (starts at 1)
        use_cache: Whether to use cached data if available

    Returns:
        Tuple[Optional[List[Dict]], bool]:
            - List of repository dictionaries (or None on error)
            - Boolean indicating if data came from cache
    """
    # Check cache first if enabled
    if use_cache and Config.USE_CACHE:
        cached_data = load_from_cache(page_number)
        if cached_data:
            return cached_data, True

    # Build API URL with pagination parameters
    # since parameter: Only show repositories with ID greater than this
    # This implements pagination by repository ID
    since_id = (page_number - 1) * Config.REPOS_PER_PAGE
    url = f"{Config.GITHUB_API_BASE_URL}{Config.GITHUB_REPOS_ENDPOINT}"
    params = {
        'since': since_id,
        'per_page': Config.REPOS_PER_PAGE
    }

    logger.info(f"Fetching page {page_number} (since ID: {since_id})...")

    try:
        response = requests.get(
            url,
            params=params,
            headers=get_api_headers(),
            timeout=30
        )

        # Check rate limit status
        check_rate_limit(response)

        # Handle rate limiting
        if response.status_code == 403:
            if 'rate limit' in response.text.lower():
                logger.error("Rate limit exceeded!")
                logger.info(f"Sleeping for {Config.RATE_LIMIT_SLEEP} seconds...")
                time.sleep(Config.RATE_LIMIT_SLEEP)
                return None, False

        # Raise exception for other HTTP errors
        response.raise_for_status()

        # Parse JSON response
        repos = response.json()
        logger.info(f"Successfully fetched {len(repos)} repositories from page {page_number}")

        # Save to cache for future use
        save_to_cache(page_number, repos)

        return repos, False

    except requests.exceptions.RequestException as e:
        logger.error(f"Error fetching page {page_number}: {e}")
        return None, False


def extract_all_repositories(pages: int, use_cache: bool = True) -> List[Dict]:
    """
    Extract repositories from multiple pages.
    Aggregates all repository data into a single list.

    Args:
        pages: Number of pages to extract
        use_cache: Whether to use cached data if available

    Returns:
        List[Dict]: List of all repository dictionaries
    """
    all_repos = []
    cache_hits = 0
    api_calls = 0

    logger.info(f"Starting extraction of {pages} pages...")
    logger.info(f"Cache enabled: {use_cache and Config.USE_CACHE}")

    for page_num in range(1, pages + 1):
        repos, from_cache = fetch_repositories_page(page_num, use_cache)

        if repos is None:
            logger.warning(f"Skipping page {page_num} due to error")
            continue

        all_repos.extend(repos)

        if from_cache:
            cache_hits += 1
        else:
            api_calls += 1
            # Add small delay between API calls to be respectful
            if page_num < pages:
                time.sleep(1)

    logger.info(f"Extraction complete: {len(all_repos)} total repositories")
    logger.info(f"API calls: {api_calls}, Cache hits: {cache_hits}")

    return all_repos


# ============================================================================
# DATA VALIDATION FUNCTIONS
# ============================================================================

def validate_repository(repo: Dict) -> Tuple[bool, List[str]]:
    """
    Validate a single repository object for required fields and data quality.
    Uses the global REQUIRED_FIELDS list defined at the top of the file.

    Args:
        repo: Repository dictionary to validate

    Returns:
        Tuple[bool, List[str]]:
            - Boolean indicating if validation passed
            - List of validation error messages
    """
    errors = []

    # Check for required fields using global REQUIRED_FIELDS list
    for field in REQUIRED_FIELDS:
        if field not in repo:
            errors.append(f"Missing required field: {field}")

    # Validate data types and values
    if 'id' in repo and not isinstance(repo['id'], int):
        errors.append(f"Invalid id type: {type(repo['id'])}")

    if 'id' in repo and repo['id'] <= 0:
        errors.append(f"Invalid id value: {repo['id']}")

    if 'name' in repo and not repo['name']:
        errors.append("Repository name is empty")

    if 'stargazers_count' in repo and repo['stargazers_count'] < 0:
        errors.append(f"Invalid stargazers_count: {repo['stargazers_count']}")

    # Validate owner structure
    if 'owner' in repo:
        if not isinstance(repo['owner'], dict):
            errors.append("Owner is not a dictionary")
        elif 'login' not in repo['owner']:
            errors.append("Owner missing login field")

    return len(errors) == 0, errors


def filter_valid_repositories(repos: List[Dict]) -> Tuple[List[Dict], Dict]:
    """
    Filter repositories to keep only those that pass validation.
    Invalid repositories are excluded from the final dataset.

    Args:
        repos: List of repository dictionaries to validate

    Returns:
        Tuple[List[Dict], Dict]:
            - List of valid repositories only
            - Validation summary with statistics
    """
    logger.info("Starting data validation and filtering...")

    total_repos = len(repos)
    valid_repos_list = []
    invalid_repos = 0
    all_errors = []

    for idx, repo in enumerate(repos):
        is_valid, errors = validate_repository(repo)

        if is_valid:
            valid_repos_list.append(repo)
        else:
            invalid_repos += 1
            repo_name = repo.get('full_name', f'Unknown (index {idx})')
            # Only log first few invalid repos to avoid cluttering logs
            if invalid_repos <= 5:
                logger.warning(f"Filtering out invalid repo {repo_name}: {errors[:3]}")  # Show first 3 errors
            all_errors.extend(errors)

    valid_count = len(valid_repos_list)

    # Generate summary statistics
    summary = {
        'total_repositories_extracted': total_repos,
        'valid_repositories': valid_count,
        'invalid_repositories_filtered': invalid_repos,
        'validation_rate': f"{(valid_count/total_repos*100):.2f}%" if total_repos > 0 else "0%",
        'total_errors': len(all_errors),
        'unique_errors': len(set(all_errors))
    }

    logger.info(f"Validation complete: {valid_count}/{total_repos} repositories valid")
    logger.info(f"Filtered out: {invalid_repos} invalid repositories")
    logger.info(f"Validation rate: {summary['validation_rate']}")

    if invalid_repos > 5:
        logger.info(f"Suppressed {invalid_repos - 5} validation warnings (too many to display)")

    return valid_repos_list, summary


def validate_all_repositories(repos: List[Dict]) -> Dict:
    """
    Validate all repositories and generate data quality report.
    NOTE: This function only reports validation status, does NOT filter.
    Use filter_valid_repositories() to exclude invalid repos.

    Args:
        repos: List of repository dictionaries to validate

    Returns:
        Dict: Validation summary with statistics
    """
    logger.info("Starting data validation...")

    total_repos = len(repos)
    valid_repos = 0
    invalid_repos = 0
    all_errors = []

    for idx, repo in enumerate(repos):
        is_valid, errors = validate_repository(repo)

        if is_valid:
            valid_repos += 1
        else:
            invalid_repos += 1
            repo_name = repo.get('full_name', f'Unknown (index {idx})')
            logger.debug(f"Validation failed for {repo_name}: {errors}")
            all_errors.extend(errors)

    # Generate summary statistics
    summary = {
        'total_repositories': total_repos,
        'valid_repositories': valid_repos,
        'invalid_repositories': invalid_repos,
        'validation_rate': f"{(valid_repos/total_repos*100):.2f}%" if total_repos > 0 else "0%",
        'total_errors': len(all_errors),
        'unique_errors': len(set(all_errors))
    }

    logger.info(f"Validation complete: {valid_repos}/{total_repos} repositories valid")
    logger.info(f"Validation rate: {summary['validation_rate']}")

    if invalid_repos > 0:
        logger.warning(f"Found {invalid_repos} invalid repositories")

    return summary


def get_data_statistics(repos: List[Dict]) -> Dict:
    """
    Calculate statistics about the extracted data.

    Args:
        repos: List of repository dictionaries

    Returns:
        Dict: Statistics summary
    """
    if not repos:
        return {}

    # Language distribution
    languages = {}
    total_stars = 0
    total_forks = 0

    for repo in repos:
        lang = repo.get('language', 'Unknown')
        languages[lang] = languages.get(lang, 0) + 1
        total_stars += repo.get('stargazers_count', 0)
        total_forks += repo.get('forks_count', 0)

    # Sort languages by count
    top_languages = sorted(languages.items(), key=lambda x: x[1], reverse=True)[:10]

    stats = {
        'total_repositories': len(repos),
        'total_stars': total_stars,
        'total_forks': total_forks,
        'average_stars': total_stars / len(repos) if repos else 0,
        'average_forks': total_forks / len(repos) if repos else 0,
        'top_10_languages': dict(top_languages),
        'unique_languages': len(languages)
    }

    logger.info(f"Data statistics: {stats['total_repositories']} repos, "
                f"{stats['total_stars']} total stars, "
                f"{stats['unique_languages']} unique languages")

    return stats


# ============================================================================
# S3 UPLOAD FUNCTIONS
# ============================================================================

def upload_to_s3(data: List[Dict], metadata: Dict) -> Optional[str]:
    """
    Upload repository data to S3 bucket with optional date partitioning.

    S3 Structure:
    - With partitioning (default): s3://bucket/yyyy/mm/dd/github_repos_YYYY-MM-DD_HH-MM-SS.json
    - Without partitioning: s3://bucket/github_repos_YYYY-MM-DD_HH-MM-SS.json

    Args:
        data: List of repository dictionaries to upload
        metadata: Metadata about the extraction (validation, statistics)

    Returns:
        Optional[str]: S3 object key if successful, None otherwise
    """
    # Generate timestamp and filename
    now = datetime.now()
    timestamp = now.strftime('%Y-%m-%d_%H-%M-%S')
    base_filename = f"github_repos_{timestamp}.json"

    # Build S3 key with optional date partitioning
    if Config.S3_USE_DATE_PARTITIONING:
        # Create folder structure: yyyy/mm/dd/filename
        year = now.strftime('%Y')
        month = now.strftime('%m')
        day = now.strftime('%d')
        s3_key = f"{year}/{month}/{day}/{base_filename}"
        logger.info(f"Using date partitioning: {year}/{month}/{day}/")
    else:
        s3_key = base_filename
        logger.info("Date partitioning disabled, uploading to root")

    # Prepare data package with metadata
    data_package = {
        'metadata': {
            'extraction_timestamp': timestamp,
            'total_repositories': len(data),
            'pages_extracted': Config.PAGES_TO_EXTRACT,
            'repos_per_page': Config.REPOS_PER_PAGE,
            **metadata
        },
        'repositories': data
    }

    try:
        # Initialize S3 client
        s3_client = boto3.client('s3', region_name=Config.AWS_REGION)

        logger.info(f"Uploading to S3: s3://{Config.AWS_S3_BUCKET}/{s3_key}")

        # Upload JSON data
        s3_client.put_object(
            Bucket=Config.AWS_S3_BUCKET,
            Key=s3_key,
            Body=json.dumps(data_package, indent=2),
            ContentType='application/json',
            Metadata={
                'extraction-timestamp': timestamp,
                'repository-count': str(len(data))
            }
        )

        logger.info(f"Successfully uploaded {len(data)} repositories to S3")
        logger.info(f"S3 URI: s3://{Config.AWS_S3_BUCKET}/{s3_key}")

        return s3_key

    except Exception as e:
        logger.error(f"Failed to upload to S3: {e}")
        return None


# ============================================================================
# MAIN EXECUTION
# ============================================================================

def main():
    """
    Main execution function.
    Orchestrates the complete extraction, validation, and upload process.
    """
    # Parse command line arguments
    parser = argparse.ArgumentParser(description='Extract GitHub repository data')
    parser.add_argument('--use-cache', action='store_true',
                       help='Use cached API responses if available')
    parser.add_argument('--skip-upload', action='store_true',
                       help='Skip S3 upload (for testing)')
    args = parser.parse_args()

    logger.info("="*70)
    logger.info("GitHub Data Extraction Pipeline Starting")
    logger.info("="*70)
    logger.info(f"Configuration:")
    logger.info(f"  - Pages to extract: {Config.PAGES_TO_EXTRACT}")
    logger.info(f"  - Repos per page: {Config.REPOS_PER_PAGE}")
    logger.info(f"  - Expected total repos: ~{Config.PAGES_TO_EXTRACT * Config.REPOS_PER_PAGE}")
    logger.info(f"  - S3 Bucket: {Config.AWS_S3_BUCKET}")
    logger.info(f"  - AWS Region: {Config.AWS_REGION}")
    logger.info(f"  - Use cache: {args.use_cache or Config.USE_CACHE}")
    logger.info(f"  - Skip upload: {args.skip_upload}")
    logger.info("="*70)

    # Step 1: Extract repositories
    logger.info("STEP 1: Extracting repositories from GitHub API")
    repositories = extract_all_repositories(
        pages=Config.PAGES_TO_EXTRACT,
        use_cache=args.use_cache or Config.USE_CACHE
    )

    if not repositories:
        logger.error("No repositories extracted. Exiting.")
        return 1

    # Step 2: Validate and filter data quality
    logger.info("STEP 2: Validating and filtering data quality")
    valid_repositories, validation_summary = filter_valid_repositories(repositories)

    if not valid_repositories:
        logger.error("No valid repositories after filtering. Exiting.")
        logger.error("Consider adjusting REQUIRED_FIELDS at top of script")
        return 1

    # Step 3: Calculate statistics (only on valid repos)
    logger.info("STEP 3: Calculating data statistics")
    statistics = get_data_statistics(valid_repositories)

    # Step 4: Upload to S3
    if not args.skip_upload:
        logger.info("STEP 4: Uploading to S3")
        metadata = {
            'validation': validation_summary,
            'statistics': statistics
        }
        s3_key = upload_to_s3(valid_repositories, metadata)

        if not s3_key:
            logger.error("S3 upload failed. Exiting.")
            return 1
    else:
        logger.info("STEP 4: Skipping S3 upload (--skip-upload flag set)")

    # Final summary
    logger.info("="*70)
    logger.info("Extraction Pipeline Complete!")
    logger.info("="*70)
    logger.info(f"Summary:")
    logger.info(f"  ✓ Repositories extracted: {validation_summary['total_repositories_extracted']}")
    logger.info(f"  ✓ Valid repositories uploaded: {len(valid_repositories)}")
    logger.info(f"  ✓ Invalid repositories filtered: {validation_summary['invalid_repositories_filtered']}")
    logger.info(f"  ✓ Validation rate: {validation_summary['validation_rate']}")
    logger.info(f"  ✓ Top language: {list(statistics['top_10_languages'].keys())[0] if statistics['top_10_languages'] else 'N/A'}")
    if not args.skip_upload:
        logger.info(f"  ✓ S3 upload: Success")
    logger.info("="*70)

    return 0


if __name__ == '__main__':
    sys.exit(main())
