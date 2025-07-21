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
        event_id = event['id']
        event_type = event['event_type']
        aggregate_id = event['aggregate_id']
        
        try:
            # Parse event data
            event_data = json.loads(event['event_data']) if isinstance(event['event_data'], str) else event['event_data']
            
            # Проверяем размер данных события из базы
            raw_event_size = len(str(event['event_data']).encode('utf-8'))
            self.logger.info(
                "Processing outbox event",
                event_id=event_id,
                event_type=event_type,
                aggregate_id=aggregate_id,
                raw_event_size_bytes=raw_event_size,
                raw_event_size_mb=round(raw_event_size / 1024 / 1024, 2)
            )
            
            # Determine target topic based on event type
            topic = self.get_topic_for_event_type(event_type)
            
            # Publish event to Kafka with retry
            success = retry_with_backoff(
                lambda: self.publish_event_with_confirmation(topic, event_data, aggregate_id),
                max_attempts=self.max_retries,
                base_delay=1.0,
                max_delay=30.0
            )
            
            if success:
                # Mark event as processed
                self.mark_event_processed(event_id)
                
                self.logger.info(
                    "Event published successfully",
                    event_id=event_id,
                    event_type=event_type,
                    aggregate_id=aggregate_id,
                    topic=topic
                )
                
                self.metrics.record_business_event('outbox_event_processed', 'success')
                return True
            else:
                self.logger.error(
                    "Failed to publish event after retries",
                    event_id=event_id,
                    event_type=event_type
                )
                
                self.metrics.record_business_event('outbox_event_processed', 'failed')
                return False
                
        except Exception as e:
            self.logger.error(
                "Error processing event",
                event_id=event_id,
                error=str(e)
            )
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
        """Publish event to Kafka and confirm delivery"""
        try:
            success = self.events.publish_event(topic, event_data, key)
            
            if not success:
                raise Exception("Failed to publish event to Kafka")
            
            return True
            
        except Exception as e:
            self.logger.warning("Event publishing failed", topic=topic, error=str(e))
            raise
    
    def mark_event_processed(self, event_id: int):
        """Mark event as processed in outbox table"""
        try:
            with self.db.transaction():
                with self.db.get_cursor() as cursor:
                    cursor.execute("""
                        UPDATE orders.outbox_events
                        SET processed = true, processed_at = CURRENT_TIMESTAMP
                        WHERE id = %s
                    """, (event_id,))
                    
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