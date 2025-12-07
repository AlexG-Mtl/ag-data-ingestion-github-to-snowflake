#!/bin/bash
# Helper script for common docker-compose operations

set -e  # Exit on error

# Colors for output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

# Check if .env.docker exists
if [ ! -f .env.docker ]; then
    echo -e "${RED}Error: .env.docker not found${NC}"
    echo "Create it from template: cp .env.docker.example .env.docker"
    exit 1
fi

# Function to print usage
usage() {
    echo "Usage: $0 {test|prod|custom|clean|shell|logs}"
    echo ""
    echo "Commands:"
    echo "  test    - Run in test mode (59 repos, skip upload)"
    echo "  prod    - Run in production mode (59 repos, upload to S3)"
    echo "  custom  - Run with custom flags (pass flags as argument)"
    echo "  clean   - Remove containers and volumes"
    echo "  shell   - Open interactive shell in container"
    echo "  logs    - View container logs"
    echo ""
    echo "Examples:"
    echo "  $0 test"
    echo "  $0 prod"
    echo "  $0 custom '--use-cache --skip-upload'"
    echo "  $0 clean"
    exit 1
}

# Parse command
case "${1:-}" in
    test)
        echo -e "${GREEN}Running in TEST mode (59 repos, no S3 upload)${NC}"
        docker-compose run --rm github-extractor --test-mode --skip-upload --use-cache
        ;;

    prod)
        echo -e "${GREEN}Running in PRODUCTION mode (59 repos, upload to S3)${NC}"
        docker-compose up
        ;;

    custom)
        if [ -z "${2:-}" ]; then
            echo -e "${RED}Error: Provide custom flags${NC}"
            echo "Example: $0 custom '--use-cache --test-mode'"
            exit 1
        fi
        echo -e "${GREEN}Running with custom flags: $2${NC}"
        docker-compose run --rm github-extractor $2
        ;;

    clean)
        echo -e "${YELLOW}Cleaning up containers and volumes...${NC}"
        docker-compose down -v
        echo -e "${GREEN}Cleanup complete${NC}"
        ;;

    shell)
        echo -e "${GREEN}Opening interactive shell...${NC}"
        docker-compose run --rm --entrypoint /bin/bash github-extractor
        ;;

    logs)
        echo -e "${GREEN}Showing logs...${NC}"
        docker-compose logs -f
        ;;

    *)
        usage
        ;;
esac
