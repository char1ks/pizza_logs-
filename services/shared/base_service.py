"""
Pizza Order System - Shared Base Service
Event-Driven Saga Architecture

Base class and utilities for all microservices
"""

import os
import json
import logging
import time
import uuid
import asyncio
from datetime import datetime, timezone
from typing import Dict, Any, Optional, List
from contextlib import contextmanager

import psycopg2
import psycopg2.extras
from psycopg2.pool import ThreadedConnectionPool
from kafka import KafkaProducer, KafkaConsumer
from kafka.errors import KafkaError
from flask import Flask, request, jsonify
from prometheus_client import Counter, Histogram, Gauge, generate_latest
import structlog


# ========================================
# Configuration Management
# ========================================

class Config:
    """Centralized configuration for microservices"""
    
    def __init__(self):
        # Database Configuration
        self.DATABASE_URL = os.getenv('DATABASE_URL', 'postgresql://pizza_user:pizza_password@postgres:5432/pizza_system')
        
        # Kafka Configuration
        self.KAFKA_BOOTSTRAP_SERVERS = os.getenv('KAFKA_BOOTSTRAP_SERVERS', 'kafka:29092').split(',')
        self.KAFKA_RETRIES = int(os.getenv('KAFKA_RETRIES', '3'))
        self.KAFKA_RETRY_BACKOFF_MS = int(os.getenv('KAFKA_RETRY_BACKOFF_MS', '100'))
        
        # Service Configuration
        self.SERVICE_NAME = os.getenv('SERVICE_NAME', 'unknown-service')
        self.SERVICE_VERSION = os.getenv('SERVICE_VERSION', '1.0.0')
        self.PORT = int(os.getenv('PORT', '5000'))
        
        # Retry Configuration
        self.RETRY_ATTEMPTS = int(os.getenv('RETRY_ATTEMPTS', '3'))
        self.RETRY_DELAY = int(os.getenv('RETRY_DELAY', '2'))
        
        # Monitoring Configuration
        self.ENABLE_METRICS = os.getenv('ENABLE_METRICS', 'true').lower() == 'true'
        self.METRICS_PATH = os.getenv('METRICS_PATH', '/metrics')
        
        # Logging Configuration
        self.LOG_LEVEL = os.getenv('LOG_LEVEL', 'INFO')
        # По умолчанию используем JSON-формат логов, чтобы UI получал метаданные
        self.LOG_FORMAT = os.getenv('LOG_FORMAT', 'json')


# ========================================
# Structured Logging Setup
# ========================================

def setup_logging(service_name: str, log_level: str = 'INFO') -> structlog.BoundLogger:
    """Setup structured logging for the service"""
    
    # Ensure logs directory exists and attach a file handler per service
    try:
        logs_dir = "/app/logs"
        os.makedirs(logs_dir, exist_ok=True)
        log_file_path = os.path.join(logs_dir, f"{service_name}.log")
    except Exception:
        # Fallback paths for non-container local runs
        logs_dir = os.path.join(os.getcwd(), "logs")
        os.makedirs(logs_dir, exist_ok=True)
        log_file_path = os.path.join(logs_dir, f"{service_name}.log")

    # Выбираем формат логов: text или json
    def _event_text_renderer(logger, name, event_dict):
        # Пишем только текст события/сообщение без метаданных
        msg = event_dict.get('event') or event_dict.get('message') or ''
        # На случай если передали нестроковые данные
        return str(msg)

    log_format = os.getenv('LOG_FORMAT', 'text').lower()
    final_renderer = structlog.processors.JSONRenderer() if log_format == 'json' else _event_text_renderer

    # Configure structlog
    structlog.configure(
        processors=[
            structlog.stdlib.filter_by_level,
            structlog.stdlib.add_logger_name,
            structlog.stdlib.add_log_level,
            structlog.stdlib.PositionalArgumentsFormatter(),
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.UnicodeDecoder(),
            final_renderer,
        ],
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )
    
    # Configure standard library logging
    logging.basicConfig(
        level=getattr(logging, log_level.upper()),
        format="%(message)s",
    )

    # Attach file handler to root logger to persist logs to /app/logs/<service>.log
    try:
        file_handler = logging.FileHandler(log_file_path)
        file_handler.setLevel(getattr(logging, log_level.upper()))
        file_handler.setFormatter(logging.Formatter("%(message)s"))
        root_logger = logging.getLogger()
        # Avoid duplicating handlers if already attached
        if not any(isinstance(h, logging.FileHandler) and getattr(h, 'baseFilename', None) == file_handler.baseFilename for h in root_logger.handlers):
            root_logger.addHandler(file_handler)
    except Exception:
        # If file handler fails, continue with console logging only
        pass

    # Suppress framework access logs from propagating to root/file
    try:
        wz_logger = logging.getLogger('werkzeug')
        wz_logger.setLevel(logging.ERROR)
        wz_logger.propagate = False
        flask_logger = logging.getLogger('flask.app')
        flask_logger.setLevel(logging.ERROR)
        flask_logger.propagate = False
        for name in (
            'kafka',
            'kafka.client',
            'kafka.conn',
            'kafka.cluster',
            'kafka.metrics',
            'kafka.producer.kafka',
            'kafka.consumer.fetcher',
            'kafka.coordinator.consumer',
            'kafka.coordinator.assignors',
        ):
            kl = logging.getLogger(name)
            kl.setLevel(logging.ERROR)
            kl.propagate = False
    except Exception:
        pass
    
    # Create logger for service with service metadata
    logger = structlog.get_logger(service_name)
    
    # Bind service metadata to all log messages
    service_version = os.getenv('SERVICE_VERSION', '1.0.0')
    container_id = os.getenv('HOSTNAME', 'unknown')  # Docker container hostname
    
    logger = logger.bind(
        service=service_name,
        version=service_version,
        container_id=container_id
    )
    
    return logger


# ========================================
# Metrics Collection
# ========================================

class ServiceMetrics:
    """Prometheus metrics for microservices"""
    
    def __init__(self, service_name: str):
        self.service_name = service_name
        
        # Request metrics
        self.request_count = Counter(
            'http_requests_total',
            'Total HTTP requests',
            ['service', 'method', 'endpoint', 'status']
        )
        
        self.request_duration = Histogram(
            'http_request_duration_seconds',
            'HTTP request duration',
            ['service', 'method', 'endpoint']
        )
        
        # Database metrics
        self.db_connections = Gauge(
            'database_connections_active',
            'Active database connections',
            ['service']
        )
        
        self.db_query_duration = Histogram(
            'database_query_duration_seconds',
            'Database query duration',
            ['service', 'operation']
        )
        
        # Kafka metrics
        self.kafka_messages_sent = Counter(
            'kafka_messages_sent_total',
            'Total Kafka messages sent',
            ['service', 'topic']
        )
        
        self.kafka_messages_received = Counter(
            'kafka_messages_received_total',
            'Total Kafka messages received',
            ['service', 'topic']
        )
        
        # Business metrics
        self.business_events = Counter(
            'business_events_total',
            'Total business events',
            ['service', 'event_type', 'status']
        )
        
        # System metrics
        self.open_file_descriptors = Gauge(
            'open_file_descriptors',
            'Number of open file descriptors',
            ['service']
        )
    
    def record_request(self, method: str, endpoint: str, status: int, duration: float):
        """Record HTTP request metrics"""
        self.request_count.labels(
            service=self.service_name,
            method=method,
            endpoint=endpoint,
            status=status
        ).inc()
        
        self.request_duration.labels(
            service=self.service_name,
            method=method,
            endpoint=endpoint
        ).observe(duration)
    
    def record_kafka_message(self, topic: str, sent: bool = True):
        """Record Kafka message metrics"""
        if sent:
            self.kafka_messages_sent.labels(
                service=self.service_name,
                topic=topic
            ).inc()
        else:
            self.kafka_messages_received.labels(
                service=self.service_name,
                topic=topic
            ).inc()
    
    def record_business_event(self, event_type: str, status: str = 'success'):
        """Record business event metrics"""
        self.business_events.labels(
            service=self.service_name,
            event_type=event_type,
            status=status
        ).inc()


# ========================================
# Database Connection Manager
# ========================================

class DatabaseManager:
    """Database connection and query management with thread-safe pool"""
    
    def __init__(self, config: Config, logger: structlog.BoundLogger, metrics: ServiceMetrics):
        self.config = config
        self.logger = logger
        self.metrics = metrics
        self._pool: Optional[ThreadedConnectionPool] = None
    
    def _get_pool(self) -> ThreadedConnectionPool:
        """Lazy-initialize a ThreadedConnectionPool"""
        if self._pool is None:
            try:
                minconn = int(os.getenv('DB_POOL_MIN', '5'))
                maxconn = int(os.getenv('DB_POOL_MAX', '50'))
                self._pool = ThreadedConnectionPool(
                    minconn,
                    maxconn,
                    self.config.DATABASE_URL,
                    cursor_factory=psycopg2.extras.RealDictCursor
                )
                self.logger.info("Database connection pool established", minconn=minconn, maxconn=maxconn)
            except Exception as e:
                self.logger.error("Failed to create DB pool", error=str(e))
                raise
        return self._pool
    
    def _acquire(self):
        pool = self._get_pool()
        conn = pool.getconn()
        conn.autocommit = False
        return conn
    
    def _release(self, conn):
        try:
            self._get_pool().putconn(conn)
        except Exception:
            pass
    
    @contextmanager
    def get_cursor(self):
        """Context manager for database cursor (pooled)"""
        connection = self._acquire()
        cursor = connection.cursor()
        try:
            yield cursor
        except Exception as e:
            connection.rollback()
            self.logger.error("Database operation failed", error=str(e))
            raise
        finally:
            try:
                cursor.close()
            finally:
                self._release(connection)
    
    @contextmanager
    def transaction(self):
        """Context manager for database transactions (pooled)"""
        connection = self._acquire()
        try:
            # Guard against long-running statements
            try:
                with connection.cursor() as c:
                    c.execute("SET LOCAL statement_timeout = '10s'")
            except Exception:
                pass
            
            yield connection
            connection.commit()
            self.logger.debug("Transaction committed")
        except Exception as e:
            connection.rollback()
            self.logger.error("Transaction rolled back", error=str(e))
            raise
        finally:
            self._release(connection)
    
    def execute_query(self, query: str, params: tuple = None, fetch: str = None) -> Optional[Dict]:
        """Execute database query with metrics"""
        start_time = time.time()
        
        try:
            with self.get_cursor() as cursor:
                cursor.execute(query, params)
                
                if fetch == 'one':
                    result = cursor.fetchone()
                    if result:
                        result_dict = dict(result)
                        self.logger.debug("Query executed", query=query, rows_returned=1)
                        return result_dict
                    else:
                        self.logger.debug("Query executed", query=query, rows_returned=0)
                        return None
                elif fetch == 'all':
                    result = cursor.fetchall()
                    result_list = [dict(row) for row in result]
                    self.logger.debug("Query executed", query=query, rows_returned=len(result_list))
                    return result_list
                elif fetch:  # For backward compatibility with boolean True
                    result = cursor.fetchall()
                    result_list = [dict(row) for row in result]
                    self.logger.debug("Query executed", query=query, rows_returned=len(result_list))
                    return result_list
                else:
                    self.logger.debug("Query executed", query=query, rows_affected=cursor.rowcount)
                    return None
        
        except Exception as e:
            self.logger.error("Query execution failed", query=query, error=str(e))
            raise
        
        finally:
            duration = time.time() - start_time
            self.metrics.db_query_duration.labels(
                service=self.config.SERVICE_NAME,
                operation='query'
            ).observe(duration)


# ========================================
# Kafka Event Manager
# ========================================

class EventManager:
    """Kafka event publishing and consuming"""
    
    def __init__(self, config: Config, logger: structlog.BoundLogger, metrics: ServiceMetrics):
        self.config = config
        self.logger = logger
        self.metrics = metrics
        self._producer = None
        self._consumers = {}
    
    def get_producer(self) -> KafkaProducer:
        """Get Kafka producer with retry logic"""
        if self._producer is None:
            self._producer = KafkaProducer(
                bootstrap_servers=self.config.KAFKA_BOOTSTRAP_SERVERS,
                value_serializer=lambda x: json.dumps(x).encode('utf-8'),
                key_serializer=lambda x: x.encode('utf-8') if x else None,
                retries=self.config.KAFKA_RETRIES,
                retry_backoff_ms=self.config.KAFKA_RETRY_BACKOFF_MS,
                acks='all',
                compression_type='gzip',
                max_request_size=104857600,  # 100MB
                buffer_memory=33554432  # 32MB
            )
            self.logger.debug("Kafka producer initialized")
        return self._producer
    
    def publish_event(self, topic: str, event_data: Dict[str, Any], key: str = None) -> bool:
        """Publish event to Kafka topic"""
        try:
            # Add metadata to event
            enriched_event = {
                **event_data,
                'service_name': self.config.SERVICE_NAME,
                'service_version': self.config.SERVICE_VERSION,
                'timestamp': datetime.now(timezone.utc).isoformat(),
                'event_id': str(uuid.uuid4())
            }
            
            # Проверяем размер сообщения
            event_json = json.dumps(enriched_event)
            event_size = len(event_json.encode('utf-8'))
            
            self.logger.debug(
                "Publishing event", 
                topic=topic, 
                event_type=event_data.get('event_type'),
                event_size_bytes=event_size,
                event_size_mb=round(event_size / 1024 / 1024, 2)
            )
            
            # Проверяем, не превышает ли размер лимит
            if event_size > 100 * 1024 * 1024:  # 100MB
                self.logger.error(
                    "Event too large to publish",
                    topic=topic,
                    event_size_bytes=event_size,
                    event_size_mb=round(event_size / 1024 / 1024, 2),
                    limit_mb=100
                )
                return False
            
            producer = self.get_producer()
            future = producer.send(topic, value=enriched_event, key=key)
            
            # Wait for send to complete
            record_metadata = future.get(timeout=10)
            
            self.logger.debug(
                "Event published",
                topic=topic,
                event_type=event_data.get('event_type'),
                partition=record_metadata.partition,
                offset=record_metadata.offset
            )
            
            self.metrics.record_kafka_message(topic, sent=True)
            return True
            
        except KafkaError as e:
            self.logger.error("Failed to publish event", topic=topic, error=str(e))
            self.metrics.record_business_event('event_publish', 'failed')
            return False
    
    def get_consumer(self, topics: List[str], group_id: str) -> KafkaConsumer:
        """Get Kafka consumer for topics"""
        consumer_key = f"{group_id}:{','.join(topics)}"
        
        if consumer_key not in self._consumers:
            self._consumers[consumer_key] = KafkaConsumer(
                *topics,
                bootstrap_servers=self.config.KAFKA_BOOTSTRAP_SERVERS,
                group_id=group_id,
                value_deserializer=lambda x: json.loads(x.decode('utf-8')),
                key_deserializer=lambda x: x.decode('utf-8') if x else None,
                auto_offset_reset='earliest',
                enable_auto_commit=True,
                consumer_timeout_ms=1000,
                max_partition_fetch_bytes=52428800,  # 50MB
                fetch_max_bytes=52428800  # 50MB
            )
            self.logger.debug("Kafka consumer initialized", topics=topics, group_id=group_id)
        
        return self._consumers[consumer_key]
    
    def process_events(self, topics: List[str], group_id: str, handler_func, max_messages: int = 100):
        """Process events from Kafka topics"""
        consumer = self.get_consumer(topics, group_id)
        
        try:
            for message in consumer:
                if max_messages <= 0:
                    break
                
                try:
                    self.logger.debug(
                        "Processing event",
                        topic=message.topic,
                        partition=message.partition,
                        offset=message.offset,
                        key=message.key
                    )
                    
                    # Call handler function
                    handler_func(message.topic, message.value, message.key)
                    
                    self.metrics.record_kafka_message(message.topic, sent=False)
                    max_messages -= 1
                    
                except Exception as e:
                    self.logger.error(
                        "Error processing event",
                        topic=message.topic,
                        error=str(e),
                        event_data=message.value
                    )
                    
        except Exception as e:
            self.logger.error("Consumer error", error=str(e))


# ========================================
# Base Service Class
# ========================================

class BaseService:
    """Base class for all microservices"""
    
    def __init__(self, service_name: str):
        # Initialize configuration
        self.config = Config()
        self.config.SERVICE_NAME = service_name
        
        # Setup logging
        self.logger = setup_logging(service_name, self.config.LOG_LEVEL)
        
        # Initialize metrics
        self.metrics = ServiceMetrics(service_name)
        
        # Initialize managers
        self.db = DatabaseManager(self.config, self.logger, self.metrics)
        self.events = EventManager(self.config, self.logger, self.metrics)
        
        # Flask app setup
        self.app = Flask(service_name)
        self.setup_flask_routes()
        
        self.logger.info("Service initialized", service=service_name)
    
    def setup_flask_routes(self):
        """Setup common Flask routes"""
        
        @self.app.before_request
        def before_request():
            request.start_time = time.time()
        
        @self.app.after_request
        def after_request(response):
            if hasattr(request, 'start_time'):
                duration = time.time() - request.start_time
                
                # Filter out technical endpoints from logging
                endpoint = request.endpoint or 'unknown'
                path = request.path
                
                # Skip logging of HTTP requests entirely to avoid noise
                # Metrics are still recorded below
                
                # Always record metrics (but not log)
                self.metrics.record_request(
                    method=request.method,
                    endpoint=endpoint,
                    status=response.status_code,
                    duration=duration
                )
            return response
        
        @self.app.route('/health')
        def health_check():
            """Health check endpoint"""
            try:
                # Test database connection
                with self.db.get_cursor() as cursor:
                    cursor.execute("SELECT 1")
                
                return jsonify({
                    'service': self.config.SERVICE_NAME,
                    'status': 'healthy',
                    'version': self.config.SERVICE_VERSION,
                    'timestamp': datetime.now(timezone.utc).isoformat()
                })
            except Exception as e:
                self.logger.error("Health check failed", error=str(e))
                return jsonify({
                    'service': self.config.SERVICE_NAME,
                    'status': 'unhealthy',
                    'error': str(e),
                    'timestamp': datetime.now(timezone.utc).isoformat()
                }), 503
        
        @self.app.route(self.config.METRICS_PATH)
        def metrics():
            """Prometheus metrics endpoint"""
            if not self.config.ENABLE_METRICS:
                return "Metrics disabled", 404
            
            try:
                # Добавляем дополнительные метрики перед экспортом
                self._update_runtime_metrics()
                
                from prometheus_client import CONTENT_TYPE_LATEST
                return generate_latest(), 200, {'Content-Type': CONTENT_TYPE_LATEST}
            except Exception as e:
                self.logger.error("Failed to generate metrics", error=str(e))
                return f"Error generating metrics: {str(e)}", 500
    
    def _update_runtime_metrics(self):
        """Update runtime metrics before export"""
        try:
            # Обновляем метрики активных подключений к БД
            # Это примерная реализация - можно расширить
            active_connections = 1 if hasattr(self.db, '_connection') and self.db._connection else 0
            self.metrics.db_connections.labels(service=self.config.SERVICE_NAME).set(active_connections)
            
            # Мониторинг открытых файловых дескрипторов
            try:
                import os
                import glob
                # Подсчитываем открытые файловые дескрипторы для текущего процесса
                fd_count = len(glob.glob(f'/proc/{os.getpid()}/fd/*'))
                self.metrics.open_file_descriptors.labels(service=self.config.SERVICE_NAME).set(fd_count)
            except Exception:
                # Fallback для систем без /proc (например, macOS)
                try:
                    import resource
                    fd_count = resource.getrlimit(resource.RLIMIT_NOFILE)[0]  # Лимит как приблизительное значение
                    self.metrics.open_file_descriptors.labels(service=self.config.SERVICE_NAME).set(fd_count)
                except Exception:
                    pass  # Игнорируем если не можем получить информацию
            
        except Exception as e:
            self.logger.debug("Failed to update runtime metrics", error=str(e))
    
    def init_database_with_schema_creation(self, schema_name: str, test_query: str = None):
        """Initialize database connection and create schema if needed."""
        max_retries = 10
        retry_delay = 5  # seconds
        for attempt in range(max_retries):
            try:
                with self.db.get_cursor() as cursor:
                    # Create schema if it doesn't exist
                    cursor.execute(f"CREATE SCHEMA IF NOT EXISTS {schema_name}")
                    
                    # Set search path
                    cursor.execute(f"SET search_path TO {schema_name}, public")
                    
                    # Test connection with specific query if provided
                    if test_query:
                        cursor.execute(test_query)
                        result = cursor.fetchone()
                        self.logger.info(f"{schema_name.title()} database initialized", result=result)
                    else:
                        self.logger.info(f"{schema_name.title()} schema ready")
                
                return  # Success
                
            except Exception as e:
                self.logger.warning(
                    "Database initialization failed, retrying...",
                    attempt=attempt + 1,
                    max_retries=max_retries,
                    schema=schema_name,
                    error=str(e)
                )
                if attempt < max_retries - 1:
                    time.sleep(retry_delay)
                else:
                    self.logger.error("Could not initialize database after all retries.", error=str(e))
                    # Continue without failing - service might still work
                    return

    def run(self, debug: bool = False):
        """Run the Flask application"""
        self.logger.info(
            "Starting service",
            service=self.config.SERVICE_NAME,
            version=self.config.SERVICE_VERSION,
            port=self.config.PORT
        )
        
        try:
            self.app.run(
                host='0.0.0.0',
                port=self.config.PORT,
                debug=debug,
                threaded=True
            )
        except Exception as e:
            self.logger.error("Failed to start service", error=str(e))
            raise


# ========================================
# Utility Functions
# ========================================

def generate_id(prefix: str = '') -> str:
    """Generate unique ID with optional prefix"""
    timestamp = int(time.time() * 1000)
    unique_part = str(uuid.uuid4()).split('-')[0]
    return f"{prefix}{timestamp}_{unique_part}" if prefix else f"{timestamp}_{unique_part}"


def retry_with_backoff(func, max_attempts: int = 3, base_delay: float = 1.0, max_delay: float = 60.0):
    """Retry function with exponential backoff"""
    for attempt in range(max_attempts):
        try:
            return func()
        except Exception as e:
            if attempt == max_attempts - 1:
                raise e
            
            delay = min(base_delay * (2 ** attempt), max_delay)
            time.sleep(delay)


def format_currency(cents: int) -> str:
    """Format currency from cents to dollars"""
    return f"${cents / 100:.2f}"


def format_order_status_message(order_id: str, status: str, service: str, **kwargs) -> str:
    """Format user-friendly order status message"""
    status_messages = {
        'PENDING': f"📝 Заказ #{order_id[:8]} принят и ожидает обработки",
        'PROCESSING': f"⚙️ Заказ #{order_id[:8]} обрабатывается",
        'PAID': f"💳 Заказ #{order_id[:8]} оплачен успешно",
        'FAILED': f"❌ Заказ #{order_id[:8]} не удался",
        'COMPLETED': f"✅ Заказ #{order_id[:8]} выполнен",
        'CANCELLED': f"🚫 Заказ #{order_id[:8]} отменен"
    }
    
    base_message = status_messages.get(status, f"📋 Заказ #{order_id[:8]} - статус: {status}")
    
    # Add additional context based on service and kwargs
    if service == 'payment-service':
        if 'amount' in kwargs:
            amount_str = format_currency(kwargs['amount'])
            base_message += f" (сумма: {amount_str})"
        if 'payment_method' in kwargs:
            base_message += f" (способ оплаты: {kwargs['payment_method']})"
    
    if 'reason' in kwargs and kwargs['reason']:
        base_message += f" - {kwargs['reason']}"
    
    return base_message


def validate_required_fields(data: Dict[str, Any], required_fields: List[str]) -> List[str]:
    """Validate required fields in data"""
    missing_fields = []
    for field in required_fields:
        if field not in data or data[field] is None:
            missing_fields.append(field)
    return missing_fields


# ========================================
# Exception Classes
# ========================================

class ServiceError(Exception):
    """Base service exception"""
    pass


class ValidationError(ServiceError):
    """Data validation error"""
    pass


class DatabaseError(ServiceError):
    """Database operation error"""
    pass


class EventPublishError(ServiceError):
    """Event publishing error"""
    pass