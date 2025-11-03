"""
RAG Analytics Service

Provides detailed analytics for RAG system:
- Query patterns and trends
- Document usage statistics
- Retrieval effectiveness
- Popular queries and keywords
"""

import logging
from typing import Dict, List, Optional, Tuple
from datetime import datetime, timedelta
from collections import defaultdict, Counter
import re

logger = logging.getLogger(__name__)


class RAGAnalytics:
    """Service for RAG-specific analytics"""
    
    def __init__(self, metrics_service):
        """
        Initialize RAG analytics
        
        Args:
            metrics_service: MetricsService instance to pull data from
        """
        self.metrics_service = metrics_service
        logger.info("RAGAnalytics initialized")
    
    def get_query_patterns(self, time_window_minutes: int = 60) -> Dict:
        """
        Analyze query patterns and trends
        
        Returns:
            Dictionary with query pattern analytics
        """
        cutoff_time = datetime.utcnow() - timedelta(minutes=time_window_minutes)
        
        recent_queries = [
            m for m in self.metrics_service.query_metrics
            if m.timestamp >= cutoff_time
        ]
        
        if not recent_queries:
            return {
                "total_queries": 0,
                "query_length_stats": {},
                "common_keywords": [],
                "query_patterns": {},
                "peak_hours": {},
            }
        
        # Analyze query lengths
        query_lengths = [len(m.query_preview or "") for m in recent_queries if m.query_preview]
        
        # Extract keywords from queries
        all_words = []
        for query in recent_queries:
            if query.query_preview:
                # Simple keyword extraction (remove common words)
                words = re.findall(r'\b[a-zA-Z]{3,}\b', query.query_preview.lower())
                # Filter out common stop words
                stop_words = {'the', 'what', 'who', 'where', 'when', 'why', 'how', 'is', 'are', 'this', 'that', 'these', 'those', 'and', 'or', 'but', 'with', 'for', 'from', 'about', 'into', 'onto', 'upon'}
                words = [w for w in words if w not in stop_words]
                all_words.extend(words)
        
        # Most common keywords
        keyword_counts = Counter(all_words)
        common_keywords = [
            {"keyword": word, "count": count}
            for word, count in keyword_counts.most_common(20)
        ]
        
        # Query patterns (question types)
        query_patterns = defaultdict(int)
        for query in recent_queries:
            if query.query_preview:
                preview_lower = query.query_preview.lower()
                if preview_lower.startswith('what'):
                    query_patterns['what_questions'] += 1
                elif preview_lower.startswith('who'):
                    query_patterns['who_questions'] += 1
                elif preview_lower.startswith('where'):
                    query_patterns['where_questions'] += 1
                elif preview_lower.startswith('when'):
                    query_patterns['when_questions'] += 1
                elif preview_lower.startswith('why'):
                    query_patterns['why_questions'] += 1
                elif preview_lower.startswith('how'):
                    query_patterns['how_questions'] += 1
                elif preview_lower.startswith('list') or preview_lower.startswith('show'):
                    query_patterns['listing_queries'] += 1
                elif '?' not in query.query_preview:
                    query_patterns['statements'] += 1
        
        # Peak hours analysis
        hour_counts = defaultdict(int)
        for query in recent_queries:
            hour = query.timestamp.hour
            hour_counts[hour] += 1
        
        peak_hours = dict(sorted(hour_counts.items(), key=lambda x: x[1], reverse=True)[:5])
        
        return {
            "total_queries": len(recent_queries),
            "query_length_stats": {
                "average": sum(query_lengths) / len(query_lengths) if query_lengths else 0,
                "min": min(query_lengths) if query_lengths else 0,
                "max": max(query_lengths) if query_lengths else 0,
                "median": sorted(query_lengths)[len(query_lengths) // 2] if query_lengths else 0,
            },
            "common_keywords": common_keywords,
            "query_patterns": dict(query_patterns),
            "peak_hours": peak_hours,
        }
    
    def get_document_usage_stats(self) -> Dict:
        """
        Analyze which documents are being used most frequently
        
        Returns:
            Dictionary with document usage statistics
        """
        # This will need to be enhanced to track document references
        # For now, we'll analyze based on sources in query metrics
        
        document_counts = defaultdict(int)
        document_response_times = defaultdict(list)
        document_session_usage = defaultdict(set)
        
        # Analyze query metrics for document references
        for query_metric in self.metrics_service.query_metrics:
            # We'd need to track which documents were used in each query
            # This is a simplified version - in production, track document IDs in query metrics
            if query_metric.sources_count > 0:
                # Track that documents were used (even if we don't know which ones)
                document_counts['total_document_queries'] += 1
                document_response_times['all'].append(query_metric.response_time_ms)
                if query_metric.session_id:
                    document_session_usage['all'].add(query_metric.session_id)
        
        return {
            "total_document_queries": document_counts.get('total_document_queries', 0),
            "unique_sessions_using_documents": len(document_session_usage.get('all', set())),
            "average_response_time_for_document_queries": (
                sum(document_response_times['all']) / len(document_response_times['all'])
                if document_response_times['all'] else 0
            ),
            "document_usage_trend": "increasing" if document_counts.get('total_document_queries', 0) > 0 else "stable",
        }
    
    def get_retrieval_effectiveness(self, time_window_minutes: int = 60) -> Dict:
        """
        Analyze retrieval effectiveness
        
        Returns:
            Dictionary with retrieval effectiveness metrics
        """
        cutoff_time = datetime.utcnow() - timedelta(minutes=time_window_minutes)
        
        recent_queries = [
            m for m in self.metrics_service.query_metrics
            if m.timestamp >= cutoff_time and m.query_type == 'document'
        ]
        
        if not recent_queries:
            return {
                "total_document_queries": 0,
                "average_retrieval_count": 0,
                "average_rerank_count": 0,
                "average_sources_count": 0,
                "retrieval_to_sources_ratio": 0,
                "rerank_usage_rate": 0,
            }
        
        # Calculate effectiveness metrics
        retrieval_counts = [m.retrieval_count for m in recent_queries if m.retrieval_count > 0]
        rerank_counts = [m.rerank_count for m in recent_queries if m.rerank_count > 0]
        sources_counts = [m.sources_count for m in recent_queries if m.sources_count > 0]
        
        avg_retrieval = sum(retrieval_counts) / len(retrieval_counts) if retrieval_counts else 0
        avg_rerank = sum(rerank_counts) / len(rerank_counts) if rerank_counts else 0
        avg_sources = sum(sources_counts) / len(sources_counts) if sources_counts else 0
        
        # Ratio: how many retrieved chunks result in sources shown to user
        retrieval_to_sources = (avg_sources / avg_retrieval * 100) if avg_retrieval > 0 else 0
        
        # Percentage of queries that used re-ranking
        rerank_usage = (len(rerank_counts) / len(recent_queries) * 100) if recent_queries else 0
        
        return {
            "total_document_queries": len(recent_queries),
            "average_retrieval_count": round(avg_retrieval, 2),
            "average_rerank_count": round(avg_rerank, 2),
            "average_sources_count": round(avg_sources, 2),
            "retrieval_to_sources_ratio": round(retrieval_to_sources, 2),
            "rerank_usage_rate": round(rerank_usage, 2),
        }
    
    def get_performance_trends(self, time_window_minutes: int = 60, buckets: int = 6) -> Dict:
        """
        Analyze performance trends over time
        
        Returns:
            Dictionary with performance trend data
        """
        cutoff_time = datetime.utcnow() - timedelta(minutes=time_window_minutes)
        bucket_size_minutes = time_window_minutes / buckets
        
        recent_queries = [
            m for m in self.metrics_service.query_metrics
            if m.timestamp >= cutoff_time
        ]
        
        if not recent_queries:
            return {
                "time_buckets": [],
                "response_time_trend": "stable",
                "error_rate_trend": "stable",
            }
        
        # Group queries into time buckets
        bucket_data = defaultdict(lambda: {"queries": [], "errors": 0})
        for query in recent_queries:
            minutes_ago = (datetime.utcnow() - query.timestamp).total_seconds() / 60
            bucket_index = int(minutes_ago / bucket_size_minutes)
            bucket_data[bucket_index]["queries"].append(query)
            if query.error:
                bucket_data[bucket_index]["errors"] += 1
        
        # Build trend data
        time_buckets = []
        response_times = []
        error_rates = []
        
        for i in range(buckets):
            bucket = bucket_data.get(i, {"queries": [], "errors": 0})
            queries_in_bucket = bucket["queries"]
            
            if queries_in_bucket:
                avg_response_time = sum(q.response_time_ms for q in queries_in_bucket) / len(queries_in_bucket)
                error_rate = (bucket["errors"] / len(queries_in_bucket)) * 100
                response_times.append(avg_response_time)
                error_rates.append(error_rate)
            else:
                response_times.append(0)
                error_rates.append(0)
            
            time_buckets.append({
                "bucket": i,
                "query_count": len(queries_in_bucket),
                "average_response_time_ms": round(avg_response_time if queries_in_bucket else 0, 2),
                "error_rate": round(error_rate if queries_in_bucket else 0, 2),
            })
        
        # Determine trends (simple: compare first half to second half)
        mid = len(response_times) // 2
        first_half_avg = sum(response_times[:mid]) / mid if mid > 0 and response_times[:mid] else 0
        second_half_avg = sum(response_times[mid:]) / (len(response_times) - mid) if len(response_times) > mid and response_times[mid:] else 0
        
        if first_half_avg == 0 or second_half_avg == 0:
            response_time_trend = "stable"
        elif second_half_avg > first_half_avg * 1.1:
            response_time_trend = "increasing"
        elif second_half_avg < first_half_avg * 0.9:
            response_time_trend = "decreasing"
        else:
            response_time_trend = "stable"
        
        first_half_error = sum(error_rates[:mid]) / mid if mid > 0 and error_rates[:mid] else 0
        second_half_error = sum(error_rates[mid:]) / (len(error_rates) - mid) if len(error_rates) > mid and error_rates[mid:] else 0
        
        if first_half_error == 0 and second_half_error == 0:
            error_rate_trend = "stable"
        elif second_half_error > first_half_error * 1.1:
            error_rate_trend = "increasing"
        elif second_half_error < first_half_error * 0.9:
            error_rate_trend = "decreasing"
        else:
            error_rate_trend = "stable"
        
        return {
            "time_buckets": time_buckets,
            "response_time_trend": response_time_trend,
            "error_rate_trend": error_rate_trend,
        }
    
    def get_query_success_analysis(self, time_window_minutes: int = 60) -> Dict:
        """
        Analyze query success patterns
        
        Returns:
            Dictionary with success analysis
        """
        cutoff_time = datetime.utcnow() - timedelta(minutes=time_window_minutes)
        
        recent_queries = [
            m for m in self.metrics_service.query_metrics
            if m.timestamp >= cutoff_time
        ]
        
        if not recent_queries:
            return {
                "total_queries": 0,
                "success_rate": 0,
                "success_by_type": {},
                "common_failure_patterns": [],
            }
        
        # Analyze success by query type
        success_by_type = defaultdict(lambda: {"total": 0, "success": 0, "failed": 0})
        
        for query in recent_queries:
            query_type = query.query_type
            success_by_type[query_type]["total"] += 1
            if query.error:
                success_by_type[query_type]["failed"] += 1
            else:
                success_by_type[query_type]["success"] += 1
        
        # Calculate success rates
        success_by_type_rates = {}
        for qtype, stats in success_by_type.items():
            success_rate = (stats["success"] / stats["total"] * 100) if stats["total"] > 0 else 0
            success_by_type_rates[qtype] = {
                "total": stats["total"],
                "success": stats["success"],
                "failed": stats["failed"],
                "success_rate": round(success_rate, 2),
            }
        
        total_success = sum(1 for q in recent_queries if not q.error)
        overall_success_rate = (total_success / len(recent_queries) * 100) if recent_queries else 0
        
        # Analyze failure patterns (if any)
        failed_queries = [q for q in recent_queries if q.error]
        failure_keywords = []
        if failed_queries:
            error_messages = [q.error_message or "" for q in failed_queries]
            # Extract common error patterns
            error_words = []
            for msg in error_messages:
                words = re.findall(r'\b[a-zA-Z]{4,}\b', msg.lower())
                error_words.extend(words)
            failure_keywords = [
                {"keyword": word, "count": count}
                for word, count in Counter(error_words).most_common(10)
            ]
        
        return {
            "total_queries": len(recent_queries),
            "success_rate": round(overall_success_rate, 2),
            "success_by_type": success_by_type_rates,
            "common_failure_patterns": failure_keywords,
        }

