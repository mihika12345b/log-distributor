"""
Demo Script 3: High Throughput Test

This script demonstrates the system can handle high throughput by:
1. Sending many packets concurrently
2. Measuring throughput (packets/sec, messages/sec)
3. Measuring latency (response times)
4. Checking for errors under load

This uses concurrent requests to maximize throughput.

Usage:
    python3 tests/demo_throughput.py                    # Default: 2000 packets, 10 workers
    python3 tests/demo_throughput.py 5000               # 5000 packets, 10 workers
    python3 tests/demo_throughput.py 10000 20           # 10000 packets, 20 workers
    python3 tests/demo_throughput.py --packets 5000 --workers 15 --messages 20
"""

import requests
import time
import uuid
import argparse
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed
import statistics

DISTRIBUTOR_URL = "http://localhost:8000"

# Default values (can be overridden by command-line arguments)
DEFAULT_NUM_PACKETS = 2000
DEFAULT_CONCURRENT_WORKERS = 10
DEFAULT_MESSAGES_PER_PACKET = 15


def generate_log_packet(packet_num: int, messages_per_packet: int) -> dict:
    """Generate a sample log packet"""
    messages = []
    for i in range(messages_per_packet):
        messages.append({
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": "INFO",
            "source": "throughput-test",
            "message": f"High throughput test packet {packet_num} message {i}",
            "metadata": {"packet_num": packet_num, "msg_num": i}
        })

    return {
        "packet_id": f"throughput-{packet_num}-{uuid.uuid4().hex[:8]}",
        "agent_id": f"throughput-agent-{packet_num % 10}",  # Simulate 10 agents
        "messages": messages
    }


def send_packet(packet_num: int, messages_per_packet: int):
    """Send a single packet and return result"""
    packet = generate_log_packet(packet_num, messages_per_packet)

    start_time = time.time()
    try:
        response = requests.post(
            f"{DISTRIBUTOR_URL}/ingest",
            json=packet,
            timeout=10
        )

        latency = time.time() - start_time

        return {
            "success": response.status_code == 202,
            "status_code": response.status_code,
            "latency": latency,
            "packet_num": packet_num
        }

    except requests.RequestException as e:
        latency = time.time() - start_time
        return {
            "success": False,
            "status_code": None,
            "latency": latency,
            "packet_num": packet_num,
            "error": str(e)
        }


def run_throughput_test(num_packets, concurrent_workers, messages_per_packet):
    """Run the throughput test with concurrent workers"""
    print(f"\n{'='*60}")
    print("High Throughput Test")
    print(f"{'='*60}\n")

    print(f"Configuration:")
    print(f"  - Total packets: {num_packets:,}")
    print(f"  - Messages per packet: {messages_per_packet}")
    print(f"  - Total messages: {num_packets * messages_per_packet:,}")
    print(f"  - Concurrent workers: {concurrent_workers}")
    print(f"\nNote: This test pushes the system hard. Some 503 errors are expected")
    print(f"if queue fills up (this is correct backpressure behavior).\n")
    print(f"Starting test...\n")

    results = []
    successful = 0
    failed = 0

    start_time = time.time()

    # Use ThreadPoolExecutor for concurrent requests
    with ThreadPoolExecutor(max_workers=concurrent_workers) as executor:
        # Submit all tasks
        futures = {
            executor.submit(send_packet, i, messages_per_packet): i
            for i in range(num_packets)
        }

        # Process results as they complete
        completed = 0
        progress_interval = max(100, num_packets // 20)  # Show progress ~20 times

        for future in as_completed(futures):
            result = future.result()
            results.append(result)

            if result["success"]:
                successful += 1
            else:
                failed += 1

            completed += 1

            # Progress indicator
            if completed % progress_interval == 0 or completed == num_packets:
                elapsed = time.time() - start_time
                rate = completed / elapsed if elapsed > 0 else 0
                print(f"Progress: {completed:,}/{num_packets:,} "
                      f"({rate:.0f} packets/sec, "
                      f"{successful:,} success, {failed:,} failed)")

    total_time = time.time() - start_time

    return results, successful, failed, total_time


def analyze_results(results, successful, failed, total_time, messages_per_packet):
    """Analyze and display test results"""
    print(f"\n{'='*60}")
    print("Results")
    print(f"{'='*60}\n")

    # Basic stats
    total_packets = successful + failed
    total_messages = total_packets * messages_per_packet
    packet_rate = total_packets / total_time
    message_rate = total_messages / total_time
    success_rate = (successful / total_packets * 100) if total_packets > 0 else 0

    print(f"Throughput:")
    print(f"  - Packets/sec:  {packet_rate:>10.1f}")
    print(f"  - Messages/sec: {message_rate:>10,.1f}")
    print(f"  - Total time:   {total_time:>10.2f} seconds")

    print(f"\nSuccess Rate:")
    print(f"  - Successful:   {successful:>10,} ({success_rate:.1f}%)")
    print(f"  - Failed:       {failed:>10,}")

    # Latency analysis
    successful_results = [r for r in results if r["success"]]
    if successful_results:
        latencies = [r["latency"] for r in successful_results]

        # Convert to milliseconds for readability
        latencies_ms = [l * 1000 for l in latencies]

        print(f"\nLatency (milliseconds):")
        print(f"  - Min:          {min(latencies_ms):>10.2f} ms")
        print(f"  - Max:          {max(latencies_ms):>10.2f} ms")
        print(f"  - Mean:         {statistics.mean(latencies_ms):>10.2f} ms")
        print(f"  - Median:       {statistics.median(latencies_ms):>10.2f} ms")

        # Calculate percentiles
        sorted_latencies = sorted(latencies_ms)
        p50 = sorted_latencies[len(sorted_latencies) * 50 // 100]
        p95 = sorted_latencies[len(sorted_latencies) * 95 // 100]
        p99 = sorted_latencies[len(sorted_latencies) * 99 // 100]

        print(f"  - P50:          {p50:>10.2f} ms")
        print(f"  - P95:          {p95:>10.2f} ms")
        print(f"  - P99:          {p99:>10.2f} ms")

    # Error analysis
    if failed > 0:
        print(f"\nErrors:")
        error_types = {}
        for r in results:
            if not r["success"]:
                status = r.get("status_code", "Network Error")
                error_types[status] = error_types.get(status, 0) + 1

        for error_type, count in error_types.items():
            print(f"  - {error_type}: {count}")

    # Get final stats from distributor
    print(f"\n{'='*60}")
    print("Distributor Statistics")
    print(f"{'='*60}\n")

    time.sleep(2)  # Wait for processing

    try:
        response = requests.get(f"{DISTRIBUTOR_URL}/stats", timeout=5)
        stats = response.json()

        print(f"Total packets received:  {stats['total_packets_received']}")
        print(f"Total messages received: {stats['total_messages_received']}")
        print(f"Failed sends:            {stats['failed_sends']}")

        print(f"\nPer-analyzer distribution:")
        for analyzer_name in ["analyzer-1", "analyzer-2", "analyzer-3", "analyzer-4"]:
            count = stats["packets_per_analyzer"].get(analyzer_name, 0)
            print(f"  {analyzer_name}: {count:>6} packets")

    except:
        print("(Could not retrieve distributor stats)")


def parse_args():
    """Parse command-line arguments"""
    parser = argparse.ArgumentParser(
        description="High throughput test for log distributor",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s                           # Default: 2000 packets, 10 workers, 15 messages/packet
  %(prog)s 5000                      # 5000 packets, default workers and messages
  %(prog)s 10000 20                  # 10000 packets, 20 workers, default messages
  %(prog)s --packets 5000            # Named argument for packets
  %(prog)s -p 10000 -w 20 -m 20      # Full configuration with short options
  %(prog)s --extreme                 # Extreme test: 20000 packets, 25 workers, 20 messages
        """
    )

    # Positional arguments (for convenience)
    parser.add_argument(
        "num_packets",
        type=int,
        nargs="?",
        default=DEFAULT_NUM_PACKETS,
        help=f"Number of packets to send (default: {DEFAULT_NUM_PACKETS})"
    )
    parser.add_argument(
        "concurrent_workers",
        type=int,
        nargs="?",
        default=DEFAULT_CONCURRENT_WORKERS,
        help=f"Number of concurrent workers (default: {DEFAULT_CONCURRENT_WORKERS})"
    )

    # Named arguments (override positional if provided)
    parser.add_argument(
        "-p", "--packets",
        type=int,
        dest="packets_override",
        help="Number of packets to send (overrides positional argument)"
    )
    parser.add_argument(
        "-w", "--workers",
        type=int,
        dest="workers_override",
        help="Number of concurrent workers (overrides positional argument)"
    )
    parser.add_argument(
        "-m", "--messages",
        type=int,
        default=DEFAULT_MESSAGES_PER_PACKET,
        help=f"Messages per packet (default: {DEFAULT_MESSAGES_PER_PACKET})"
    )

    # Preset configurations
    parser.add_argument(
        "--light",
        action="store_true",
        help="Light test: 1000 packets, 5 workers, 10 messages"
    )
    parser.add_argument(
        "--medium",
        action="store_true",
        help="Medium test: 5000 packets, 15 workers, 15 messages"
    )
    parser.add_argument(
        "--heavy",
        action="store_true",
        help="Heavy test: 10000 packets, 20 workers, 20 messages"
    )
    parser.add_argument(
        "--extreme",
        action="store_true",
        help="Extreme test: 20000 packets, 25 workers, 20 messages"
    )

    args = parser.parse_args()

    # Handle presets
    if args.light:
        return 1000, 5, 10
    elif args.medium:
        return 5000, 15, 15
    elif args.heavy:
        return 10000, 20, 20
    elif args.extreme:
        return 20000, 25, 20

    # Use named arguments if provided, otherwise use positional
    num_packets = args.packets_override if args.packets_override else args.num_packets
    concurrent_workers = args.workers_override if args.workers_override else args.concurrent_workers
    messages_per_packet = args.messages

    return num_packets, concurrent_workers, messages_per_packet


def main():
    """Main throughput demo"""
    # Parse arguments
    num_packets, concurrent_workers, messages_per_packet = parse_args()

    print("\n" + "="*60)
    print("  Log Distributor - High Throughput Demo")
    print("="*60)

    # Check system is running
    try:
        response = requests.get(f"{DISTRIBUTOR_URL}/health", timeout=5)
        if response.status_code != 200:
            print("\n✗ Error: Distributor is not healthy")
            print("  Please start the system with: docker-compose up -d")
            return
    except requests.RequestException:
        print("\n✗ Error: Cannot connect to distributor")
        print("  Please start the system with: docker-compose up -d")
        return

    print("\n✓ Distributor is running and healthy")

    # Run test
    results, successful, failed, total_time = run_throughput_test(
        num_packets, concurrent_workers, messages_per_packet
    )

    # Analyze results
    analyze_results(results, successful, failed, total_time, messages_per_packet)

    # Success criteria
    print(f"\n{'='*60}")
    packet_rate = (successful + failed) / total_time
    success_rate = successful / (successful + failed) * 100 if (successful + failed) > 0 else 0

    if packet_rate >= 500 and success_rate >= 95:
        print("✓ SUCCESS: System demonstrated high throughput!")
        print(f"  - Achieved {packet_rate:,.0f} packets/sec")
        print(f"  - {success_rate:.1f}% success rate")
    else:
        print("⚠ Performance below target")
        if packet_rate < 500:
            print(f"  - Throughput: {packet_rate:,.0f} packets/sec (target: 500+)")
        if success_rate < 95:
            print(f"  - Success rate: {success_rate:.1f}% (target: 95%+)")

    print(f"{'='*60}\n")


if __name__ == "__main__":
    main()
