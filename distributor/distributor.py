"""
Core distribution logic for routing log packets to analyzers.

This module implements the weighted distribution algorithm with the following features:
1. Thread-safe weighted random selection
2. Automatic exclusion of unhealthy analyzers
3. Dynamic weight renormalization when analyzers go offline
4. Statistics tracking for demo validation
"""

import random
import httpx
import asyncio
from typing import List, Optional
from distributor.models import LogPacket, Analyzer, DistributorStats
import logging

logger = logging.getLogger(__name__)


class LogDistributor:
    """
    Manages the distribution of log packets to multiple analyzers based on weights.

    Architecture:
    - Uses weighted random selection (simpler and stateless compared to round-robin)
    - Thread-safe using threading.Lock for shared state
    - AsyncIO for non-blocking HTTP calls to analyzers
    - Automatically adjusts for offline analyzers

    Why weighted random vs weighted round-robin?
    - Stateless: No need to track "next" analyzer per thread
    - Simpler implementation: Just pick randomly based on weights
    - Good enough distribution: Over large N, distribution converges to weights
    - Thread-safe by default: No shared counter to manage
    """

    def __init__(self, analyzers: List[Analyzer], timeout: float = 5.0):
        """
        Initialize the distributor.

        Args:
            analyzers: List of analyzer configurations
            timeout: HTTP timeout for sending to analyzers (seconds)
        """
        self.analyzers = analyzers
        self.timeout = timeout

        # Async lock for accessing shared state (analyzers list and stats)
        # This is critical because multiple async workers will be selecting analyzers
        # and updating statistics concurrently
        # Using asyncio.Lock() since we're in an async context, NOT threading.Lock()
        self._lock = asyncio.Lock()

        # Statistics for monitoring and demo validation
        self.stats = DistributorStats()

        # Initialize per-analyzer stats
        for analyzer in analyzers:
            self.stats.packets_per_analyzer[analyzer.name] = 0
            self.stats.messages_per_analyzer[analyzer.name] = 0

        # Async HTTP client for sending packets to analyzers
        # Using httpx because it supports async/await and connection pooling
        self._client: Optional[httpx.AsyncClient] = None

        logger.info(f"Initialized distributor with {len(analyzers)} analyzers")

    async def initialize(self):
        """
        Initialize async resources (HTTP client).
        Must be called before using the distributor.
        """
        self._client = httpx.AsyncClient(
            timeout=self.timeout,
            limits=httpx.Limits(
                max_keepalive_connections=20,  # Keep connections alive for reuse
                max_connections=100  # Max concurrent connections
            )
        )
        logger.info("HTTP client initialized")

    async def close(self):
        """Clean up async resources"""
        if self._client:
            await self._client.aclose()
            logger.info("HTTP client closed")

    async def _select_analyzer(self) -> Optional[Analyzer]:
        """
        Select an analyzer using weighted random selection.

        Algorithm:
        1. Filter to only healthy analyzers
        2. If no healthy analyzers, return None
        3. Calculate total weight of healthy analyzers
        4. Generate random number in [0, total_weight)
        5. Iterate through analyzers, accumulating weights until we exceed random number

        Example with weights [0.4, 0.3, 0.3]:
        - Total weight = 1.0
        - Random = 0.55
        - Cumulative: 0.4 (skip), 0.7 (selected!) -> returns analyzer 2

        Concurrency Safety:
        - Uses async lock to safely read analyzer list and health status
        - Lock is released quickly (only during selection, not during HTTP call)
        - Multiple async workers can call this concurrently

        Returns:
            Selected analyzer, or None if all analyzers are unhealthy
        """
        async with self._lock:
            # Filter to only healthy analyzers
            healthy_analyzers = [a for a in self.analyzers if a.is_healthy]

            if not healthy_analyzers:
                logger.warning("No healthy analyzers available")
                return None

            # Calculate total weight of healthy analyzers
            total_weight = sum(a.weight for a in healthy_analyzers)

            if total_weight == 0:
                logger.error("Total weight is 0, cannot select analyzer")
                return None

            # Weighted random selection
            # Generate random number in [0, total_weight)
            rand = random.uniform(0, total_weight)

            # Accumulate weights until we exceed the random number
            cumulative_weight = 0.0
            for analyzer in healthy_analyzers:
                cumulative_weight += analyzer.weight
                if rand < cumulative_weight:
                    logger.debug(f"Selected analyzer: {analyzer.name} (weight: {analyzer.weight})")
                    return analyzer

            # Fallback (shouldn't happen due to math, but just in case)
            return healthy_analyzers[-1]

    async def _send_to_analyzer(self, packet: LogPacket, analyzer: Analyzer) -> bool:
        """
        Send a packet to a specific analyzer.

        This is separated from distribute() to enable retry logic.

        Args:
            packet: The log packet to send
            analyzer: The target analyzer

        Returns:
            True if sent successfully, False otherwise

        Raises:
            httpx exceptions on failure (for retry handling)
        """
        logger.debug(f"Sending packet {packet.packet_id} to {analyzer.name}")

        response = await self._client.post(
            analyzer.url,
            json=packet.model_dump(mode='json'),  # Convert Pydantic model to JSON
            headers={"Content-Type": "application/json"}
        )

        response.raise_for_status()  # Raise exception for 4xx/5xx status codes

        logger.info(f"Successfully sent packet {packet.packet_id} to {analyzer.name}")
        return True

    async def distribute(self, packet: LogPacket, max_retries: int = 2, retry_delay: float = 0.5) -> bool:
        """
        Distribute a log packet to a selected analyzer with retry logic.

        Flow:
        1. Select analyzer using weighted random
        2. Attempt to send packet to analyzer
        3. On failure, retry with exponential backoff (up to max_retries)
        4. On each retry, may select a different analyzer
        5. Update statistics

        Retry Strategy:
        - Retries on timeout or network errors (transient failures)
        - Does NOT retry on 4xx errors (client errors like bad request)
        - Exponential backoff between retries
        - Each retry may select a different healthy analyzer

        Args:
            packet: The log packet to distribute
            max_retries: Maximum number of retry attempts
            retry_delay: Base delay between retries (seconds, exponentially increased)

        Returns:
            True if sent successfully, False if all attempts failed
        """
        last_error = None

        for attempt in range(max_retries + 1):
            # Select an analyzer based on weights and health
            # We reselect on each attempt in case the first analyzer went down
            analyzer = await self._select_analyzer()

            if not analyzer:
                logger.error(f"No analyzer available for packet {packet.packet_id}")
                async with self._lock:
                    self.stats.failed_sends += 1
                return False

            try:
                # Attempt to send the packet
                success = await self._send_to_analyzer(packet, analyzer)

                if success:
                    # Update statistics atomically
                    async with self._lock:
                        self.stats.total_packets_received += 1
                        self.stats.total_messages_received += len(packet.messages)
                        self.stats.packets_per_analyzer[analyzer.name] += 1
                        self.stats.messages_per_analyzer[analyzer.name] += len(packet.messages)

                    return True

            except httpx.TimeoutException as e:
                last_error = f"Timeout sending to {analyzer.name}"
                logger.warning(f"{last_error} (attempt {attempt + 1}/{max_retries + 1})")

                # Retry on timeout (transient failure)
                if attempt < max_retries:
                    # Exponential backoff
                    delay = retry_delay * (2 ** attempt)
                    await asyncio.sleep(delay)
                    continue

            except httpx.ConnectError as e:
                last_error = f"Connection error to {analyzer.name}"
                logger.warning(f"{last_error} (attempt {attempt + 1}/{max_retries + 1})")

                # Retry on connection errors (transient failure)
                if attempt < max_retries:
                    delay = retry_delay * (2 ** attempt)
                    await asyncio.sleep(delay)
                    continue

            except httpx.HTTPStatusError as e:
                # Don't retry on 4xx errors (client errors)
                if 400 <= e.response.status_code < 500:
                    logger.error(f"Client error {e.response.status_code} sending packet {packet.packet_id} to {analyzer.name} - not retrying")
                    async with self._lock:
                        self.stats.failed_sends += 1
                    return False

                # Retry on 5xx errors (server errors)
                last_error = f"HTTP {e.response.status_code} from {analyzer.name}"
                logger.warning(f"{last_error} (attempt {attempt + 1}/{max_retries + 1})")

                if attempt < max_retries:
                    delay = retry_delay * (2 ** attempt)
                    await asyncio.sleep(delay)
                    continue

            except Exception as e:
                last_error = f"Unexpected error sending to {analyzer.name}: {e}"
                logger.error(f"{last_error} (attempt {attempt + 1}/{max_retries + 1})")

                # Retry on unexpected errors
                if attempt < max_retries:
                    delay = retry_delay * (2 ** attempt)
                    await asyncio.sleep(delay)
                    continue

        # All retry attempts exhausted
        logger.error(f"Failed to send packet {packet.packet_id} after {max_retries + 1} attempts. Last error: {last_error}")
        async with self._lock:
            self.stats.failed_sends += 1
        return False

    async def update_analyzer_health(self, analyzer_name: str, is_healthy: bool):
        """
        Update the health status of an analyzer.
        Called by the health monitor when it detects an analyzer is down/up.

        Async-safe update of analyzer health status.

        Args:
            analyzer_name: Name of the analyzer
            is_healthy: New health status
        """
        async with self._lock:
            for analyzer in self.analyzers:
                if analyzer.name == analyzer_name:
                    old_status = analyzer.is_healthy
                    analyzer.is_healthy = is_healthy

                    if old_status != is_healthy:
                        status_str = "HEALTHY" if is_healthy else "UNHEALTHY"
                        logger.warning(f"Analyzer {analyzer_name} marked as {status_str}")

                    return

            logger.error(f"Analyzer {analyzer_name} not found in distributor")

    async def get_stats(self) -> DistributorStats:
        """
        Get current distribution statistics.
        Async-safe read of stats.

        Returns:
            Current statistics
        """
        async with self._lock:
            # Return a copy to avoid external modifications
            return self.stats.model_copy(deep=True)

    async def get_healthy_analyzers(self) -> List[Analyzer]:
        """
        Get list of currently healthy analyzers.
        Async-safe read.

        Returns:
            List of healthy analyzers
        """
        async with self._lock:
            return [a.model_copy() for a in self.analyzers if a.is_healthy]
