#!/bin/bash

# Setup validation script
# This script tests that the Docker setup works correctly out-of-the-box

set -e  # Exit on error

echo "======================================"
echo "  Docker Setup Validation"
echo "======================================"
echo ""

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Check Docker is installed and running
echo "1. Checking Docker..."
if ! command -v docker &> /dev/null; then
    echo -e "${RED}✗ Docker is not installed${NC}"
    exit 1
fi

if ! docker info > /dev/null 2>&1; then
    echo -e "${RED}✗ Docker is not running${NC}"
    exit 1
fi
echo -e "${GREEN}✓ Docker is installed and running${NC}"

# Check Docker Compose is available
echo ""
echo "2. Checking Docker Compose..."
if ! docker-compose --version &> /dev/null && ! docker compose version &> /dev/null; then
    echo -e "${RED}✗ Docker Compose is not available${NC}"
    exit 1
fi
echo -e "${GREEN}✓ Docker Compose is available${NC}"

# Validate docker-compose.yml
echo ""
echo "3. Validating docker-compose.yml..."
if docker-compose config > /dev/null 2>&1 || docker compose config > /dev/null 2>&1; then
    echo -e "${GREEN}✓ docker-compose.yml is valid${NC}"
else
    echo -e "${RED}✗ docker-compose.yml has errors${NC}"
    exit 1
fi

# Clean up any existing containers
echo ""
echo "4. Cleaning up existing containers..."
docker-compose down -v 2>/dev/null || docker compose down -v 2>/dev/null || true
echo -e "${GREEN}✓ Cleanup complete${NC}"

# Build images
echo ""
echo "5. Building Docker images..."
echo -e "${YELLOW}   (This may take a few minutes on first run)${NC}"
if docker-compose build --no-cache > build.log 2>&1 || docker compose build --no-cache > build.log 2>&1; then
    echo -e "${GREEN}✓ Images built successfully${NC}"
else
    echo -e "${RED}✗ Image build failed. Check build.log for details${NC}"
    tail -20 build.log
    exit 1
fi

# Start services
echo ""
echo "6. Starting services..."
if docker-compose up -d > startup.log 2>&1 || docker compose up -d > startup.log 2>&1; then
    echo -e "${GREEN}✓ Services started${NC}"
else
    echo -e "${RED}✗ Service startup failed. Check startup.log for details${NC}"
    tail -20 startup.log
    exit 1
fi

# Wait for services to be ready
echo ""
echo "7. Waiting for services to be ready..."
echo -e "${YELLOW}   (Waiting 30 seconds for initialization)${NC}"
sleep 30

# Check all containers are running
echo ""
echo "8. Checking container status..."
CONTAINERS=("logs-distributor" "analyzer-1" "analyzer-2" "analyzer-3" "analyzer-4")
ALL_RUNNING=true

for container in "${CONTAINERS[@]}"; do
    if docker ps --filter "name=$container" --filter "status=running" | grep -q "$container"; then
        echo -e "${GREEN}   ✓ $container is running${NC}"
    else
        echo -e "${RED}   ✗ $container is not running${NC}"
        ALL_RUNNING=false
    fi
done

if [ "$ALL_RUNNING" = false ]; then
    echo -e "${RED}✗ Not all containers are running${NC}"
    echo ""
    echo "Container logs:"
    docker-compose logs --tail=50
    exit 1
fi

# Test distributor health endpoint
echo ""
echo "9. Testing distributor health endpoint..."
for i in {1..10}; do
    if curl -s -f http://localhost:8000/health > /dev/null 2>&1; then
        echo -e "${GREEN}✓ Distributor health check passed${NC}"
        break
    elif [ $i -eq 10 ]; then
        echo -e "${RED}✗ Distributor health check failed after 10 attempts${NC}"
        docker logs logs-distributor --tail=50
        exit 1
    else
        echo -e "${YELLOW}   Attempt $i/10... waiting${NC}"
        sleep 3
    fi
done

# Test all analyzer health endpoints
echo ""
echo "10. Testing analyzer health endpoints..."
for port in 8001 8002 8003 8004; do
    if curl -s -f http://localhost:$port/health > /dev/null 2>&1; then
        echo -e "${GREEN}   ✓ Analyzer on port $port is healthy${NC}"
    else
        echo -e "${RED}   ✗ Analyzer on port $port health check failed${NC}"
        docker logs "analyzer-$((port-8000))" --tail=20
        exit 1
    fi
done

# Test sending a packet
echo ""
echo "11. Testing packet ingestion..."
RESPONSE=$(curl -s -X POST http://localhost:8000/ingest \
  -H "Content-Type: application/json" \
  -d '{
    "packet_id": "test-setup-001",
    "agent_id": "test-agent",
    "messages": [{
      "timestamp": "2025-11-30T00:00:00Z",
      "level": "INFO",
      "source": "test",
      "message": "Setup test message",
      "metadata": {}
    }]
  }')

if echo "$RESPONSE" | grep -q "accepted"; then
    echo -e "${GREEN}✓ Packet ingestion successful${NC}"
else
    echo -e "${RED}✗ Packet ingestion failed${NC}"
    echo "Response: $RESPONSE"
    exit 1
fi

# Verify stats are being collected
echo ""
echo "12. Verifying statistics collection..."
sleep 2  # Wait for processing
STATS=$(curl -s http://localhost:8000/stats)

if echo "$STATS" | grep -q "total_packets_received"; then
    PACKETS=$(echo "$STATS" | grep -o '"total_packets_received":[0-9]*' | grep -o '[0-9]*')
    if [ "$PACKETS" -ge 1 ]; then
        echo -e "${GREEN}✓ Statistics collection working (received $PACKETS packet(s))${NC}"
    else
        echo -e "${YELLOW}⚠ Statistics showing 0 packets${NC}"
    fi
else
    echo -e "${RED}✗ Statistics endpoint not working properly${NC}"
    echo "Stats: $STATS"
    exit 1
fi

# Final summary
echo ""
echo "======================================"
echo -e "${GREEN}✓ All setup tests passed!${NC}"
echo "======================================"
echo ""
echo "System is ready. You can now:"
echo "  - Run demos: ./run_demos.sh"
echo "  - Check status: docker-compose ps"
echo "  - View logs: docker-compose logs -f"
echo "  - Stop system: docker-compose down"
echo ""

# Keep services running
echo "Services are still running. To stop them:"
echo "  docker-compose down"
echo ""
