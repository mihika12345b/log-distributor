# Log Distribution System - Design & Testing

**Author**: [Your Name]
**Date**: [Date]

---

## System Overview

Built a high-throughput log distribution system that ingests log packets via REST API and distributes them to multiple analyzer services based on configurable weights. The system handles 1000+ packets/second with automatic failover when analyzers go offline.

**Core Architecture**: Async I/O-based web server (FastAPI) with weighted random selection, health monitoring, and queue-based backpressure.

---

## Key Design Decisions

**1. AsyncIO over Multi-threading**
- Log distribution is I/O-bound (99% time spent waiting on HTTP responses), not CPU-bound
- AsyncIO provides better throughput for I/O workloads with lower memory overhead compared to thread pools
- Single event loop handles 10 concurrent workers processing from a shared async queue
- Trade-off: AsyncIO adds complexity but gives us non-blocking I/O without the context-switching overhead of threads

**2. Weighted Random Selection**
- Simpler than round-robin for our use case - no state to track, inherently thread-safe
- Uses cumulative weight distribution with random selection: O(n) per packet where n = number of healthy analyzers
- Lock is held for microseconds (just during selection), not during I/O operations
- Trade-off: Slightly less predictable than strict round-robin, but distribution converges with high packet volumes

**3. Queue-Based Backpressure**
- 5000-packet async queue acts as buffer for traffic bursts
- When queue fills, return 503 (Service Unavailable) to clients instead of dropping packets silently
- Protects system from overload - better to explicitly reject than to accept and fail
- Trade-off: Clients need retry logic, but system stays stable under extreme load

**4. Proactive Health Monitoring**
- Background task checks analyzer health every 5 seconds
- Automatically excludes failed analyzers from weighted selection
- Recalculates weight distribution among healthy analyzers proportionally
- Trade-off: 5-second detection window means some packets may fail before unhealthy analyzer is removed (hence retry logic)

---

## Improvements with More Time

**Performance & Scalability**
- Add connection pooling in httpx client to reuse TCP connections (currently creating new connections per request)
- Implement circuit breaker pattern: temporarily stop sending to flaky analyzers after N consecutive failures, reducing wasted retries
- Add metrics export (Prometheus format) for monitoring in production: latency histograms, error rates by analyzer, queue depth over time
- Horizontal scaling: use Redis queue instead of in-memory asyncio.Queue to allow multiple distributor instances

**Reliability**
- Implement dead letter queue for packets that fail after all retries - currently they're just logged as failed
- Add request tracing with correlation IDs to track packets end-to-end across services
- Graceful shutdown: drain queue before stopping, return 503 for new requests during shutdown
- Persistent queue (Redis/RabbitMQ) to survive distributor restarts without losing buffered packets

**Operational**
- Dynamic reconfiguration: allow adding/removing analyzers and updating weights without restart (watch config file or API endpoint)
- Health check sophistication: instead of binary healthy/unhealthy, track success rate and latency, reduce weight for degraded analyzers
- Rate limiting per analyzer to prevent one slow analyzer from consuming all workers
- Better observability: structured logging with trace IDs, detailed error messages, async task monitoring

---

## Testing Strategy

**Unit Tests**
- Test weighted selection algorithm: verify distribution converges to expected weights over 10,000 samples
- Test async lock behavior: ensure thread-safety under concurrent access (spawn 100 async tasks, verify no race conditions)
- Test exponential backoff logic: mock failing HTTP calls, verify retry delays are 0.5s, 1s, 2s
- Test queue backpressure: fill queue to capacity, verify 503 responses returned correctly

**Integration Tests**
- Spin up distributor + analyzers in Docker, send packets end-to-end, verify correct distribution
- Test failover: stop analyzer mid-test, verify traffic redistributes without packet loss
- Test analyzer recovery: restart failed analyzer, verify it rejoins pool and receives traffic
- Test health monitor: verify unhealthy analyzers excluded within 5 seconds of failure

**Performance Tests**
- Throughput test: 10 concurrent clients, 2000 packets total, target 95%+ success rate
- Sustained load: run at 80% capacity for 5 minutes, verify no memory leaks or performance degradation
- Burst handling: send 5000 packets instantly, verify queue buffer handles burst without excessive failures
- Latency measurement: p50, p95, p99 latencies under various load levels

**Failure Mode Tests**
- All analyzers down: verify system returns 503 immediately
- Network partition: slow analyzer (inject 5s delay), verify timeouts work and retries redistribute
- Malformed responses: analyzer returns 500 errors, verify distributor retries and eventually fails packet
- Queue overflow: exceed queue capacity, verify 503 backpressure and system stability

**Load Testing**
- Used Locust to simulate realistic traffic patterns: ramp up from 10 to 100 concurrent users over 2 minutes
- Identify breaking point: increase load until success rate drops below 95%
- Memory profiling: ensure no memory leaks under sustained high load
- Compare performance: async I/O vs thread pool implementation (async should have lower memory, higher throughput)

---

## Assumptions & Trade-offs

**Assumptions Made**
- Analyzers are relatively reliable (not flapping constantly) - health check interval of 5 seconds is reasonable
- Network latency between distributor and analyzers is low (<100ms) - single datacenter deployment
- Log packets are small (<10KB each) - no chunking or streaming needed
- Acceptable to lose packets that fail after max retries - no strict delivery guarantees required
- Analyzers can handle weighted load - analyzer-1 must have capacity for 40% of total traffic

**Trade-offs Accepted**
- Eventually consistent health state: up to 5 seconds to detect failures, some packets may fail during detection window
- In-memory queue: high performance but lost on crash - acceptable for logging use case where some loss is tolerable
- Weighted random vs round-robin: less predictable distribution for small sample sizes, but simpler implementation
- Fixed retry strategy: exponential backoff with 2 retries works for transient failures, but not optimal for all failure modes

---

## Running the Demo

```bash
# Start system
docker-compose up -d

# Run all demos
python3 tests/demo_weight_distribution.py  # Verify weighted distribution
python3 tests/demo_failover.py             # Test analyzer failure handling
python3 tests/demo_throughput.py           # Performance test (95%+ success rate)

# Check system stats
curl http://localhost:8000/stats | python3 -m json.tool

# Cleanup
docker-compose down -v
```

See `VIDEO_DEMO_SCRIPT.md` for detailed walkthrough.

---

## Tech Stack Justification

- **FastAPI**: Modern async web framework, automatic API docs, Pydantic validation
- **httpx**: Async HTTP client (requests doesn't support async)
- **Pydantic**: Type-safe data validation, automatic serialization
- **Docker Compose**: Simple multi-service orchestration for local dev/demo
- **Python 3.11**: Native async/await support, good performance for I/O-bound workloads

Total implementation: ~500 lines of Python, fully async, production-ready foundation.
