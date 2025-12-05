#!/bin/bash

# Quick test script to validate the system is working
# Run this after starting with docker-compose up -d

set -e

echo "🧪 Quick System Test"
echo "===================="
echo ""

# Test 1: Check distributor is accessible
echo "1. Testing distributor accessibility..."
if curl -s -f http://localhost:8000/health > /dev/null 2>&1; then
    echo "   ✅ Distributor is accessible"
else
    echo "   ❌ Distributor is not accessible"
    echo "   Run: docker-compose up -d"
    exit 1
fi

# Test 2: Check health status
echo ""
echo "2. Checking system health..."
HEALTH=$(curl -s http://localhost:8000/health)
HEALTHY_COUNT=$(echo "$HEALTH" | grep -o '"healthy":[0-9]*' | grep -o '[0-9]*')

if [ "$HEALTHY_COUNT" = "4" ]; then
    echo "   ✅ All 4 analyzers are healthy"
else
    echo "   ⚠️  Only $HEALTHY_COUNT/4 analyzers are healthy"
    echo "   This is OK if you just started the system (health checks take ~10 seconds)"
fi

# Test 3: Send a test packet
echo ""
echo "3. Sending test packet..."
RESPONSE=$(curl -s -X POST http://localhost:8000/ingest \
  -H "Content-Type: application/json" \
  -d '{
    "packet_id": "quick-test-001",
    "agent_id": "quick-test",
    "messages": [{
      "timestamp": "2025-11-30T00:00:00Z",
      "level": "INFO",
      "source": "quick-test",
      "message": "Quick test message",
      "metadata": {}
    }]
  }')

if echo "$RESPONSE" | grep -q "accepted"; then
    echo "   ✅ Packet accepted successfully"
else
    echo "   ❌ Packet was not accepted"
    echo "   Response: $RESPONSE"
    exit 1
fi

# Test 4: Check statistics
echo ""
echo "4. Checking statistics..."
sleep 2  # Wait for processing
STATS=$(curl -s http://localhost:8000/stats)
TOTAL_PACKETS=$(echo "$STATS" | grep -o '"total_packets_received":[0-9]*' | grep -o '[0-9]*')

if [ "$TOTAL_PACKETS" -ge 1 ]; then
    echo "   ✅ Statistics working ($TOTAL_PACKETS packets received)"
else
    echo "   ⚠️  No packets in statistics yet"
fi

# Test 5: Check all analyzer endpoints
echo ""
echo "5. Checking analyzer endpoints..."
ALL_GOOD=true
for port in 8001 8002 8003 8004; do
    if curl -s -f http://localhost:$port/health > /dev/null 2>&1; then
        echo "   ✅ Analyzer on port $port is responding"
    else
        echo "   ❌ Analyzer on port $port is not responding"
        ALL_GOOD=false
    fi
done

# Summary
echo ""
echo "===================="
if [ "$ALL_GOOD" = true ] && [ "$HEALTHY_COUNT" = "4" ] && [ "$TOTAL_PACKETS" -ge 1 ]; then
    echo "✅ ALL TESTS PASSED!"
    echo ""
    echo "System is working correctly. You can now:"
    echo "  - Run demos: ./run_demos.sh"
    echo "  - View logs: docker-compose logs -f"
    echo "  - Check stats: curl http://localhost:8000/stats | jq"
else
    echo "⚠️  SOME TESTS HAD ISSUES"
    echo ""
    echo "If you just started the system, wait 10 seconds and run this script again."
    echo "Otherwise, check:"
    echo "  - docker-compose ps (all containers should be 'Up')"
    echo "  - docker-compose logs (for error messages)"
fi
echo ""
