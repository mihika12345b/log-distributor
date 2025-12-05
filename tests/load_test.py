"""
Load testing script using Locust.

This simulates many agents sending log packets to the distributor
to test high-throughput scenarios.

Locust is a scalable load testing framework that:
- Simulates thousands of concurrent users
- Provides real-time statistics
- Has a web UI for monitoring

Run with:
    locust -f tests/load_test.py --host=http://localhost:8000
"""

from locust import HttpUser, task, between
import random
import uuid
from datetime import datetime


class LogAgent(HttpUser):
    """
    Simulates a log agent that sends packets to the distributor.

    Each Locust user represents one agent that continuously sends
    log packets at a realistic rate.
    """

    # Wait 0.1 to 0.5 seconds between requests (simulates real agent behavior)
    wait_time = between(0.1, 0.5)

    # Sample log sources and levels for realistic data
    LOG_SOURCES = [
        "payment-service",
        "auth-service",
        "user-service",
        "notification-service",
        "api-gateway"
    ]

    LOG_LEVELS = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]

    LOG_MESSAGES = [
        "Request processed successfully",
        "Database connection established",
        "Cache miss, fetching from DB",
        "User authentication successful",
        "Payment processed",
        "API rate limit warning",
        "Temporary service degradation",
        "Connection timeout",
        "Invalid input received"
    ]

    def on_start(self):
        """Called when a user starts - generate a unique agent ID"""
        self.agent_id = f"agent-{uuid.uuid4().hex[:8]}"

    @task
    def send_log_packet(self):
        """
        Send a log packet to the distributor.

        This is the main task that each simulated agent performs.
        The @task decorator means Locust will execute this repeatedly.
        """

        # Generate a realistic log packet with 5-20 messages
        num_messages = random.randint(5, 20)

        messages = []
        for _ in range(num_messages):
            message = {
                "timestamp": datetime.utcnow().isoformat() + "Z",
                "level": random.choice(self.LOG_LEVELS),
                "source": random.choice(self.LOG_SOURCES),
                "message": random.choice(self.LOG_MESSAGES),
                "metadata": {
                    "request_id": uuid.uuid4().hex,
                    "user_id": f"user_{random.randint(1, 10000)}"
                }
            }
            messages.append(message)

        packet = {
            "packet_id": f"packet-{uuid.uuid4().hex}",
            "agent_id": self.agent_id,
            "messages": messages
        }

        # Send the packet
        # Locust automatically tracks response time, success rate, etc.
        with self.client.post(
            "/ingest",
            json=packet,
            catch_response=True
        ) as response:
            if response.status_code == 202:
                # 202 Accepted is success for our async API
                response.success()
            elif response.status_code == 503:
                # Queue full - this is expected under extreme load
                response.failure("Queue full (503)")
            else:
                response.failure(f"Unexpected status: {response.status_code}")

    @task(1)  # Lower weight - check stats less frequently
    def check_stats(self):
        """
        Occasionally check stats (to simulate monitoring).

        The weight (1) means this runs less frequently than send_log_packet.
        """
        self.client.get("/stats")

    @task(1)  # Lower weight
    def check_health(self):
        """Occasionally check health endpoint"""
        self.client.get("/health")


# ===== CLI USAGE =====
"""
To run load tests:

1. Start the system:
   docker-compose up -d

2. Basic load test (Web UI):
   locust -f tests/load_test.py --host=http://localhost:8000
   # Then open http://localhost:8089 and configure users/spawn rate

3. Headless mode (no UI):
   locust -f tests/load_test.py --host=http://localhost:8000 \\
          --users 100 --spawn-rate 10 --run-time 60s --headless

4. High throughput test:
   locust -f tests/load_test.py --host=http://localhost:8000 \\
          --users 500 --spawn-rate 50 --run-time 120s --headless

Expected Results:
- System should handle 1000+ requests/second
- 99th percentile latency should be under 100ms
- No errors under normal load (queue should not fill)
- Under extreme load (1000+ users), may see some 503s (expected backpressure)
"""
