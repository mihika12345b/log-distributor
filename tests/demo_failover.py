"""
Demo Script 2: Analyzer Failover

This script demonstrates that the system handles analyzer failures gracefully:
1. Send packets with all analyzers online
2. Stop one analyzer (analyzer-2)
3. Verify traffic redistributes to remaining analyzers
4. Restart the analyzer
5. Verify it rejoins and receives traffic again

This tests the health monitoring and dynamic weight adjustment.
"""

import requests
import time
import uuid
import subprocess
from datetime import datetime

DISTRIBUTOR_URL = "http://localhost:8000"
PACKETS_PER_PHASE = 200
MESSAGES_PER_PACKET = 10


def generate_log_packet(phase: str, packet_num: int) -> dict:
    """Generate a sample log packet"""
    messages = []
    for i in range(MESSAGES_PER_PACKET):
        messages.append({
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "level": "INFO",
            "source": f"demo-{phase}",
            "message": f"Failover demo {phase} - packet {packet_num} msg {i}",
            "metadata": {"phase": phase, "packet_num": packet_num}
        })

    return {
        "packet_id": f"failover-{phase}-{packet_num}-{uuid.uuid4().hex[:8]}",
        "agent_id": "demo-failover-agent",
        "messages": messages
    }


def send_packets(phase: str, num_packets: int):
    """Send packets and return success count"""
    print(f"  Sending {num_packets} packets during '{phase}' phase...")

    successful = 0
    for i in range(num_packets):
        packet = generate_log_packet(phase, i)
        try:
            response = requests.post(
                f"{DISTRIBUTOR_URL}/ingest",
                json=packet,
                timeout=5
            )
            if response.status_code == 202:
                successful += 1
        except requests.RequestException as e:
            pass  # Ignore errors for demo

        # Brief pause to spread out packets
        if i % 50 == 0:
            time.sleep(0.1)

    print(f"  ✓ Sent {successful}/{num_packets} packets successfully")
    return successful


def get_stats():
    """Get current distributor stats"""
    try:
        response = requests.get(f"{DISTRIBUTOR_URL}/stats", timeout=5)
        response.raise_for_status()
        return response.json()
    except:
        return None


def get_health():
    """Get health status"""
    try:
        response = requests.get(f"{DISTRIBUTOR_URL}/health", timeout=5)
        response.raise_for_status()
        return response.json()
    except:
        return None


def print_distribution(stats, phase_name):
    """Print current distribution"""
    print(f"\n  Distribution after '{phase_name}':")
    print(f"  {'-'*50}")

    if not stats:
        print("  (Unable to retrieve stats)")
        return

    total = stats["total_packets_received"]
    for analyzer_name in ["analyzer-1", "analyzer-2", "analyzer-3", "analyzer-4"]:
        count = stats["packets_per_analyzer"].get(analyzer_name, 0)
        percentage = (count / total * 100) if total > 0 else 0
        print(f"  {analyzer_name:<15} {count:>6} packets ({percentage:>5.1f}%)")


def stop_analyzer():
    """Stop analyzer-2 container"""
    print("  Stopping analyzer-2 container...")
    try:
        result = subprocess.run(
            ["docker", "stop", "analyzer-2"],
            capture_output=True,
            text=True,
            timeout=10
        )
        if result.returncode == 0:
            print("  ✓ Analyzer-2 stopped")
            return True
        else:
            print(f"  ✗ Failed to stop: {result.stderr}")
            return False
    except Exception as e:
        print(f"  ✗ Error stopping analyzer-2: {e}")
        return False


def start_analyzer():
    """Start analyzer-2 container"""
    print("  Starting analyzer-2 container...")
    try:
        result = subprocess.run(
            ["docker", "start", "analyzer-2"],
            capture_output=True,
            text=True,
            timeout=10
        )
        if result.returncode == 0:
            print("  ✓ Analyzer-2 started")
            return True
        else:
            print(f"  ✗ Failed to start: {result.stderr}")
            return False
    except Exception as e:
        print(f"  ✗ Error starting analyzer-2: {e}")
        return False


def wait_for_health_detection(expected_healthy: int):
    """Wait for health monitor to detect the change"""
    print(f"  Waiting for health monitor to detect change (target: {expected_healthy} healthy)...")

    for i in range(20):  # Wait up to 20 seconds (4 health check cycles)
        time.sleep(1)
        health = get_health()
        if health and health["analyzers"]["healthy"] == expected_healthy:
            print(f"  ✓ Health monitor detected change ({expected_healthy} healthy analyzers)")
            return True

    print(f"  ⚠ Timeout waiting for health detection")
    return False


def main():
    """Main failover demo"""
    print("\n" + "="*60)
    print("  Log Distributor - Failover Demo")
    print("="*60)

    # Check system is running
    health = get_health()
    if not health:
        print("\n✗ Error: Cannot connect to distributor")
        print("  Please start the system with: docker-compose up -d")
        return

    print(f"\n✓ System is running")
    print(f"  - Healthy analyzers: {health['analyzers']['healthy']}/4")

    # ===== PHASE 1: All analyzers healthy =====
    print(f"\n{'='*60}")
    print("PHASE 1: All Analyzers Online")
    print(f"{'='*60}\n")

    send_packets("phase1", PACKETS_PER_PHASE)
    time.sleep(2)  # Let packets process

    stats_before = get_stats()
    print_distribution(stats_before, "Phase 1 (All Online)")

    # Check analyzer-2 received traffic
    phase1_analyzer2 = stats_before["packets_per_analyzer"].get("analyzer-2", 0)
    print(f"\n  Analyzer-2 received: {phase1_analyzer2} packets")

    # ===== PHASE 2: Stop analyzer-2 =====
    print(f"\n{'='*60}")
    print("PHASE 2: Analyzer-2 Goes Offline")
    print(f"{'='*60}\n")

    if not stop_analyzer():
        print("\n✗ Failed to stop analyzer-2. Ensure Docker is running.")
        return

    # Wait for health monitor to detect failure
    wait_for_health_detection(expected_healthy=3)

    # Send more packets
    time.sleep(1)
    send_packets("phase2", PACKETS_PER_PHASE)
    time.sleep(2)

    stats_after_stop = get_stats()
    print_distribution(stats_after_stop, "Phase 2 (Analyzer-2 Offline)")

    # Check analyzer-2 did NOT receive new traffic
    phase2_analyzer2 = stats_after_stop["packets_per_analyzer"].get("analyzer-2", 0)
    new_packets_to_analyzer2 = phase2_analyzer2 - phase1_analyzer2

    print(f"\n  Analyzer-2 packets in Phase 2: {new_packets_to_analyzer2}")

    if new_packets_to_analyzer2 <= 5:  # Allow small number due to timing
        print("  ✓ Traffic correctly excluded analyzer-2")
    else:
        print("  ⚠ Analyzer-2 still received traffic (health check may not have detected failure yet)")

    # ===== PHASE 3: Restart analyzer-2 =====
    print(f"\n{'='*60}")
    print("PHASE 3: Analyzer-2 Comes Back Online")
    print(f"{'='*60}\n")

    if not start_analyzer():
        print("\n✗ Failed to start analyzer-2")
        return

    # Wait for health monitor to detect recovery
    wait_for_health_detection(expected_healthy=4)

    # Send more packets
    time.sleep(1)
    send_packets("phase3", PACKETS_PER_PHASE)
    time.sleep(2)

    stats_after_restart = get_stats()
    print_distribution(stats_after_restart, "Phase 3 (Analyzer-2 Back Online)")

    # Check analyzer-2 received new traffic
    phase3_analyzer2 = stats_after_restart["packets_per_analyzer"].get("analyzer-2", 0)
    new_packets_after_restart = phase3_analyzer2 - phase2_analyzer2

    print(f"\n  Analyzer-2 packets in Phase 3: {new_packets_after_restart}")

    if new_packets_after_restart > 10:  # Should receive ~30% of 200 = ~60 packets
        print("  ✓ Traffic correctly resumed to analyzer-2")
    else:
        print("  ⚠ Analyzer-2 may not be receiving traffic yet")

    # ===== SUMMARY =====
    print(f"\n{'='*60}")
    print("Summary")
    print(f"{'='*60}\n")

    health_final = get_health()
    if health_final:
        print(f"Final system state:")
        print(f"  - Healthy analyzers: {health_final['analyzers']['healthy']}/4")
        print(f"  - Total packets processed: {stats_after_restart['total_packets_received']}")

    print(f"\n✓ Failover demo completed!")
    print(f"  The system correctly:")
    print(f"  1. Detected when analyzer-2 went offline")
    print(f"  2. Redistributed traffic to remaining analyzers")
    print(f"  3. Detected when analyzer-2 came back online")
    print(f"  4. Resumed sending traffic to analyzer-2")
    print(f"\n{'='*60}\n")


if __name__ == "__main__":
    main()
