"""
FastAPI web server for the log distributor.

This is the main entry point that:
1. Receives log packets via HTTP POST
2. Queues them for distribution (non-blocking)
3. Uses async workers for parallel distribution
4. Provides monitoring endpoints

Architecture:
- FastAPI async handlers for non-blocking request handling
- AsyncIO queue for buffering incoming packets
- Multiple async worker tasks for concurrent distribution
- Background tasks for queue processing and health monitoring
- All I/O operations use async/await (httpx AsyncClient)
"""

import asyncio
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
import uvicorn

from distributor.models import LogPacket, Analyzer, DistributorStats
from distributor.distributor import LogDistributor
from distributor.health_monitor import HealthMonitor
from distributor import config

# Configure logging
logging.basicConfig(
    level=getattr(logging, config.LOG_LEVEL),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# ===== CONFIGURATION =====

# Get analyzer configuration
ANALYZERS = config.get_analyzers()
NUM_WORKERS = config.NUM_WORKERS
MAX_QUEUE_SIZE = config.MAX_QUEUE_SIZE

# ===== GLOBAL STATE =====

# The queue that buffers incoming log packets
# AsyncIO queue is thread-safe and non-blocking
packet_queue: asyncio.Queue = None

# The distributor handles weighted routing
distributor: LogDistributor = None

# The health monitor checks analyzer availability
health_monitor: HealthMonitor = None

# Flag to control worker tasks
running = False


# ===== LIFECYCLE MANAGEMENT =====

@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Lifecycle manager for FastAPI app.

    This handles startup and shutdown:
    - Startup: Initialize distributor, health monitor, worker tasks
    - Shutdown: Clean up resources gracefully

    Using @asynccontextmanager allows us to do async setup/teardown.
    """
    global packet_queue, distributor, health_monitor, running

    logger.info("=== Starting Logs Distributor ===")

    # Initialize the packet queue
    packet_queue = asyncio.Queue(maxsize=MAX_QUEUE_SIZE)
    logger.info(f"Packet queue initialized (max size: {MAX_QUEUE_SIZE})")

    # Initialize the distributor
    distributor = LogDistributor(analyzers=ANALYZERS, timeout=config.ANALYZER_TIMEOUT)
    await distributor.initialize()
    logger.info(f"Distributor initialized with {len(ANALYZERS)} analyzers")

    # Initialize the health monitor
    health_monitor = HealthMonitor(
        distributor=distributor,
        check_interval=config.HEALTH_CHECK_INTERVAL,
        timeout=config.HEALTH_CHECK_TIMEOUT
    )
    await health_monitor.start()
    logger.info("Health monitor started")

    # Start async worker tasks that process the queue
    # These run concurrently using asyncio (no thread pool needed)
    running = True
    worker_tasks = [
        asyncio.create_task(queue_worker(i))
        for i in range(NUM_WORKERS)
    ]
    logger.info(f"Started {NUM_WORKERS} async queue workers")

    logger.info("=== Logs Distributor Ready ===")

    # Yield control to FastAPI (server runs here)
    yield

    # Shutdown sequence
    logger.info("=== Shutting Down Logs Distributor ===")

    # Stop accepting new work
    running = False

    # Cancel worker tasks
    for task in worker_tasks:
        task.cancel()
    await asyncio.gather(*worker_tasks, return_exceptions=True)

    # Stop health monitor
    await health_monitor.stop()

    # Close distributor
    await distributor.close()

    logger.info("=== Shutdown Complete ===")


# Create FastAPI app with lifecycle management
app = FastAPI(
    title="Logs Distributor",
    description="High-throughput log packet distributor with weighted routing",
    version="1.0.0",
    lifespan=lifespan
)


# ===== WORKER TASKS =====

async def queue_worker(worker_id: int):
    """
    Worker task that processes packets from the queue.

    Flow:
    1. Get packet from queue (blocks if queue is empty)
    2. Call distribute (async, non-blocking)
    3. Repeat

    Why async workers?
    - AsyncIO handles concurrency efficiently without threads
    - httpx AsyncClient uses non-blocking I/O
    - Multiple workers process queue in parallel
    - No GIL issues since we're I/O-bound not CPU-bound

    Args:
        worker_id: Identifier for this worker (for logging)
    """
    logger.info(f"Worker {worker_id} started")

    while running:
        try:
            # Get a packet from the queue
            # This blocks until a packet is available (but doesn't block other tasks)
            packet = await asyncio.wait_for(
                packet_queue.get(),
                timeout=1.0  # Check 'running' flag periodically
            )

            logger.debug(f"Worker {worker_id} processing packet {packet.packet_id}")

            # Distribute the packet (async, non-blocking)
            # Multiple workers can be doing this concurrently
            # Includes retry logic with exponential backoff
            success = await distributor.distribute(
                packet,
                max_retries=config.MAX_RETRIES,
                retry_delay=config.RETRY_DELAY
            )

            if not success:
                logger.error(f"Worker {worker_id} failed to distribute packet {packet.packet_id} after all retries")

            # Mark task as done in queue
            packet_queue.task_done()

        except asyncio.TimeoutError:
            # Queue was empty for 1 second, check if we should continue
            continue

        except asyncio.CancelledError:
            logger.info(f"Worker {worker_id} cancelled")
            break

        except Exception as e:
            logger.error(f"Worker {worker_id} error: {e}")
            # Continue running despite errors

    logger.info(f"Worker {worker_id} stopped")


# ===== API ENDPOINTS =====

@app.post("/ingest", status_code=202)
async def ingest_log_packet(packet: LogPacket):
    """
    Ingest a log packet for distribution.

    This endpoint:
    1. Validates the packet (FastAPI + Pydantic do this automatically)
    2. Adds it to the queue (non-blocking if space available)
    3. Returns immediately (202 Accepted)

    The actual distribution happens asynchronously in worker tasks.

    Status code 202 (Accepted) indicates:
    - Request was accepted
    - Processing will happen asynchronously
    - This is semantically correct for this use case

    Args:
        packet: The log packet to ingest

    Returns:
        Success message with packet ID

    Raises:
        HTTPException: If queue is full (503 Service Unavailable)
    """
    try:
        # Try to add to queue without blocking
        # If queue is full, this raises asyncio.QueueFull
        packet_queue.put_nowait(packet)

        logger.info(f"Accepted packet {packet.packet_id} from agent {packet.agent_id} "
                   f"with {len(packet.messages)} messages")

        return {
            "status": "accepted",
            "packet_id": packet.packet_id,
            "message": f"Packet queued for distribution ({len(packet.messages)} messages)"
        }

    except asyncio.QueueFull:
        # Queue is full - we need to apply backpressure
        # Return 503 (Service Unavailable) to tell client to retry later
        logger.error(f"Queue full, rejecting packet {packet.packet_id}")
        raise HTTPException(
            status_code=503,
            detail="Queue is full, please retry later"
        )


@app.get("/stats")
async def get_stats() -> DistributorStats:
    """
    Get current distribution statistics.

    This is useful for:
    - Demo validation (checking weight distribution)
    - Monitoring in production
    - Debugging distribution issues

    Returns:
        Current statistics including per-analyzer counts
    """
    return await distributor.get_stats()


@app.get("/health")
async def health_check():
    """
    Health check endpoint for the distributor itself.

    Returns:
    - Overall health status
    - Queue utilization
    - Analyzer health status

    This is used by:
    - Load balancers
    - Monitoring systems
    - Demo validation
    """
    stats = await distributor.get_stats()
    healthy_analyzers = await distributor.get_healthy_analyzers()

    queue_size = packet_queue.qsize()
    queue_utilization = queue_size / MAX_QUEUE_SIZE

    return {
        "status": "healthy",
        "queue_size": queue_size,
        "queue_utilization": f"{queue_utilization:.1%}",
        "total_packets_received": stats.total_packets_received,
        "total_messages_received": stats.total_messages_received,
        "failed_sends": stats.failed_sends,
        "analyzers": {
            "total": len(ANALYZERS),
            "healthy": len(healthy_analyzers),
            "unhealthy": len(ANALYZERS) - len(healthy_analyzers)
        },
        "analyzer_details": [
            {
                "name": a.name,
                "weight": a.weight,
                "is_healthy": a.is_healthy,
                "packets_received": stats.packets_per_analyzer.get(a.name, 0),
                "messages_received": stats.messages_per_analyzer.get(a.name, 0)
            }
            for a in ANALYZERS
        ]
    }


@app.get("/")
async def root():
    """Root endpoint with API information"""
    return {
        "service": "Logs Distributor",
        "version": "1.0.0",
        "endpoints": {
            "ingest": "POST /ingest - Submit log packets",
            "stats": "GET /stats - View distribution statistics",
            "health": "GET /health - Check service health"
        }
    }


# ===== MAIN =====

if __name__ == "__main__":
    """
    Run the server directly (for development).
    In production, use: uvicorn main:app --host 0.0.0.0 --port 8000
    """
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        log_level="info",
        # Enable auto-reload for development
        reload=False
    )
