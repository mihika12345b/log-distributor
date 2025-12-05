#!/bin/bash

# Demo runner script for Log Distributor
# This script runs all three demos sequentially

set -e  # Exit on error

echo "======================================"
echo "  Log Distributor - Demo Suite"
echo "======================================"
echo ""

# Check if system is running
echo "Checking if distributor is running..."
if ! curl -s http://localhost:8000/health > /dev/null 2>&1; then
    echo "❌ Error: Distributor is not running"
    echo "Please start the system with: docker-compose up -d"
    exit 1
fi

echo "✅ Distributor is running"
echo ""

# Check Python dependencies
echo "Checking Python dependencies..."
if ! python3 -c "import requests" 2>/dev/null; then
    echo "Installing requirements..."
    pip install -r requirements.txt
fi

echo ""
echo "======================================"
echo "  Demo 1: Weight Distribution"
echo "======================================"
echo ""
python3 tests/demo_weight_distribution.py

echo ""
read -p "Press Enter to continue to Demo 2 (Failover)..."
echo ""

echo "======================================"
echo "  Demo 2: Failover Handling"
echo "======================================"
echo ""
python3 tests/demo_failover.py

echo ""
read -p "Press Enter to continue to Demo 3 (Throughput)..."
echo ""

echo "======================================"
echo "  Demo 3: High Throughput"
echo "======================================"
echo ""
python3 tests/demo_throughput.py

echo ""
echo "======================================"
echo "  All Demos Complete!"
echo "======================================"
echo ""
echo "You can also run individual demos:"
echo "  - python3 tests/demo_weight_distribution.py"
echo "  - python3 tests/demo_failover.py"
echo "  - python3 tests/demo_throughput.py"
echo ""
echo "Or run load tests with Locust:"
echo "  - locust -f tests/load_test.py --host=http://localhost:8000"
echo ""
