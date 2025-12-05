"""
Mock Analyzer Service

This simulates a log analyzer that:
1. Receives log packets from the distributor
2. Processes them (simulated with a small delay)
3. Tracks statistics
4. Provides health endpoint

In a real system, this would be a separate service doing actual log analysis
(pattern matching, anomaly detection, indexing, etc.)
"""

import asyncio
import logging
from datetime import datetime
from fastapi import FastAPI, HTTPException
import uvicorn
import sys
import os

# Allow importing models from parent directory
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from distributor.models import LogPacket

# Get analyzer name and port from environment variables
# This allows us to run multiple instances with different configs
ANALYZER_NAME = os.getenv("ANALYZER_NAME", "analyzer-unknown")
ANALYZER_PORT = int(os.getenv("ANALYZER_PORT", "8001"))

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format=f'%(asctime)s - {ANALYZER_NAME} - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Create FastAPI app
app = FastAPI(
    title=f"Log Analyzer - {ANALYZER_NAME}",
    description="Mock analyzer service for demo",
    version="1.0.0"
)

# ===== STATISTICS =====

# Track how many packets and messages this analyzer has received
stats = {
    "analyzer_name": ANALYZER_NAME,
    "start_time": datetime.utcnow().isoformat(),
    "packets_received": 0,
    "messages_received": 0,
    "total_bytes_processed": 0,
    "last_packet_time": None
}


# ===== ENDPOINTS =====

@app.post("/analyze")
async def analyze_logs(packet: LogPacket):
    """
    Receive and "analyze" a log packet.

    In a real analyzer, this would:
    - Parse and validate logs
    - Extract metrics/patterns
    - Store in database/index
    - Trigger alerts if needed

    For demo purposes, we:
    - Log receipt
    - Update statistics
    - Simulate processing time
    - Return success

    Args:
        packet: The log packet to analyze

    Returns:
        Analysis result
    """
    logger.info(f"Received packet {packet.packet_id} from agent {packet.agent_id} "
               f"with {len(packet.messages)} messages")

    # Update statistics
    stats["packets_received"] += 1
    stats["messages_received"] += len(packet.messages)
    stats["last_packet_time"] = datetime.utcnow().isoformat()

    # Calculate approximate size
    # In production, you'd track actual bytes
    estimated_bytes = sum(len(msg.message) for msg in packet.messages)
    stats["total_bytes_processed"] += estimated_bytes

    # Simulate processing time
    # Real analyzers would do actual work here:
    # - Parse logs
    # - Extract structured data
    # - Index into database
    # - Run anomaly detection
    # - etc.
    await asyncio.sleep(0.01)  # 10ms processing time

    logger.debug(f"Processed packet {packet.packet_id}")

    return {
        "status": "success",
        "analyzer": ANALYZER_NAME,
        "packet_id": packet.packet_id,
        "messages_processed": len(packet.messages),
        "timestamp": datetime.utcnow().isoformat()
    }


@app.get("/health")
async def health_check():
    """
    Health check endpoint.

    The distributor's health monitor calls this to check if we're alive.

    Returns:
        Health status
    """
    return {
        "status": "healthy",
        "analyzer": ANALYZER_NAME,
        "timestamp": datetime.utcnow().isoformat()
    }


@app.get("/stats")
async def get_stats():
    """
    Get analyzer statistics.

    Useful for demo validation - we can check how many packets
    each analyzer received and verify the distribution matches weights.

    Returns:
        Current statistics
    """
    return stats


@app.get("/")
async def root():
    """Root endpoint with service info"""
    return {
        "service": "Log Analyzer",
        "name": ANALYZER_NAME,
        "port": ANALYZER_PORT,
        "endpoints": {
            "analyze": "POST /analyze - Receive log packets",
            "health": "GET /health - Health check",
            "stats": "GET /stats - View statistics"
        }
    }


# ===== MAIN =====

if __name__ == "__main__":
    """
    Run the analyzer service.

    Port is configured via ANALYZER_PORT environment variable.
    """
    logger.info(f"Starting {ANALYZER_NAME} on port {ANALYZER_PORT}")

    uvicorn.run(
        "analyzer:app",
        host="0.0.0.0",
        port=ANALYZER_PORT,
        log_level="info"
    )
