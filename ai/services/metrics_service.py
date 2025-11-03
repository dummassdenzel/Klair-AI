"""
Metrics Service

Collects and aggregates system metrics for observability and monitoring.
Tracks query performance, retrieval statistics, error rates, and more.
"""

import logging
from typing import Dict, List, Optional
from datetime import datetime, timedelta
from collections import defaultdict, deque
from dataclasses import dataclass, asdict
import json

logger = logging.getLogger(__name__)


@dataclass
class QueryMetric:
    """Individual query metric record"""
    timestamp: datetime
    query_type: str  # greeting, general, document
    response_time_ms: float
    sources_count: int
    retrieval_count: int
    rerank_count: int
    session_id: Optional[int] = None
    query_preview: Optional[str] = None
    error: bool = False
    error_message: Optional[str] = None


@dataclass
class RetrievalMetric:
    """Retrieval operation metric"""
    timestamp: datetime
    semantic_results: int
    keyword_results: int
    fused_results: int
    rerank_count: Optional[int] = None


class MetricsService:
    """Service for collecting and aggregating system metrics"""
    
    def __init__(self, max_history: int = 1000):
        """
        Initialize metrics service
        
        Args:
            max_history: Maximum number of metrics to keep in memory
        """
        self.max_history = max_history
        
        # In-memory storage (in production, consider using a time-series DB)
        self.query_metrics: deque = deque(maxlen=max_history)
        self.retrieval_metrics: deque = deque(maxlen=max_history)
        self.error_metrics: deque = deque(maxlen=max_history)
        
        # Aggregated counters
        self.counters = defaultdict(int)
        
        logger.info(f"MetricsService initialized (max_history={max_history})")
    
    def record_query(
        self,
        query_type: str,
        response_time_ms: float,
        sources_count: int,
        retrieval_count: int = 0,
        rerank_count: int = 0,
        session_id: Optional[int] = None,
        query_preview: Optional[str] = None,
        error: bool = False,
        error_message: Optional[str] = None
    ):
        """Record a query metric"""
        metric = QueryMetric(
            timestamp=datetime.utcnow(),
            query_type=query_type,
            response_time_ms=response_time_ms,
            sources_count=sources_count,
            retrieval_count=retrieval_count,
            rerank_count=rerank_count,
            session_id=session_id,
            query_preview=query_preview,
            error=error,
            error_message=error_message
        )
        
        self.query_metrics.append(metric)
        self.counters[f"queries_{query_type}"] += 1
        self.counters["total_queries"] += 1
        
        if error:
            self.error_metrics.append(metric)
            self.counters["total_errors"] += 1
        
        logger.debug(f"Recorded query metric: {query_type}, {response_time_ms:.2f}ms")
    
    def record_retrieval(
        self,
        semantic_results: int,
        keyword_results: int,
        fused_results: int,
        rerank_count: Optional[int] = None
    ):
        """Record a retrieval operation metric"""
        metric = RetrievalMetric(
            timestamp=datetime.utcnow(),
            semantic_results=semantic_results,
            keyword_results=keyword_results,
            fused_results=fused_results,
            rerank_count=rerank_count
        )
        
        self.retrieval_metrics.append(metric)
        self.counters["total_retrievals"] += 1
        
        logger.debug(f"Recorded retrieval metric: {fused_results} fused results")
    
    def get_metrics_summary(self, time_window_minutes: int = 60) -> Dict:
        """
        Get aggregated metrics summary for a time window
        
        Args:
            time_window_minutes: Time window to aggregate (default: last hour)
            
        Returns:
            Dictionary with aggregated metrics
        """
        cutoff_time = datetime.utcnow() - timedelta(minutes=time_window_minutes)
        
        # Filter recent metrics
        recent_queries = [
            m for m in self.query_metrics
            if m.timestamp >= cutoff_time
        ]
        
        if not recent_queries:
            return {
                "time_window_minutes": time_window_minutes,
                "total_queries": 0,
                "query_types": {},
                "average_response_time_ms": 0,
                "error_rate": 0,
                "average_sources_count": 0,
                "average_retrieval_count": 0,
                "average_rerank_count": 0
            }
        
        # Aggregate statistics
        query_types = defaultdict(int)
        response_times = []
        sources_counts = []
        retrieval_counts = []
        rerank_counts = []
        errors = 0
        
        for metric in recent_queries:
            query_types[metric.query_type] += 1
            response_times.append(metric.response_time_ms)
            sources_counts.append(metric.sources_count)
            if metric.retrieval_count > 0:
                retrieval_counts.append(metric.retrieval_count)
            if metric.rerank_count > 0:
                rerank_counts.append(metric.rerank_count)
            if metric.error:
                errors += 1
        
        total_queries = len(recent_queries)
        
        return {
            "time_window_minutes": time_window_minutes,
            "total_queries": total_queries,
            "query_types": dict(query_types),
            "average_response_time_ms": (
                sum(response_times) / len(response_times) if response_times else 0
            ),
            "median_response_time_ms": (
                sorted(response_times)[len(response_times) // 2] if response_times else 0
            ),
            "min_response_time_ms": min(response_times) if response_times else 0,
            "max_response_time_ms": max(response_times) if response_times else 0,
            "error_rate": (errors / total_queries * 100) if total_queries > 0 else 0,
            "error_count": errors,
            "average_sources_count": (
                sum(sources_counts) / len(sources_counts) if sources_counts else 0
            ),
            "average_retrieval_count": (
                sum(retrieval_counts) / len(retrieval_counts) if retrieval_counts else 0
            ),
            "average_rerank_count": (
                sum(rerank_counts) / len(rerank_counts) if rerank_counts else 0
            ),
        }
    
    def get_retrieval_stats(self, time_window_minutes: int = 60) -> Dict:
        """Get retrieval statistics"""
        cutoff_time = datetime.utcnow() - timedelta(minutes=time_window_minutes)
        
        recent_retrievals = [
            m for m in self.retrieval_metrics
            if m.timestamp >= cutoff_time
        ]
        
        if not recent_retrievals:
            return {
                "time_window_minutes": time_window_minutes,
                "total_retrievals": 0,
                "average_semantic_results": 0,
                "average_keyword_results": 0,
                "average_fused_results": 0,
                "average_rerank_count": 0
            }
        
        return {
            "time_window_minutes": time_window_minutes,
            "total_retrievals": len(recent_retrievals),
            "average_semantic_results": (
                sum(m.semantic_results for m in recent_retrievals) / len(recent_retrievals)
            ),
            "average_keyword_results": (
                sum(m.keyword_results for m in recent_retrievals) / len(recent_retrievals)
            ),
            "average_fused_results": (
                sum(m.fused_results for m in recent_retrievals) / len(recent_retrievals)
            ),
            "average_rerank_count": (
                sum(m.rerank_count for m in recent_retrievals if m.rerank_count) 
                / len([m for m in recent_retrievals if m.rerank_count])
                if any(m.rerank_count for m in recent_retrievals) else 0
            ),
        }
    
    def get_time_series(
        self,
        metric_type: str = "response_time",
        time_window_minutes: int = 60,
        bucket_minutes: int = 5
    ) -> List[Dict]:
        """
        Get time series data for a metric
        
        Args:
            metric_type: 'response_time', 'query_count', 'error_count', 'sources_count'
            time_window_minutes: Total time window
            bucket_minutes: Time bucket size for aggregation
            
        Returns:
            List of {timestamp, value} dictionaries
        """
        cutoff_time = datetime.utcnow() - timedelta(minutes=time_window_minutes)
        
        recent_queries = [
            m for m in self.query_metrics
            if m.timestamp >= cutoff_time
        ]
        
        # Group by time buckets
        buckets = defaultdict(list)
        for metric in recent_queries:
            # Round timestamp to bucket
            bucket_start = metric.timestamp.replace(
                minute=(metric.timestamp.minute // bucket_minutes) * bucket_minutes,
                second=0,
                microsecond=0
            )
            buckets[bucket_start].append(metric)
        
        # Aggregate by bucket
        time_series = []
        for bucket_time in sorted(buckets.keys()):
            bucket_metrics = buckets[bucket_time]
            
            if metric_type == "response_time":
                value = sum(m.response_time_ms for m in bucket_metrics) / len(bucket_metrics)
            elif metric_type == "query_count":
                value = len(bucket_metrics)
            elif metric_type == "error_count":
                value = sum(1 for m in bucket_metrics if m.error)
            elif metric_type == "sources_count":
                value = sum(m.sources_count for m in bucket_metrics) / len(bucket_metrics)
            else:
                value = 0
            
            time_series.append({
                "timestamp": bucket_time.isoformat(),
                "value": round(value, 2)
            })
        
        return time_series
    
    def get_recent_queries(self, limit: int = 20) -> List[Dict]:
        """Get recent query metrics"""
        recent = list(self.query_metrics)[-limit:]
        return [
            {
                "timestamp": m.timestamp.isoformat(),
                "query_type": m.query_type,
                "response_time_ms": m.response_time_ms,
                "sources_count": m.sources_count,
                "retrieval_count": m.retrieval_count,
                "rerank_count": m.rerank_count,
                "session_id": m.session_id,
                "query_preview": m.query_preview,
                "error": m.error,
                "error_message": m.error_message
            }
            for m in reversed(recent)  # Most recent first
        ]
    
    def get_counters(self) -> Dict[str, int]:
        """Get all counter metrics"""
        return dict(self.counters)
    
    def reset_counters(self):
        """Reset all counters (useful for testing or periodic resets)"""
        self.counters.clear()
        logger.info("Metrics counters reset")

