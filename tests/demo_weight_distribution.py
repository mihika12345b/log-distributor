"""
Demo Script 1: Weight Distribution Verification

This script:
1. Sends a large number of log packets to the distributor
2. Retrieves statistics from the distributor
3. Verifies that packets are distributed according to weights

Expected weights:
- analyzer-1: 0.4 (40%)
- analyzer-2: 0.3 (30%)
- analyzer-3: 0.2 (20%)
- analyzer-4: 0.1 (10%)
"""

import requests
import time
import uuid
from datetime import datetime
import json

# Configuration
DISTRIBUTOR_URL = "http://localhost:8000"
NUM_PACKETS = 1000  # Send 1000 packets for good statistical distribution
MESSAGES_PER_PACKET = 10

# Expected weights
EXPECTED_WEIGHTS = {
    "analyzer-1": 0.4,
    "analyzer-2": 0.3,
    "analyzer-3": 0.2,
    "analyzer-4": 0.1
}


def generate_log_packet(packet_num: int) -> dict:
    """Generate a sample log packet"""
    messages = []
    for i in range(MESSAGES_PER_PACKET):
        messages.append({
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "level": "INFO",
            "source": "demo-script",
            "message": f"Demo log message {packet_num}-{i}",
            "metadata": {"packet_num": packet_num, "msg_num": i}
        })

    return {
        "packet_id": f"demo-packet-{packet_num}-{uuid.uuid4().hex[:8]}",
        "agent_id": "demo-agent",
        "messages": messages
    }


def send_packets():
    """Send log packets to the distributor"""
    print(f"\n{'='*60}")
    print("DEMO 1: Weight Distribution Verification")
    print(f"{'='*60}\n")

    print(f"Sending {NUM_PACKETS} packets to the distributor...")
    print(f"Each packet contains {MESSAGES_PER_PACKET} log messages\n")

    successful = 0
    failed = 0
    start_time = time.time()

    for i in range(NUM_PACKETS):
        packet = generate_log_packet(i)

        try:
            response = requests.post(
                f"{DISTRIBUTOR_URL}/ingest",
                json=packet,
                timeout=5
            )

            if response.status_code == 202:
                successful += 1
            else:
                failed += 1
                print(f"Warning: Packet {i} failed with status {response.status_code}")

            # Progress indicator
            if (i + 1) % 100 == 0:
                elapsed = time.time() - start_time
                rate = (i + 1) / elapsed
                print(f"Progress: {i+1}/{NUM_PACKETS} packets sent ({rate:.1f} packets/sec)")

        except requests.RequestException as e:
            failed += 1
            print(f"Error sending packet {i}: {e}")

    elapsed_time = time.time() - start_time
    rate = successful / elapsed_time

    print(f"\n✓ Finished sending packets")
    print(f"  - Successful: {successful}")
    print(f"  - Failed: {failed}")
    print(f"  - Time: {elapsed_time:.2f} seconds")
    print(f"  - Rate: {rate:.1f} packets/sec")

    return successful > 0


def check_distribution():
    """Check the distribution statistics"""
    print(f"\n{'='*60}")
    print("Checking Distribution Statistics")
    print(f"{'='*60}\n")

    # Wait a moment for all packets to be processed
    print("Waiting 5 seconds for processing to complete...")
    time.sleep(5)

    try:
        response = requests.get(f"{DISTRIBUTOR_URL}/stats", timeout=5)
        response.raise_for_status()
        stats = response.json()

        print("\nDistribution Results:")
        print(f"{'='*60}")
        print(f"{'Analyzer':<15} {'Expected':<12} {'Actual':<12} {'Difference':<12} {'Status'}")
        print(f"{'-'*60}")

        total_packets = stats["total_packets_received"]
        all_within_tolerance = True

        for analyzer_name, expected_weight in EXPECTED_WEIGHTS.items():
            actual_packets = stats["packets_per_analyzer"].get(analyzer_name, 0)
            actual_weight = actual_packets / total_packets if total_packets > 0 else 0
            difference = abs(actual_weight - expected_weight)

            # Allow 5% tolerance (e.g., 0.4 ± 0.05 is acceptable)
            # This accounts for randomness in weighted selection
            tolerance = 0.05
            within_tolerance = difference <= tolerance

            status = "✓ PASS" if within_tolerance else "✗ FAIL"

            print(f"{analyzer_name:<15} {expected_weight*100:>5.1f}% "
                  f"      {actual_weight*100:>5.1f}%       "
                  f"{difference*100:>5.1f}%       {status}")

            if not within_tolerance:
                all_within_tolerance = False

        print(f"{'-'*60}")
        print(f"Total packets:  {total_packets}")
        print(f"Total messages: {stats['total_messages_received']}")
        print(f"Failed sends:   {stats['failed_sends']}")

        print(f"\n{'='*60}")
        if all_within_tolerance:
            print("✓ SUCCESS: All analyzers received packets within expected weights!")
        else:
            print("✗ WARNING: Some analyzers outside tolerance (may be due to randomness)")
        print(f"{'='*60}\n")

        return all_within_tolerance

    except requests.RequestException as e:
        print(f"Error retrieving stats: {e}")
        return False


def main():
    """Main demo function"""
    print("\n" + "="*60)
    print("  Log Distributor - Weight Distribution Demo")
    print("="*60)

    # Check if distributor is running
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

    print("\n✓ Distributor is running and healthy\n")

    # Send packets
    if not send_packets():
        print("\n✗ Failed to send packets")
        return

    # Check distribution
    check_distribution()


if __name__ == "__main__":
    main()
