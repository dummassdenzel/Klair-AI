"""
Structured Logging Configuration

Provides structured JSON logging for better observability, debugging, and metrics tracking.
Supports both JSON (production) and human-readable (development) formats.
"""

import json
import logging
import sys
from datetime import datetime
from typing import Any, Dict, Optional
from pathlib import Path


class StructuredFormatter(logging.Formatter):
    """Formatter that outputs structured JSON logs"""
    
    def format(self, record: logging.LogRecord) -> str:
        """Format log record as JSON"""
        log_data = {
            "timestamp": datetime.utcnow().isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno,
        }
        
        # Add exception info if present
        if record.exc_info:
            log_data["exception"] = self.formatException(record.exc_info)
        
        # Add extra fields (metrics, context, etc.)
        if hasattr(record, 'extra_fields'):
            log_data.update(record.extra_fields)
        
        # Add standard extra attributes
        for key, value in record.__dict__.items():
            if key not in [
                'name', 'msg', 'args', 'created', 'filename', 'funcName',
                'levelname', 'levelno', 'lineno', 'module', 'msecs',
                'message', 'pathname', 'process', 'processName', 'relativeCreated',
                'thread', 'threadName', 'exc_info', 'exc_text', 'stack_info',
                'extra_fields'
            ]:
                if not key.startswith('_'):
                    log_data[key] = value
        
        return json.dumps(log_data, default=str)


class MetricsLogger:
    """Context manager for tracking metrics in structured logs"""
    
    def __init__(self, logger: logging.Logger, operation: str, **context):
        self.logger = logger
        self.operation = operation
        self.context = context
        self.start_time = None
        self.metrics = {}
    
    def __enter__(self):
        self.start_time = datetime.utcnow()
        self.logger.info(
            f"Starting {self.operation}",
            extra={'extra_fields': {'operation': self.operation, 'action': 'start', **self.context}}
        )
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        duration_ms = (datetime.utcnow() - self.start_time).total_seconds() * 1000
        
        extra_fields = {
            'operation': self.operation,
            'action': 'complete' if exc_type is None else 'error',
            'duration_ms': round(duration_ms, 2),
            **self.context,
            **self.metrics
        }
        
        if exc_type:
            extra_fields['error_type'] = exc_type.__name__
            extra_fields['error_message'] = str(exc_val)
            self.logger.error(
                f"Failed {self.operation}",
                exc_info=exc_type,
                extra={'extra_fields': extra_fields}
            )
        else:
            self.logger.info(
                f"Completed {self.operation}",
                extra={'extra_fields': extra_fields}
            )
    
    def add_metric(self, key: str, value: Any):
        """Add a metric to be included in the completion log"""
        self.metrics[key] = value


def setup_logging(
    json_format: bool = False,
    log_level: str = "INFO",
    log_file: Optional[str] = None
):
    """
    Setup structured logging configuration
    
    Args:
        json_format: If True, use JSON format. If False, use human-readable format.
        log_level: Logging level (DEBUG, INFO, WARNING, ERROR)
        log_file: Optional file path to write logs to
    """
    # Set root logger level
    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, log_level.upper()))
    
    # Remove existing handlers
    root_logger.handlers.clear()
    
    # Create formatter
    if json_format:
        formatter = StructuredFormatter()
    else:
        formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
    
    # Console handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    root_logger.addHandler(console_handler)
    
    # File handler (if specified)
    if log_file:
        log_path = Path(log_file)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        
        file_handler = logging.FileHandler(log_file)
        file_handler.setFormatter(formatter)
        root_logger.addHandler(file_handler)
    
    # Suppress noisy loggers
    for noisy_logger in [
        "sqlalchemy.engine",
        "httpx",
        "chromadb",
        "watchdog.observers.inotify",
        "urllib3",
    ]:
        logging.getLogger(noisy_logger).setLevel(logging.WARNING)
    
    logging.getLogger(__name__).info(
        f"Logging configured: format={'JSON' if json_format else 'Human-readable'}, "
        f"level={log_level}"
    )


def log_query_metrics(
    logger: logging.Logger,
    query: str,
    query_type: str,
    response_time: float,
    sources_count: int,
    retrieval_count: int = None,
    rerank_count: int = None,
    session_id: int = None,
    **extra_metrics
):
    """
    Log structured metrics for a query
    
    Args:
        logger: Logger instance
        query: User query
        query_type: Classification result (greeting/general/document)
        response_time: Total response time in seconds
        sources_count: Number of sources returned
        retrieval_count: Number of chunks retrieved
        rerank_count: Number of chunks re-ranked
        session_id: Chat session ID
        **extra_metrics: Additional metrics to include
    """
    metrics = {
        'query_length': len(query),
        'query_type': query_type,
        'response_time_ms': round(response_time * 1000, 2),
        'sources_count': sources_count,
        **extra_metrics
    }
    
    if retrieval_count is not None:
        metrics['retrieval_count'] = retrieval_count
    if rerank_count is not None:
        metrics['rerank_count'] = rerank_count
    if session_id is not None:
        metrics['session_id'] = session_id
    
    logger.info(
        f"Query processed: type={query_type}, time={response_time:.2f}s, sources={sources_count}",
        extra={'extra_fields': {'event_type': 'query', 'query_preview': query[:100], **metrics}}
    )


def log_retrieval_metrics(
    logger: logging.Logger,
    semantic_count: int,
    keyword_count: int,
    fused_count: int,
    reranked_count: int = None,
    **extra_metrics
):
    """
    Log structured metrics for retrieval operations
    
    Args:
        logger: Logger instance
        semantic_count: Number of semantic search results
        keyword_count: Number of BM25 keyword results
        fused_count: Number after fusion
        reranked_count: Number after re-ranking (if applicable)
        **extra_metrics: Additional metrics
    """
    metrics = {
        'semantic_results': semantic_count,
        'keyword_results': keyword_count,
        'fused_results': fused_count,
        **extra_metrics
    }
    
    if reranked_count is not None:
        metrics['reranked_results'] = reranked_count
    
    logger.debug(
        f"Retrieval: semantic={semantic_count}, keyword={keyword_count}, fused={fused_count}",
        extra={'extra_fields': {'event_type': 'retrieval', **metrics}}
    )

