"""
Data models for the logs distributor system.

This module defines the core data structures:
- LogMessage: A single log entry with metadata
- LogPacket: A batch of log messages sent together (more efficient than sending one at a time)
- Analyzer: Configuration for a log analyzer service
"""

from pydantic import BaseModel, Field
from typing import List, Optional
from datetime import datetime
from enum import Enum


class LogLevel(str, Enum):
    """
    Standard log levels following common logging conventions.
    Using an Enum ensures type safety and prevents invalid values.
    """
    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


class LogMessage(BaseModel):
    """
    Represents a single log message.

    Design decisions:
    - timestamp: When the log was generated (important for time-series analysis)
    - level: Severity of the log (analyzers might filter by this)
    - source: Which service/app generated this log (helps with routing/filtering)
    - message: The actual log content
    - metadata: Flexible dict for additional context (tags, user_id, trace_id, etc.)
    """
    timestamp: datetime = Field(default_factory=datetime.utcnow, description="When the log was generated")
    level: LogLevel = Field(default=LogLevel.INFO, description="Log severity level")
    source: str = Field(..., description="Origin service/application name", min_length=1)
    message: str = Field(..., description="The actual log message", min_length=1)
    metadata: Optional[dict] = Field(default_factory=dict, description="Additional context (tags, trace_ids, etc.)")

    class Config:
        """Pydantic config to show example in API docs"""
        json_schema_extra = {
            "example": {
                "timestamp": "2025-11-24T10:30:00Z",
                "level": "ERROR",
                "source": "payment-service",
                "message": "Failed to process payment for order #12345",
                "metadata": {
                    "order_id": "12345",
                    "user_id": "user_789",
                    "trace_id": "abc-def-ghi"
                }
            }
        }


class LogPacket(BaseModel):
    """
    Represents a batch of log messages sent together.

    Why batching?
    - Reduces network overhead (fewer HTTP requests)
    - Better throughput (process multiple logs at once)
    - Common pattern in log aggregation systems (Fluentd, Logstash do this)

    Fields:
    - packet_id: Unique identifier for this batch (helps with deduplication/tracking)
    - messages: The batch of log messages
    - agent_id: Which agent collected these logs (useful for debugging/monitoring)
    """
    packet_id: str = Field(..., description="Unique identifier for this packet", min_length=1)
    messages: List[LogMessage] = Field(..., description="Batch of log messages", min_items=1)
    agent_id: str = Field(..., description="ID of the agent that sent this packet", min_length=1)

    class Config:
        """Pydantic config to show example in API docs"""
        json_schema_extra = {
            "example": {
                "packet_id": "packet-001-20251124-103000",
                "agent_id": "agent-us-west-1",
                "messages": [
                    {
                        "timestamp": "2025-11-24T10:30:00Z",
                        "level": "ERROR",
                        "source": "payment-service",
                        "message": "Payment timeout",
                        "metadata": {"order_id": "12345"}
                    },
                    {
                        "timestamp": "2025-11-24T10:30:01Z",
                        "level": "INFO",
                        "source": "auth-service",
                        "message": "User logged in",
                        "metadata": {"user_id": "user_789"}
                    }
                ]
            }
        }


class Analyzer(BaseModel):
    """
    Configuration for an analyzer service.

    Fields:
    - name: Human-readable identifier
    - url: Endpoint where the analyzer receives logs
    - weight: Relative weight for distribution (e.g., 0.4 = 40% of traffic)
    - is_healthy: Current health status (dynamically updated by health monitor)

    Design note: We track health status here so the distributor can quickly
    exclude unhealthy analyzers without blocking on failed requests.
    """
    name: str = Field(..., description="Analyzer identifier")
    url: str = Field(..., description="Analyzer endpoint URL")
    weight: float = Field(..., description="Relative weight (0.0 to 1.0)", ge=0.0, le=1.0)
    is_healthy: bool = Field(default=True, description="Current health status")

    class Config:
        """Pydantic config to show example in API docs"""
        json_schema_extra = {
            "example": {
                "name": "analyzer-1",
                "url": "http://analyzer-1:8001/analyze",
                "weight": 0.4,
                "is_healthy": True
            }
        }


class DistributorStats(BaseModel):
    """
    Statistics for monitoring the distributor's behavior.
    Used in the demo to verify weight distribution is correct.
    """
    total_packets_received: int = Field(default=0, description="Total packets received by distributor")
    total_messages_received: int = Field(default=0, description="Total individual log messages received")
    packets_per_analyzer: dict[str, int] = Field(default_factory=dict, description="Packets sent to each analyzer")
    messages_per_analyzer: dict[str, int] = Field(default_factory=dict, description="Messages sent to each analyzer")
    failed_sends: int = Field(default=0, description="Number of failed sends to analyzers")
