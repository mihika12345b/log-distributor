"""
Configuration module for the log distributor.

This centralizes all configurable parameters to avoid hardcoded values.
In production, these would be loaded from environment variables or a config file.
"""

import os
from typing import List
from distributor.models import Analyzer


# ===== SERVER CONFIGURATION =====

# Number of async worker tasks for parallel distribution
# Increase for higher throughput (more concurrent HTTP requests to analyzers)
NUM_WORKERS = int(os.getenv("NUM_WORKERS", "10"))

# Queue size - max packets that can be buffered
# If queue fills up, we'll start rejecting requests (backpressure)
# Set higher to handle burst traffic, but uses more memory
MAX_QUEUE_SIZE = int(os.getenv("MAX_QUEUE_SIZE", "5000"))

# HTTP timeout for sending packets to analyzers (seconds)
ANALYZER_TIMEOUT = float(os.getenv("ANALYZER_TIMEOUT", "5.0"))


# ===== ANALYZER CONFIGURATION =====

# Define analyzers with their weights
# In production, this would come from service discovery or a config file
def get_analyzers() -> List[Analyzer]:
    """
    Get the list of configured analyzers.

    Supports environment variable override for flexibility:
    - ANALYZER_1_URL, ANALYZER_1_WEIGHT
    - ANALYZER_2_URL, ANALYZER_2_WEIGHT
    - etc.
    """
    analyzers = [
        Analyzer(
            name="analyzer-1",
            url=os.getenv("ANALYZER_1_URL", "http://analyzer-1:8001/analyze"),
            weight=float(os.getenv("ANALYZER_1_WEIGHT", "0.4"))
        ),
        Analyzer(
            name="analyzer-2",
            url=os.getenv("ANALYZER_2_URL", "http://analyzer-2:8002/analyze"),
            weight=float(os.getenv("ANALYZER_2_WEIGHT", "0.3"))
        ),
        Analyzer(
            name="analyzer-3",
            url=os.getenv("ANALYZER_3_URL", "http://analyzer-3:8003/analyze"),
            weight=float(os.getenv("ANALYZER_3_WEIGHT", "0.2"))
        ),
        Analyzer(
            name="analyzer-4",
            url=os.getenv("ANALYZER_4_URL", "http://analyzer-4:8004/analyze"),
            weight=float(os.getenv("ANALYZER_4_WEIGHT", "0.1"))
        ),
    ]

    # Validate weights sum to approximately 1.0
    total_weight = sum(a.weight for a in analyzers)
    if not (0.99 <= total_weight <= 1.01):
        import logging
        logger = logging.getLogger(__name__)
        logger.warning(f"Analyzer weights sum to {total_weight}, not 1.0. Distribution may not match expectations.")

    return analyzers


# ===== HEALTH MONITORING CONFIGURATION =====

# How often to check analyzer health (seconds)
HEALTH_CHECK_INTERVAL = float(os.getenv("HEALTH_CHECK_INTERVAL", "5.0"))

# Timeout for health check requests (seconds)
HEALTH_CHECK_TIMEOUT = float(os.getenv("HEALTH_CHECK_TIMEOUT", "2.0"))


# ===== RETRY CONFIGURATION =====

# Number of retry attempts for failed distributions
# Set to 0 to disable retries
MAX_RETRIES = int(os.getenv("MAX_RETRIES", "2"))

# Delay between retries (seconds)
RETRY_DELAY = float(os.getenv("RETRY_DELAY", "0.5"))


# ===== LOGGING CONFIGURATION =====

# Log level
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
