"""
Pizza Order System - Outbox Processor
Event-Driven Saga Architecture

Processes outbox events from Order Service and publishes them to Kafka
Implements reliable event publishing pattern
"""

import os
import sys
import json
import time
import signal
from typing import List, Dict, Any
from datetime import datetime, timezone

# Add shared module to path
sys.path.insert(0, '/app/shared')

from base_service import BaseService, retry_with_backoff


class OutboxProcessor:
    """Processes outbox events and publishes them to Kafka"""
    
    def __init__(self):
        # Initialize base service components
        self.service = BaseService('order-outbox-processor')
        self.logger = self.service.logger
        self.db = self.service.db
        self.events = self.service.events
        self.metrics = self.service.metrics
        
        # Processing configuration
        self.processing_interval = int(os.getenv('PROCESSING_INTERVAL', '5'))  # seconds
        self.batch_size = int(os.getenv('BATCH_SIZE', '10'))
        self.max_retries = int(os.getenv('MAX_RETRIES', '3'))
        
        # Graceful shutdown handling
        self.running = True
        signal.signal(signal.SIGTERM, self.signal_handler)
        signal.signal(signal.SIGINT, self.signal_handler)
        
        # Initialize database
        self.service.init_database_with_schema_creation('orders', 'SELECT COUNT(*) FROM orders.outbox_events WHERE processed = false')
        self.db.default_schema = 'orders'
        
        self.logger.info("Outbox Processor initialized")
    

    
    def signal_handler(self, signum, frame):
        """Handle graceful shutdown signals"""
        self.logger.info("Received shutdown signal", signal=signum)
        self.running = False
    
    def run(self):
        """Main processing loop"""
        self.logger.info("🚀 Starting Outbox Processor")
        
        while self.running:
            try:
                processed_count = self.process_batch()
                
                if processed_count > 0:
                    self.logger.info("Processed outbox events", count=processed_count)
                
                # Sleep between processing cycles
                time.sleep(self.processing_interval)
                
            except Exception as e:
                self.logger.error("Processing cycle failed", error=str(e))
                time.sleep(self.processing_interval * 2)  # Wait longer on error
        
        self.logger.info("Outbox Processor stopped")
    
    def process_batch(self) -> int:
        """Process a batch of unprocessed outbox events"""
        try:
            # Get unprocessed events
            unprocessed_events = self.get_unprocessed_events(self.batch_size)
            
            if not unprocessed_events:
                return 0
            
            processed_count = 0
            
            for event in unprocessed_events:
                try:
                    if self.process_single_event(event):
                        processed_count += 1
                    
                    if not self.running:
                        break
                        
                except Exception as e:
                    self.logger.error(
                        "Failed to process single event",
                        event_id=event['id'],
                        error=str(e)
                    )
            
            return processed_count
            
        except Exception as e:
            self.logger.error("Failed to process batch", error=str(e))
            return 0
    
    def get_unprocessed_events(self, limit: int) -> List[Dict[str, Any]]:
        """Get unprocessed events from outbox table"""
        try:
            return self.db.execute_query("""
                SELECT id, aggregate_id, event_type, event_data, created_at
                FROM orders.outbox_events
                WHERE processed = false
                ORDER BY created_at ASC
                LIMIT %s
            """, (limit,), fetch=True)
        except Exception as e:
            self.logger.error("Failed to get unprocessed events", error=str(e))
            return []
    
    def process_single_event(self, event: Dict[str, Any]) -> bool:
        """Process a single outbox event"""
        event_id = event.get('id')
        event_type = event.get('event_type')
        aggregate_id = event.get('aggregate_id')
        
        try:
            # Parse event data with error handling
            try:
                event_data = json.loads(event['event_data']) if isinstance(event['event_data'], str) else event['event_data']
            except (json.JSONDecodeError, KeyError) as e:
                self.logger.error(
                    "Failed to parse event data",
                    event_id=event_id,
                    event_type=event_type,
                    error=str(e),
                    error_type=type(e).__name__
                )
                self.metrics.record_business_event('outbox_event_processed', 'parse_error')
                return False
            
            # Проверяем размер данных события из базы
            raw_event_size = len(str(event.get('event_data', '')).encode('utf-8'))
            
            # Determine target topic based on event type
            topic = self.get_topic_for_event_type(event_type)
            
            # Извлекаем order_id и correlation_id из event_data для трейсинга
            order_id = event_data.get('orderId', aggregate_id)
            correlation_id = event_data.get('correlationId')
            
            self.logger.info(
                "🍕 ЗАКАЗ ПИЦЦЫ: Обрабатываем событие из Outbox",
                order_id=order_id,
                correlation_id=correlation_id,
                event_id=event_id,
                event_type=event_type,
                stage="outbox_processing",
                topic=topic,
                service="order-outbox-processor"
            )
            
            # Publish event to Kafka with retry
            self.logger.info(
                "🍕 ЗАКАЗ ПИЦЦЫ: Отправляем событие в Kafka",
                order_id=order_id,
                correlation_id=correlation_id,
                event_type=event_type,
                stage="kafka_publishing",
                topic=topic,
                service="order-outbox-processor"
            )
            
            success = retry_with_backoff(
                lambda: self.publish_event_with_confirmation(topic, event_data, aggregate_id),
                max_attempts=self.max_retries,
                base_delay=1.0,
                max_delay=30.0
            )
            
            if success:
                # Mark event as processed
                try:
                    self.mark_event_processed(event_id)
                except Exception as e:
                    self.logger.error(
                        "🍕 ЗАКАЗ ПИЦЦЫ: Ошибка при отметке события как обработанного",
                        order_id=order_id,
                        correlation_id=correlation_id,
                        event_id=event_id,
                        event_type=event_type,
                        stage="mark_processed_failed",
                        error=str(e),
                        service="order-outbox-processor"
                    )
                    self.metrics.record_business_event('outbox_event_processed', 'mark_error')
                    return False
                
                self.logger.info(
                    "🍕 ЗАКАЗ ПИЦЦЫ: Событие успешно отправлено в Kafka и помечено как обработанное",
                    order_id=order_id,
                    correlation_id=correlation_id,
                    event_id=event_id,
                    event_type=event_type,
                    stage="kafka_published_success",
                    topic=topic,
                    service="order-outbox-processor"
                )
                
                self.metrics.record_business_event('outbox_event_processed', 'success')
                return True
            else:
                self.logger.error(
                    "Failed to publish event after retries",
                    event_id=event_id,
                    event_type=event_type,
                    aggregate_id=aggregate_id,
                    topic=topic
                )
                
                self.metrics.record_business_event('outbox_event_processed', 'failed')
                return False
                
        except Exception as e:
            self.logger.error(
                "Error processing event",
                event_id=event_id,
                event_type=event_type,
                aggregate_id=aggregate_id,
                error=str(e),
                error_type=type(e).__name__
            )
            self.metrics.record_business_event('outbox_event_processed', 'error')
            return False
    
    def get_topic_for_event_type(self, event_type: str) -> str:
        """Determine Kafka topic based on event type"""
        topic_mapping = {
            'OrderCreated': 'order-events',
            'OrderStatusChanged': 'order-events',
            'OrderCompleted': 'order-events',
            'OrderCancelled': 'order-events'
        }
        
        return topic_mapping.get(event_type, 'order-events')
    
    def publish_event_with_confirmation(self, topic: str, event_data: Dict[str, Any], key: str) -> bool:
        """Publish event to Kafka with delivery confirmation and retries"""
        max_retries = 5
        base_retry_delay = 0.5
        
        for attempt in range(max_retries):
            try:
                # Log attempt
                self.logger.debug(
                    "Attempting to publish event to Kafka",
                    topic=topic,
                    key=key,
                    attempt=attempt + 1,
                    max_retries=max_retries,
                    message_size=len(str(event_data).encode('utf-8'))
                )
                
                # Send to Kafka with timeout
                success = self.events.publish_event(topic, event_data, key)
                
                if not success:
                    raise Exception("Failed to publish event to Kafka")
                
                self.logger.info(
                    "Event successfully published to Kafka",
                    topic=topic,
                    key=key,
                    attempt=attempt + 1
                )
                
                # Update success metrics
                self.metrics.record_business_event('kafka_event_published', 'success')
                
                return True
                
            except Exception as e:
                error_type = type(e).__name__
                
                self.logger.warning(
                    "Failed to publish event to Kafka",
                    topic=topic,
                    key=key,
                    attempt=attempt + 1,
                    max_retries=max_retries,
                    error=str(e),
                    error_type=error_type
                )
                
                # Update failure metrics
                self.metrics.record_business_event('kafka_event_published', 'failed')
                
                if attempt < max_retries - 1:
                    # Exponential backoff with jitter
                    delay = base_retry_delay * (2 ** attempt) + (0.1 * attempt)
                    self.logger.debug(
                        "Retrying after delay",
                        topic=topic,
                        delay=delay,
                        next_attempt=attempt + 2
                    )
                    time.sleep(delay)
                else:
                    self.logger.error(
                        "Failed to publish event after all retries",
                        topic=topic,
                        key=key,
                        total_attempts=max_retries,
                        final_error=str(e),
                        error_type=error_type
                    )
                    raise
        
        return False
    
    def mark_event_processed(self, event_id: int):
        """Mark event as processed in outbox table and commit the change.
        Uses a single transactional connection to avoid losing the UPDATE due to
        missing commit when using a separate pooled cursor.
        """
        try:
            # Acquire a dedicated transaction connection and commit on exit
            with self.db.transaction() as conn:
                with conn.cursor() as cursor:
                    cursor.execute(
                        """
                        UPDATE orders.outbox_events
                        SET processed = true, processed_at = CURRENT_TIMESTAMP
                        WHERE id = %s
                        """,
                        (event_id,)
                    )
                    if cursor.rowcount == 0:
                        raise Exception(f"Event {event_id} not found for marking as processed")
        except Exception as e:
            self.logger.error("Failed to mark event as processed", event_id=event_id, error=str(e))
            raise
    
    def get_processing_stats(self) -> Dict[str, Any]:
        """Get processing statistics"""
        try:
            with self.db.get_cursor() as cursor:
                cursor.execute("""
                    SELECT 
                        COUNT(*) as total_events,
                        COUNT(*) FILTER (WHERE processed = true) as processed_events,
                        COUNT(*) FILTER (WHERE processed = false) as pending_events,
                        COUNT(*) FILTER (WHERE processed = true AND processed_at > NOW() - INTERVAL '1 hour') as processed_last_hour
                    FROM orders.outbox_events
                """)
                stats = dict(cursor.fetchone())
                
            return stats
        except Exception as e:
            self.logger.error("Failed to get processing stats", error=str(e))
            return {}
    
    def cleanup_processed_events(self, retention_hours: int = 24):
        """Delete processed events older than the retention period."""
        try:
            with self.db.transaction():
                with self.db.get_cursor() as cursor:
                    cursor.execute("""
                        DELETE FROM orders.outbox_events
                        WHERE processed = true AND processed_at < NOW() - INTERVAL '%s hours'
                    """, (retention_hours,))
                    self.logger.info("Cleaned up old processed events", deleted_count=cursor.rowcount)
        except Exception as e:
            self.logger.error("Failed to cleanup processed events", error=str(e))


# ========================================
# Application Entry Point
# ========================================

if __name__ == '__main__':
    try:
        processor = OutboxProcessor()
        
        # Run cleanup on startup
        processor.cleanup_processed_events()
        
        # Start processing
        processor.run()
        
    except KeyboardInterrupt:
        print("\n🛑 Outbox Processor stopped by user")
    except Exception as e:
        print(f"❌ Outbox Processor failed to start: {e}")
        sys.exit(1)