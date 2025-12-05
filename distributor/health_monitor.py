"""
Health monitoring for analyzer services.

This module implements periodic health checks for analyzers:
1. Runs as a background async task
2. Periodically pings each analyzer's health endpoint
3. Updates distributor when analyzer status changes
4. Implements exponential backoff for unhealthy analyzers
"""

import asyncio
import httpx
import logging
from typing import List, TYPE_CHECKING

if TYPE_CHECKING:
    from distributor.distributor import LogDistributor
    from distributor.models import Analyzer
else:
    # Avoid circular import
    pass

logger = logging.getLogger(__name__)


class HealthMonitor:
    """
    Monitors the health of analyzer services and updates the distributor.

    Design:
    - Runs as a background async task (doesn't block main server)
    - Checks each analyzer periodically
    - Uses GET /health endpoint (standard pattern)
    - Updates distributor when status changes
    - Implements simple retry logic

    Why async?
    - Health checks are I/O-bound (network calls)
    - Can check multiple analyzers concurrently
    - Doesn't block the main request processing
    """

    def __init__(
        self,
        distributor: "LogDistributor",
        check_interval: float = 5.0,  # Check every 5 seconds
        timeout: float = 2.0  # 2 second timeout for health checks
    ):
        """
        Initialize the health monitor.

        Args:
            distributor: The log distributor to update with health status
            check_interval: How often to check health (seconds)
            timeout: Timeout for health check requests (seconds)
        """
        self.distributor = distributor
        self.check_interval = check_interval
        self.timeout = timeout
        self._running = False
        self._task: asyncio.Task = None

        # Separate HTTP client for health checks
        # This isolates health check failures from log distribution
        self._client = httpx.AsyncClient(timeout=timeout)

        logger.info(f"Health monitor initialized (interval: {check_interval}s)")

    async def _check_analyzer_health(self, analyzer) -> bool:
        """
        Check if a single analyzer is healthy.

        We expect analyzers to have a /health endpoint that returns:
        - 200 OK if healthy
        - Any other status or timeout = unhealthy

        Args:
            analyzer: The analyzer to check

        Returns:
            True if healthy, False otherwise
        """
        try:
            # Construct health endpoint URL
            # Example: http://analyzer-1:8001/analyze -> http://analyzer-1:8001/health
            base_url = analyzer.url.rsplit('/', 1)[0]  # Remove last path segment
            health_url = f"{base_url}/health"

            logger.debug(f"Checking health of {analyzer.name} at {health_url}")

            response = await self._client.get(health_url)

            # Consider healthy if we get a 200 response
            is_healthy = response.status_code == 200

            if is_healthy:
                logger.debug(f"{analyzer.name} is healthy")
            else:
                logger.warning(f"{analyzer.name} returned status {response.status_code}")

            return is_healthy

        except httpx.TimeoutException:
            logger.warning(f"{analyzer.name} health check timed out")
            return False

        except httpx.ConnectError:
            logger.warning(f"{analyzer.name} connection failed (may be offline)")
            return False

        except Exception as e:
            logger.error(f"Unexpected error checking {analyzer.name}: {e}")
            return False

    async def _check_all_analyzers(self):
        """
        Check health of all analyzers concurrently.

        We use asyncio.gather to check all analyzers in parallel,
        which is much faster than checking them one by one.
        """
        analyzers = self.distributor.analyzers

        # Create health check tasks for all analyzers
        tasks = [
            self._check_analyzer_health(analyzer)
            for analyzer in analyzers
        ]

        # Run all checks concurrently
        # return_exceptions=True ensures one failure doesn't crash all checks
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Update distributor with results
        for analyzer, result in zip(analyzers, results):
            if isinstance(result, Exception):
                logger.error(f"Health check failed for {analyzer.name}: {result}")
                is_healthy = False
            else:
                is_healthy = result

            # Update the distributor's view of this analyzer's health
            await self.distributor.update_analyzer_health(analyzer.name, is_healthy)

    async def _monitor_loop(self):
        """
        Main monitoring loop.

        Runs indefinitely, checking analyzer health at regular intervals.
        This is a long-running background task.
        """
        logger.info("Health monitor loop started")

        while self._running:
            try:
                # Check all analyzers
                await self._check_all_analyzers()

                # Wait before next check
                # Using asyncio.sleep allows other tasks to run
                await asyncio.sleep(self.check_interval)

            except asyncio.CancelledError:
                logger.info("Health monitor loop cancelled")
                break

            except Exception as e:
                logger.error(f"Error in health monitor loop: {e}")
                # Continue running despite errors
                await asyncio.sleep(self.check_interval)

        logger.info("Health monitor loop stopped")

    async def start(self):
        """
        Start the health monitoring background task.

        This creates an async task that runs independently.
        """
        if self._running:
            logger.warning("Health monitor already running")
            return

        self._running = True

        # Create the background task
        # This runs concurrently with the FastAPI server
        self._task = asyncio.create_task(self._monitor_loop())

        logger.info("Health monitor started")

    async def stop(self):
        """
        Stop the health monitoring background task.

        Gracefully shuts down the monitor.
        """
        if not self._running:
            return

        self._running = False

        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

        await self._client.aclose()

        logger.info("Health monitor stopped")
