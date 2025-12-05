# High-Throughput Logs Distributor

A production-ready, high-throughput log distribution system that receives log packets from agents and distributes them to multiple analyzers based on configurable weights.

## Quick Start

```bash
# Build and start all services
docker-compose up --build -d

# Wait for services to initialize
sleep 20

# Verify system is healthy
./quick_test.sh

# Run performance demos
python3 tests/demo_weight_distribution.py
python3 tests/demo_failover.py
python3 tests/demo_throughput.py
```

Expected results:
- All containers running
- Distributor healthy with 4 analyzers
- Weight distribution: ~40%, ~30%, ~20%, ~10%
- Failover handling works automatically
- Throughput: 500-800 packets/sec, 95%+ success rate

## Architecture Overview

```
Agents → Distributor (Queue + Workers) → Analyzers
         Port 8000                        Ports 8001-8004
                                          40% / 30% / 20% / 10%
```

### Components

**Distributor**
- FastAPI async web server
- AsyncIO queue (5000 packet buffer)
- 10 concurrent async workers
- Weighted random selection
- Retry with exponential backoff
- Background health monitoring

**Analyzers**
- 4 mock analyzer services
- analyzer-1: 40% weight
- analyzer-2: 30% weight
- analyzer-3: 20% weight
- analyzer-4: 10% weight

### Data Model

```python
LogMessage:
  - timestamp: datetime
  - level: DEBUG | INFO | WARNING | ERROR | CRITICAL
  - source: string (service name)
  - message: string (log content)
  - metadata: dict (additional context)

LogPacket:
  - packet_id: string (unique identifier)
  - agent_id: string (agent identifier)
  - messages: List[LogMessage] (batch of logs)
```

## Key Features

1. **High Throughput**: AsyncIO-based for efficient I/O-bound workloads
2. **Weighted Distribution**: Configurable weights per analyzer
3. **Automatic Failover**: Health monitoring detects failures (every 5s)
4. **No Message Loss**: Retry logic with exponential backoff (up to 2 retries)
5. **Backpressure**: 503 errors when queue is full (protects system)
6. **Configuration-Driven**: All parameters via environment variables

## API Reference

### POST /ingest
Accepts log packets for distribution
- Returns: 202 Accepted (queued successfully)
- Returns: 503 Service Unavailable (queue full)

### GET /stats
Returns distribution statistics

### GET /health
Returns system health status (queue utilization, analyzer health)

## Demo Scripts

**1. Weight Distribution** (`tests/demo_weight_distribution.py`)
- Sends 1,000 packets
- Verifies distribution matches weights (±5% tolerance)

**2. Failover Handling** (`tests/demo_failover.py`)
- Stops analyzer-2
- Verifies traffic is redistributed
- Restarts analyzer-2
- Verifies traffic resumes

**3. High Throughput** (`tests/demo_throughput.py`)
- Sends 2,000 packets with 10 concurrent workers
- Measures throughput and latency
- Expected: 500+ packets/sec, 95%+ success rate

## Manual Testing

```bash
# Send a test packet
curl -X POST http://localhost:8000/ingest \
  -H "Content-Type: application/json" \
  -d '{
    "packet_id": "test-001",
    "agent_id": "test-agent",
    "messages": [{
      "timestamp": "2025-12-01T10:00:00Z",
      "level": "INFO",
      "source": "test-service",
      "message": "Test log message",
      "metadata": {"test": true}
    }]
  }'

# Check statistics
curl http://localhost:8000/stats | jq
curl http://localhost:8001/stats | jq  # analyzer-1
curl http://localhost:8002/stats | jq  # analyzer-2
```

## Configuration

Edit `distributor/config.py` or use environment variables:

```python
NUM_WORKERS = 10           # Concurrent workers
MAX_QUEUE_SIZE = 5000      # Queue capacity
MAX_RETRIES = 2            # Retry attempts
RETRY_DELAY = 0.5          # Initial retry delay (seconds)
HEALTH_CHECK_INTERVAL = 5  # Health check frequency (seconds)
```

## Project Structure

```
resolve_challenge/
├── distributor/
│   ├── main.py              # FastAPI server + workers
│   ├── models.py            # Data models
│   ├── distributor.py       # Weighted routing + retry
│   ├── health_monitor.py    # Health checking
│   └── config.py            # Configuration
├── analyzer/
│   └── analyzer.py          # Mock analyzer service
├── tests/
│   ├── demo_weight_distribution.py
│   ├── demo_failover.py
│   └── demo_throughput.py
├── docker-compose.yml
├── Dockerfile.distributor
├── Dockerfile.analyzer
├── requirements.txt
├── quick_test.sh
└── README.md (this file)
```

## Troubleshooting

**Services won't start**
```bash
docker-compose down -v
docker-compose up --build
```

**Demo scripts fail**
```bash
# Verify system is running
docker-compose ps

# Check health
curl http://localhost:8000/health

# Install dependencies
pip install -r requirements.txt
```

**Low throughput or 503 errors**
```bash
# Increase queue size
docker-compose down
# Edit distributor/config.py: MAX_QUEUE_SIZE = 10000
docker-compose up --build -d
```

## Performance Tuning

**For higher throughput:**
- Increase `NUM_WORKERS` (default: 10)
- Increase `MAX_QUEUE_SIZE` (default: 5000)
- Allocate more Docker resources (CPU/Memory)

**For faster failover detection:**
- Reduce `HEALTH_CHECK_INTERVAL` (default: 5s)
- Caution: More frequent checks = more overhead

## Stopping the System

```bash
# Stop all services
docker-compose down

# Stop and remove volumes
docker-compose down -v
```

## Documentation

- **README.md** (this file) - Quick start and usage
- **ARCHITECTURE.md** - Deep dive on design concepts
- **VISUAL_GUIDE.md** - Visual flow diagrams and scenarios

## License

This project is for demonstration purposes.
