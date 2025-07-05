"""
Pizza Order System - Notification Service
Event-Driven Saga Architecture

Handles user notifications through multiple channels (email, SMS, push, webhook)
"""

import os
import sys
import json
import threading
import time
from typing import Dict, List, Any, Optional
from flask import request, jsonify
from flask_cors import CORS
from datetime import datetime, timezone
from enum import Enum

# Add shared module to path
sys.path.insert(0, '/app/shared')

from base_service import BaseService, generate_id, validate_required_fields, ValidationError, retry_with_backoff


class NotificationType(Enum):
    """Notification type enumeration"""
    EMAIL = "EMAIL"
    SMS = "SMS"
    PUSH = "PUSH"
    WEBHOOK = "WEBHOOK"


class NotificationStatus(Enum):
    """Notification status enumeration"""
    PENDING = "PENDING"
    SENT = "SENT"
    FAILED = "FAILED"
    DELIVERED = "DELIVERED"


class NotificationService(BaseService):
    """Notification Service for sending user notifications"""
    
    def __init__(self):
        super().__init__('notification-service')
        
        # Enable CORS for web UI
        CORS(self.app, origins=['*'])
        
        # Configuration
        self.email_enabled = os.getenv('EMAIL_ENABLED', 'true').lower() == 'true'
        self.sms_enabled = os.getenv('SMS_ENABLED', 'true').lower() == 'true'
        self.push_enabled = os.getenv('PUSH_ENABLED', 'true').lower() == 'true'
        self.webhook_enabled = os.getenv('WEBHOOK_ENABLED', 'true').lower() == 'true'
        
        # Rate limiting
        self.max_notifications_per_minute = int(os.getenv('MAX_NOTIFICATIONS_PER_MINUTE', '100'))
        
        # Setup routes
        self.setup_routes()
        
        # Initialize database
        self.init_database_with_schema_creation('notifications', 'SELECT 1')
        
        # Create default templates
        self.create_default_templates()
        
        # Start event consumer in background thread
        self.start_event_consumer()
        
        self.logger.info(
            "Notification Service initialized",
            email_enabled=self.email_enabled,
            sms_enabled=self.sms_enabled,
            push_enabled=self.push_enabled,
            webhook_enabled=self.webhook_enabled
        )

    def create_default_templates(self):
        """Create default notification templates if they don't exist."""
        templates = [
            {'type': 'OrderCreated', 'title_template': 'Pizza Order Confirmed', 'message_template': 'Your pizza order #{order_id} has been confirmed. Total: ${total/100:.2f}. We\'ll notify you when payment is processed.'},
            {'type': 'OrderPaid', 'title_template': 'Payment Successful', 'message_template': 'Payment of ${amount/100:.2f} for order #{order_id} was successful. Your pizza is being prepared!'},
            {'type': 'PaymentFailed', 'title_template': 'Payment Failed', 'message_template': 'Payment for order #{order_id} failed: {failure_reason}. Please try again or contact support.'}
        ]
        
        try:
            with self.db.get_cursor(commit=True) as cursor:
                for t in templates:
                    cursor.execute(
                        """
                        INSERT INTO notifications.notification_templates (type, title_template, message_template)
                        VALUES (%s, %s, %s)
                        ON CONFLICT (type) DO NOTHING
                        """,
                        (t['type'], t['title_template'], t['message_template'])
                    )
            self.logger.info("Default notification templates checked/created.")
        except Exception as e:
            self.logger.error("Failed to create default notification templates", error=str(e))

    def setup_routes(self):
        """Setup API routes for notification service"""
        
        @self.app.route('/api/v1/notifications', methods=['POST'])
        def send_notification():
            """Send notification through specified channels"""
            try:
                data = request.get_json()
                
                # Validate required fields
                required_fields = ['userId', 'message', 'channels']
                missing_fields = validate_required_fields(data, required_fields)
                
                if missing_fields:
                    raise ValidationError(f"Missing required fields: {', '.join(missing_fields)}")
                
                user_id = data['userId']
                subject = data.get('subject', 'Pizza Order Notification')
                message = data['message']
                channels = data.get('channels', ['EMAIL']) # Default to email
                order_id = data.get('orderId')
                priority = data.get('priority', 'normal')
                
                # Validate channels
                valid_channels = [t.value for t in NotificationType]
                invalid_channels = [c for c in channels if c not in valid_channels]
                if invalid_channels:
                    raise ValidationError(f"Invalid channels: {', '.join(invalid_channels)}")
                
                # Generate notification ID
                notification_id = generate_id('notif_')
                
                # Create notification record
                self.create_notification_record(
                    notification_id=notification_id,
                    user_id=user_id,
                    order_id=order_id,
                    subject=subject,
                    message=message,
                    channels=channels,
                    priority=priority
                )
                
                # Send notifications asynchronously
                threading.Thread(
                    target=self.send_notification_async,
                    args=(notification_id,),
                    daemon=True
                ).start()
                
                self.logger.info(
                    "Notification queued for sending",
                    notification_id=notification_id,
                    user_id=user_id,
                    channels=channels,
                    priority=priority
                )
                
                self.metrics.record_business_event('notification_queued', 'success')
                
                return jsonify({
                    'success': True,
                    'notificationId': notification_id,
                    'status': 'PENDING',
                    'channels': channels,
                    'timestamp': self.get_timestamp()
                }), 202  # Accepted - processing asynchronously
                
            except ValidationError as e:
                self.logger.warning("Notification validation failed", error=str(e))
                return jsonify({
                    'success': False,
                    'error': 'Validation error',
                    'message': str(e)
                }), 400
                
            except Exception as e:
                self.logger.error("Failed to queue notification", error=str(e))
                self.metrics.record_business_event('notification_queued', 'failed')
                
                return jsonify({
                    'success': False,
                    'error': 'Failed to queue notification',
                    'message': str(e)
                }), 500
    
    def create_notification_record(self, notification_id: str, user_id: str, order_id: str,
                                  subject: str, message: str, channels: List[str], priority: str,
                                  template_type: str = None) -> Dict:
        """Create notification record in the database"""
        try:
            with self.db.transaction():
                return self.db.execute_query(
                    """
                    INSERT INTO notifications.notifications 
                        (id, user_id, order_id, subject, message, channels, priority, template_type, status)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'PENDING')
                    RETURNING *
                    """,
                    (notification_id, user_id, order_id, subject, message, channels, priority, template_type),
                    fetch='one'
                )
        except Exception as e:
            self.logger.error("Failed to create notification record", error=str(e))
            raise
    
    def send_notification_async(self, notification_id: str):
        """Send notification through all specified channels asynchronously"""
        try:
            self.logger.info("Starting async notification sending", notification_id=notification_id)
            
            # Get notification details
            notification = self.get_notification_by_id(notification_id)
            if not notification:
                raise Exception(f"Notification {notification_id} not found")
            
            channels = json.loads(notification['channels']) if isinstance(notification['channels'], str) else notification['channels']
            user_id = notification['user_id']
            
            # Get user contact info
            contact_info = self.get_user_contact_info(user_id)
            
            success_count = 0
            total_channels = len(channels)
            
            # Send through each channel
            for channel in channels:
                try:
                    success = self.send_through_channel(notification, channel, contact_info)
                    if success:
                        success_count += 1
                except Exception as e:
                    self.logger.error(
                        "Failed to send through channel",
                        notification_id=notification_id,
                        channel=channel,
                        error=str(e)
                    )
            
            # Update notification status
            if success_count == total_channels:
                self.update_notification_status(notification_id, NotificationStatus.SENT.value)
                self.logger.info("All notifications sent successfully", notification_id=notification_id)
                self.metrics.record_business_event('notification_sent', 'success')
            elif success_count > 0:
                self.update_notification_status(notification_id, NotificationStatus.SENT.value)
                self.logger.warning(
                    "Partial notification success",
                    notification_id=notification_id,
                    success_count=success_count,
                    total_channels=total_channels
                )
                self.metrics.record_business_event('notification_sent', 'partial')
            else:
                self.update_notification_status(notification_id, NotificationStatus.FAILED.value)
                self.logger.error("All notification channels failed", notification_id=notification_id)
                self.metrics.record_business_event('notification_sent', 'failed')
                
        except Exception as e:
            self.logger.error("Notification async sending error", notification_id=notification_id, error=str(e))
            self.update_notification_status(notification_id, NotificationStatus.FAILED.value)
    
    def send_through_channel(self, notification: Dict, channel: str, contact_info: Dict) -> bool:
        """Send notification through specific channel"""
        try:
            notification_id = notification['id']
            
            # Record delivery attempt
            attempt_id = self.record_delivery_attempt(notification_id, channel)
            
            success = False
            error_message = None
            
            if channel == NotificationType.EMAIL.value and self.email_enabled:
                success = self.send_email_notification(notification, contact_info)
            elif channel == NotificationType.SMS.value and self.sms_enabled:
                success = self.send_sms_notification(notification, contact_info)
            elif channel == NotificationType.PUSH.value and self.push_enabled:
                success = self.send_push_notification(notification, contact_info)
            elif channel == NotificationType.WEBHOOK.value and self.webhook_enabled:
                success = self.send_webhook_notification(notification, contact_info)
            else:
                error_message = f"Channel {channel} is not enabled or not supported"
            
            # Update delivery attempt
            self.update_delivery_attempt(attempt_id, success, error_message)
            
            return success
            
        except Exception as e:
            self.logger.error(
                "Failed to send through channel",
                notification_id=notification['id'],
                channel=channel,
                error=str(e)
            )
            return False
    
    def send_email_notification(self, notification: Dict, contact_info: Dict) -> bool:
        """Send email notification (mocked implementation)"""
        try:
            email = contact_info.get('email')
            if not email:
                self.logger.warning("No email address for user", user_id=notification['user_id'])
                return False
            
            # Simulate email sending
            time.sleep(0.5)  # Simulate API call delay
            
            self.logger.info(
                "Email notification sent",
                notification_id=notification['id'],
                email=email,
                subject=notification['subject']
            )
            
            return True
            
        except Exception as e:
            self.logger.error("Email sending failed", error=str(e))
            return False
    
    def send_sms_notification(self, notification: Dict, contact_info: Dict) -> bool:
        """Send SMS notification (mocked implementation)"""
        try:
            phone = contact_info.get('phone')
            if not phone:
                self.logger.warning("No phone number for user", user_id=notification['user_id'])
                return False
            
            # Simulate SMS sending
            time.sleep(0.3)  # Simulate API call delay
            
            self.logger.info(
                "SMS notification sent",
                notification_id=notification['id'],
                phone=phone[:4] + "****" + phone[-2:],  # Mask phone number
                message_length=len(notification['message'])
            )
            
            return True
            
        except Exception as e:
            self.logger.error("SMS sending failed", error=str(e))
            return False
    
    def send_push_notification(self, notification: Dict, contact_info: Dict) -> bool:
        """Send push notification (mocked implementation)"""
        try:
            device_tokens = contact_info.get('device_tokens', [])
            if not device_tokens:
                self.logger.warning("No device tokens for user", user_id=notification['user_id'])
                return False
            
            # Simulate push notification sending
            time.sleep(0.2)  # Simulate API call delay
            
            self.logger.info(
                "Push notification sent",
                notification_id=notification['id'],
                device_count=len(device_tokens),
                title=notification['subject']
            )
            
            return True
            
        except Exception as e:
            self.logger.error("Push notification sending failed", error=str(e))
            return False
    
    def send_webhook_notification(self, notification: Dict, contact_info: Dict) -> bool:
        """Send webhook notification"""
        try:
            webhook_url = contact_info.get('webhook_url')
            if not webhook_url:
                self.logger.warning("No webhook URL for user", user_id=notification['user_id'])
                return False
            
            import requests
            
            payload = {
                'notification_id': notification['id'],
                'user_id': notification['user_id'],
                'order_id': notification['order_id'],
                'subject': notification['subject'],
                'message': notification['message'],
                'timestamp': self.get_timestamp()
            }
            
            response = requests.post(webhook_url, json=payload, timeout=10)
            
            if response.status_code == 200:
                self.logger.info(
                    "Webhook notification sent",
                    notification_id=notification['id'],
                    webhook_url=webhook_url,
                    status_code=response.status_code
                )
                return True
            else:
                self.logger.warning(
                    "Webhook notification failed",
                    notification_id=notification['id'],
                    webhook_url=webhook_url,
                    status_code=response.status_code
                )
                return False
                
        except Exception as e:
            self.logger.error("Webhook notification sending failed", error=str(e))
            return False
    
    def get_user_contact_info(self, user_id: str) -> Dict:
        """Get user contact information (mocked implementation)"""
        # In real implementation, this would query user service or database
        return {
            'email': f"{user_id}@example.com",
            'phone': f"+1555{user_id[-7:]}",
            'device_tokens': [f"device_token_{user_id}_1", f"device_token_{user_id}_2"],
            'webhook_url': f"https://webhook.example.com/users/{user_id}/notifications"
        }
    
    def record_delivery_attempt(self, notification_id: str, channel: str) -> int:
        """Record delivery attempt in database"""
        try:
            with self.db.get_cursor() as cursor:
                cursor.execute("""
                    INSERT INTO delivery_attempts (notification_id, channel, attempt_number)
                    VALUES (%s, %s, (
                        SELECT COALESCE(MAX(attempt_number), 0) + 1 
                        FROM delivery_attempts 
                        WHERE notification_id = %s AND channel = %s
                    ))
                    RETURNING id
                """, (notification_id, channel, notification_id, channel))
                
                attempt_id = cursor.fetchone()[0]
                return attempt_id
                
        except Exception as e:
            self.logger.error("Failed to record delivery attempt", error=str(e))
            raise
    
    def update_delivery_attempt(self, attempt_id: int, success: bool, error_message: str = None):
        """Update delivery attempt result"""
        try:
            with self.db.get_cursor() as cursor:
                cursor.execute("""
                    UPDATE delivery_attempts
                    SET success = %s, error_message = %s, completed_at = CURRENT_TIMESTAMP
                    WHERE id = %s
                """, (success, error_message, attempt_id))
                
        except Exception as e:
            self.logger.error("Failed to update delivery attempt", error=str(e))
            raise
    
    def get_notification_by_id(self, notification_id: str) -> Optional[Dict]:
        """Get notification by ID"""
        try:
            notifications = self.db.execute_query(
                "SELECT * FROM notifications WHERE id = %s",
                (notification_id,),
                fetch=True
            )
            return notifications[0] if notifications else None
        except Exception as e:
            self.logger.error("Failed to get notification by ID", notification_id=notification_id, error=str(e))
            raise
    
    def update_notification_status(self, notification_id: str, status: str):
        """Update notification status"""
        try:
            with self.db.get_cursor() as cursor:
                cursor.execute("""
                    UPDATE notifications
                    SET status = %s, updated_at = CURRENT_TIMESTAMP
                    WHERE id = %s
                """, (status, notification_id))
                
                self.logger.info("Notification status updated", notification_id=notification_id, status=status)
                
        except Exception as e:
            self.logger.error("Failed to update notification status", notification_id=notification_id, error=str(e))
            raise
    
    def start_event_consumer(self):
        """Start a background thread to consume Kafka events"""
        def consume_events():
            self.logger.info("Starting event consumer for payment and order events")
            
            while True:
                try:
                    self.events.process_events(
                        topics=['payment-events', 'order-events'],
                        group_id='notification-service-group',
                        handler_func=self.handle_event,
                        max_messages=10
                    )
                    time.sleep(1)
                except Exception as e:
                    self.logger.error("Event consumer error", error=str(e))
                    time.sleep(5)
        
        consumer_thread = threading.Thread(target=consume_events, daemon=True)
        consumer_thread.start()
        self.logger.info("Event consumer thread started")
    
    def handle_event(self, topic: str, event_data: Dict, key: str):
        """Handle events from Kafka by generating notifications."""
            event_type = event_data.get('event_type')
        order_id = event_data.get('orderId') or event_data.get('order_id')
            
        self.logger.info("Processing event for notification", topic=topic, event_type=event_type, order_id=order_id)
        
        try:
            if event_type == 'OrderCreated':
                self.handle_order_created(event_data)
            elif event_type == 'OrderPaid':
                self.handle_order_paid(event_data)
            elif event_type == 'PaymentFailed':
                self.handle_payment_failed(event_data)
            else:
                self.logger.warning("Unknown event type for notification", event_type=event_type)
            
        except Exception as e:
            self.logger.error(f"Failed to handle {event_type}", error=str(e), order_id=order_id)
    
    def handle_order_created(self, event_data: Dict):
        """Handle OrderCreated event."""
        user_id = event_data.get('userId', 'anonymous')
        order_id = event_data.get('orderId')
        
        # Ensure order_id is present
        if not order_id:
            self.logger.warning("OrderCreated event missing orderId", event_data=event_data)
            return

        template = self.get_template('OrderCreated')
        if not template:
            return

        message = template['message_template'].format(**event_data)
        subject = template['title_template'].format(**event_data)

        self.save_notification(
                user_id=user_id,
                order_id=order_id,
            template_type='OrderCreated',
            subject=subject,
            message=message,
            metadata=event_data
        )
    
    def handle_order_paid(self, event_data: Dict):
        """Handle OrderPaid event (successful payment)."""
        user_id = event_data.get('user_id', 'anonymous')
            order_id = event_data.get('order_id')
        
        if not order_id:
            self.logger.warning("OrderPaid event missing order_id", event_data=event_data)
            return

        template = self.get_template('OrderPaid')
        if not template:
            return

        message = template['message_template'].format(**event_data)
        subject = template['title_template'].format(**event_data)
            
        self.save_notification(
                user_id=user_id,
                order_id=order_id,
            template_type='OrderPaid',
            subject=subject,
            message=message,
            metadata=event_data
        )

    def handle_payment_failed(self, event_data: Dict):
        """Handle PaymentFailed event."""
        user_id = event_data.get('user_id', 'anonymous')
        order_id = event_data.get('order_id')
        
        if not order_id:
            self.logger.warning("PaymentFailed event missing order_id", event_data=event_data)
            return

        template = self.get_template('PaymentFailed')
        if not template:
            return

        message = template['message_template'].format(**event_data)
        subject = template['title_template'].format(**event_data)
        
        self.save_notification(
            user_id=user_id,
            order_id=order_id,
            template_type='PaymentFailed',
            subject=subject,
            message=message,
            metadata=event_data
        )

    def get_template(self, template_type: str) -> Optional[Dict]:
        """Get notification template from the database."""
        try:
            return self.db.execute_query(
                "SELECT * FROM notifications.notification_templates WHERE type = %s",
                (template_type,),
                fetch='one'
            )
        except Exception as e:
            self.logger.error("Failed to get notification template", template_type=template_type, error=str(e))
            return None

    def save_notification(self, user_id: str, order_id: str, template_type: str, subject: str, message: str, metadata: Dict) -> Optional[str]:
        """Save a generated notification to the database."""
        try:
            notification_id = generate_id('notif_')
            channels = metadata.get('notification_channels', ['EMAIL', 'PUSH']) # Default channels
            
            self.create_notification_record(
                notification_id=notification_id,
                user_id=user_id,
                order_id=order_id,
                subject=subject,
                message=message,
                channels=channels,
                priority='normal',
                template_type=template_type
            )
            self.logger.info("Notification saved to DB", notification_id=notification_id, order_id=order_id)
            return notification_id
        except Exception as e:
            self.logger.error("Failed to save notification", order_id=order_id, error=str(e))
            return None
    
    def get_timestamp(self) -> str:
        """Get current timestamp in ISO format"""
        return datetime.now(timezone.utc).isoformat()


# ========================================
# Application Entry Point
# ========================================

if __name__ == '__main__':
    try:
        # Create and run service
        service = NotificationService()
        service.logger.info("📢 Starting Notification Service")
        
        # Run in debug mode if specified
        debug_mode = os.getenv('FLASK_DEBUG', 'false').lower() == 'true'
        service.run(debug=debug_mode)
        
    except KeyboardInterrupt:
        print("\n🛑 Notification Service stopped by user")
    except Exception as e:
        print(f"❌ Notification Service failed to start: {e}")
        sys.exit(1) 