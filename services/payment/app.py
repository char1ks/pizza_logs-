"""
Pizza Order System - Payment Service
Event-Driven Saga Architecture

Handles payment processing with retry pattern, idempotency, and circuit breaker
"""

import os
import sys
import json
import threading
import time
import hashlib
from typing import Dict, List, Any, Optional
from flask import request, jsonify
from flask_cors import CORS
from datetime import datetime, timezone, timedelta
from enum import Enum
import requests

# Add shared module to path
sys.path.insert(0, '/app/shared')

from base_service import BaseService, generate_id, validate_required_fields, ValidationError, retry_with_backoff


class PaymentStatus(Enum):
    """Payment status enumeration"""
    PENDING = "PENDING"
    PROCESSING = "PROCESSING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class CircuitBreakerState(Enum):
    """Circuit breaker state enumeration"""
    CLOSED = "CLOSED"
    OPEN = "OPEN"
    HALF_OPEN = "HALF_OPEN"


class CircuitBreaker:
    """Circuit breaker implementation for payment provider"""
    
    def __init__(self, failure_threshold: int = 5, timeout: int = 60, success_threshold: int = 3):
        self.failure_threshold = failure_threshold
        self.timeout = timeout
        self.success_threshold = success_threshold
        
        self.failure_count = 0
        self.success_count = 0
        self.last_failure_time = None
        self.state = CircuitBreakerState.CLOSED
    
    def can_execute(self) -> bool:
        """Check if request can be executed"""
        if self.state == CircuitBreakerState.CLOSED:
            return True
        elif self.state == CircuitBreakerState.OPEN:
            if self.last_failure_time and \
               datetime.now() > self.last_failure_time + timedelta(seconds=self.timeout):
                self.state = CircuitBreakerState.HALF_OPEN
                self.success_count = 0
                return True
            return False
        elif self.state == CircuitBreakerState.HALF_OPEN:
            return True
        
        return False
    
    def record_success(self):
        """Record successful execution"""
        if self.state == CircuitBreakerState.HALF_OPEN:
            self.success_count += 1
            if self.success_count >= self.success_threshold:
                self.state = CircuitBreakerState.CLOSED
                self.failure_count = 0
        else:
            self.failure_count = 0
    
    def record_failure(self):
        """Record failed execution"""
        self.failure_count += 1
        self.last_failure_time = datetime.now()
        
        if self.failure_count >= self.failure_threshold:
            self.state = CircuitBreakerState.OPEN


class PaymentService(BaseService):
    """Payment Service for processing payments with reliability patterns"""
    
    def __init__(self):
        super().__init__('payment-service')
        
        # Enable CORS for web UI
        CORS(self.app, origins=['*'])
        
        # Configuration
        self.max_retry_attempts = int(os.getenv('PAYMENT_MAX_RETRIES', '3'))
        self.retry_delay_base = float(os.getenv('PAYMENT_RETRY_DELAY', '2.0'))
        self.payment_timeout = int(os.getenv('PAYMENT_TIMEOUT', '30'))
        
        # Circuit breaker for payment provider
        self.circuit_breaker = CircuitBreaker(
            failure_threshold=int(os.getenv('CB_FAILURE_THRESHOLD', '5')),
            timeout=int(os.getenv('CB_TIMEOUT', '60')),
            success_threshold=int(os.getenv('CB_SUCCESS_THRESHOLD', '3'))
        )
        
        # Setup routes
        self.setup_routes()
        
        # Initialize database
        self.init_database_with_schema_creation('payments', 'SELECT 1')
        
        # Start event consumer in background thread
        self.start_event_consumer()
        
        self.logger.info("Payment Service initialized")
    

    
    def setup_routes(self):
        """Setup API routes for payment service"""
        
        @self.app.route('/api/v1/payments', methods=['POST'])
        def process_payment():
            """Process payment with retry pattern and idempotency"""
            try:
                data = request.get_json()
                
                # Validate required fields
                required_fields = ['orderId', 'amount', 'paymentMethod']
                missing_fields = validate_required_fields(data, required_fields)
                
                if missing_fields:
                    raise ValidationError(f"Missing required fields: {', '.join(missing_fields)}")
                
                order_id = data['orderId']
                amount = data['amount']
                payment_method = data['paymentMethod']
                
                # Validate amount
                if amount <= 0:
                    raise ValidationError("Amount must be positive")
                
                # Check for existing payment (idempotency)
                existing_payment = self.get_payment_by_order_id(order_id)
                if existing_payment:
                    self.logger.info("Payment already exists for order", order_id=order_id)
                    return jsonify({
                        'success': True,
                        'paymentId': existing_payment['id'],
                        'status': existing_payment['status'],
                        'message': 'Payment already processed'
                    })
                
                # Generate payment ID and idempotency key
                payment_id = generate_id('payment_')
                idempotency_key = self.generate_idempotency_key(order_id, amount, payment_method)
                
                # Create payment record
                payment_data = self.create_payment_record(
                    payment_id=payment_id,
                    order_id=order_id,
                    amount=amount,
                    payment_method=payment_method,
                    idempotency_key=idempotency_key
                )
                
                # Process payment asynchronously
                threading.Thread(
                    target=self.process_payment_async,
                    args=(payment_id,),
                    daemon=True
                ).start()
                
                self.logger.info(
                    "Payment processing started",
                    payment_id=payment_id,
                    order_id=order_id,
                    amount=amount
                )
                
                self.metrics.record_business_event('payment_started', 'success')
                
                return jsonify({
                    'success': True,
                    'paymentId': payment_id,
                    'status': 'PROCESSING',
                    'timestamp': self.get_timestamp()
                }), 202  # Accepted - processing asynchronously
                
            except ValidationError as e:
                self.logger.warning("Payment validation failed", error=str(e))
                return jsonify({
                    'success': False,
                    'error': 'Validation error',
                    'message': str(e)
                }), 400
                
            except Exception as e:
                self.logger.error("Failed to start payment processing", error=str(e))
                self.metrics.record_business_event('payment_started', 'failed')
                
                return jsonify({
                    'success': False,
                    'error': 'Failed to process payment',
                    'message': str(e)
                }), 500
        
        @self.app.route('/api/v1/payments/<payment_id>', methods=['GET'])
        def get_payment(payment_id: str):
            """Get payment details by ID"""
            try:
                payment = self.get_payment_by_id(payment_id)
                
                if not payment:
                    return jsonify({
                        'success': False,
                        'error': 'Payment not found'
                    }), 404
                
                # Get payment attempts
                attempts = self.get_payment_attempts(payment_id)
                payment['attempts'] = attempts
                
                self.logger.info("Payment retrieved", payment_id=payment_id)
                
                return jsonify({
                    'success': True,
                    'payment': payment,
                    'timestamp': self.get_timestamp()
                })
                
            except Exception as e:
                self.logger.error("Failed to get payment", payment_id=payment_id, error=str(e))
                
                return jsonify({
                    'success': False,
                    'error': 'Failed to retrieve payment'
                }), 500
        
        @self.app.route('/api/v1/payments/order/<order_id>', methods=['GET'])
        def get_payment_by_order(order_id: str):
            """Get payment by order ID"""
            try:
                payment = self.get_payment_by_order_id(order_id)
                
                if not payment:
                    return jsonify({
                        'success': False,
                        'error': 'Payment not found for order'
                    }), 404
                
                # Get payment attempts
                attempts = self.get_payment_attempts(payment['id'])
                payment['attempts'] = attempts
                
                return jsonify({
                    'success': True,
                    'payment': payment
                })
                
            except Exception as e:
                self.logger.error("Failed to get payment by order", order_id=order_id, error=str(e))
                
                return jsonify({
                    'success': False,
                    'error': 'Failed to retrieve payment'
                }), 500
        
        @self.app.route('/api/v1/payments/circuit-breaker/status', methods=['GET'])
        def get_circuit_breaker_status():
            """Get circuit breaker status"""
            try:
                return jsonify({
                    'success': True,
                    'circuitBreaker': {
                        'state': self.circuit_breaker.state.value,
                        'failureCount': self.circuit_breaker.failure_count,
                        'successCount': self.circuit_breaker.success_count,
                        'canExecute': self.circuit_breaker.can_execute()
                    }
                })
            except Exception as e:
                self.logger.error("Failed to get circuit breaker status", error=str(e))
                return jsonify({
                    'success': False,
                    'error': 'Failed to get circuit breaker status'
                }), 500
    
        @self.app.route('/api/v1/payments/circuit-breaker/reset', methods=['POST'])
        def reset_circuit_breaker():
            """Reset circuit breaker to CLOSED state"""
            try:
                self.circuit_breaker.state = CircuitBreakerState.CLOSED
                self.circuit_breaker.failure_count = 0
                self.circuit_breaker.success_count = 0
                self.circuit_breaker.last_failure_time = None
                
                self.logger.info("Circuit breaker reset to CLOSED state")
                
                return jsonify({
                    'success': True,
                    'message': 'Circuit breaker reset successfully',
                    'circuitBreaker': {
                        'state': self.circuit_breaker.state.value,
                        'failureCount': self.circuit_breaker.failure_count,
                        'successCount': self.circuit_breaker.success_count,
                        'canExecute': self.circuit_breaker.can_execute()
                    }
                })
            except Exception as e:
                self.logger.error("Failed to reset circuit breaker", error=str(e))
                return jsonify({
                    'success': False,
                    'error': 'Failed to reset circuit breaker'
                }), 500
    
    def generate_idempotency_key(self, order_id: str, amount: int, payment_method: str) -> str:
        """Generate idempotency key for payment"""
        data = f"{order_id}:{amount}:{payment_method}"
        return hashlib.sha256(data.encode()).hexdigest()
    
    def create_payment_record(self, payment_id: str, order_id: str, amount: int,
                            payment_method: str, idempotency_key: str) -> Dict:
        """Create payment record in database"""
        try:
            with self.db.transaction():
                with self.db.get_cursor() as cursor:
                    cursor.execute("""
                        INSERT INTO payments (id, order_id, amount, payment_method, status, idempotency_key)
                        VALUES (%s, %s, %s, %s, %s, %s)
                    """, (payment_id, order_id, amount, payment_method, PaymentStatus.PENDING.value, idempotency_key))
                
                self.logger.info("Payment record created", payment_id=payment_id, order_id=order_id)
                
                return {
                    'payment_id': payment_id,
                    'order_id': order_id,
                    'amount': amount,
                    'status': PaymentStatus.PENDING.value
                }
                
        except Exception as e:
            self.logger.error("Failed to create payment record", error=str(e))
            raise
    
    def process_payment_async(self, payment_id: str):
        """Process payment asynchronously with retry pattern"""
        try:
            self.logger.info("🔄 Starting async payment processing", payment_id=payment_id)
            
            # Update status to PROCESSING
            self.logger.info("📝 Updating payment status to PROCESSING", payment_id=payment_id)
            self.update_payment_status(payment_id, PaymentStatus.PROCESSING.value)
            
            # Process with retry pattern
            self.logger.info("🔁 Starting retry pattern for payment", payment_id=payment_id)
            success = retry_with_backoff(
                lambda: self.attempt_payment_processing(payment_id),
                max_attempts=self.max_retry_attempts,
                base_delay=self.retry_delay_base,
                max_delay=30.0
            )
            
            self.logger.info(f"🎯 Retry pattern completed, success={success}", payment_id=payment_id)
            
            if success:
                # Update status to COMPLETED
                self.logger.info("✅ Payment succeeded, updating status to COMPLETED", payment_id=payment_id)
                self.update_payment_status(payment_id, PaymentStatus.COMPLETED.value)
                
                # Publish success event
                self.logger.info("📤 Publishing payment success event", payment_id=payment_id)
                self.publish_payment_success_event(payment_id)
                
                self.logger.info("🎉 Payment processing completed successfully", payment_id=payment_id)
                self.metrics.record_business_event('payment_completed', 'success')
                
            else:
                # Update status to FAILED
                self.logger.error("❌ Payment failed, updating status to FAILED", payment_id=payment_id)
                self.update_payment_status(payment_id, PaymentStatus.FAILED.value, "Payment failed after retries")
                
                # Publish failure event
                self.logger.info("📤 Publishing payment failure event", payment_id=payment_id)
                self.publish_payment_failure_event(payment_id)
                
                self.logger.error("💥 Payment processing failed after retries", payment_id=payment_id)
                self.metrics.record_business_event('payment_completed', 'failed')
                
        except Exception as e:
            self.logger.error("🚨 Payment async processing error", payment_id=payment_id, error=str(e), exc_info=True)
            
            # Update status to FAILED
            self.update_payment_status(payment_id, PaymentStatus.FAILED.value, str(e))
            
            # Publish failure event
            self.publish_payment_failure_event(payment_id)
    
    def attempt_payment_processing(self, payment_id: str) -> bool:
        """Attempt to process payment (with circuit breaker)"""
        try:
            self.logger.info("🔍 Starting payment attempt", payment_id=payment_id)
            
            # Check circuit breaker
            if not self.circuit_breaker.can_execute():
                self.logger.warning("⚡ Circuit breaker is OPEN, payment blocked", payment_id=payment_id)
                raise Exception("Payment provider is unavailable (circuit breaker OPEN)")
            
            self.logger.info("✅ Circuit breaker check passed", payment_id=payment_id)
            
            # Get payment details
            self.logger.info("📋 Getting payment details", payment_id=payment_id)
            payment = self.get_payment_by_id(payment_id)
            if not payment:
                raise Exception(f"Payment {payment_id} not found")
            
            self.logger.info("✅ Payment details retrieved", payment_id=payment_id, order_id=payment.get('order_id'))
            
            # Record payment attempt
            self.logger.info("📝 Recording payment attempt", payment_id=payment_id)
            attempt_id = self.record_payment_attempt(payment_id)
            self.logger.info("✅ Payment attempt recorded", payment_id=payment_id, attempt_id=attempt_id)
            
            # Call external payment provider (mocked)
            self.logger.info("🌐 Calling payment provider", payment_id=payment_id)
            success = self.call_payment_provider(payment)
            self.logger.info(f"🎯 Payment provider call completed, success={success}", payment_id=payment_id)
            
            if success:
                # Record successful attempt
                self.logger.info("✅ Recording successful attempt", payment_id=payment_id, attempt_id=attempt_id)
                self.update_payment_attempt(attempt_id, success=True)
                self.circuit_breaker.record_success()
                return True
            else:
                # Check if this is a crash test (address = "123") to avoid affecting circuit breaker
                is_crash_test = False
                try:
                    order = self.db.execute_query(
                        "SELECT delivery_address FROM orders.orders WHERE id = %s",
                        (payment.get('order_id'),),
                        fetch='one'
                    )
                    if order:
                        delivery_address_clean = str(order.get('delivery_address', '')).strip()
                        is_crash_test = (delivery_address_clean == '123')
                except Exception:
                    pass
                
                # Record failed attempt
                self.logger.warning("❌ Recording failed attempt", payment_id=payment_id, attempt_id=attempt_id)
                self.update_payment_attempt(attempt_id, success=False, error="Payment provider rejected")
                
                # Only affect circuit breaker if it's not a crash test
                if not is_crash_test:
                    self.circuit_breaker.record_failure()
                    self.logger.info("⚡ Circuit breaker failure recorded for real payment", payment_id=payment_id)
                else:
                    self.logger.info("🧪 Crash test failure - circuit breaker not affected", payment_id=payment_id)
                
                raise Exception("Payment provider rejected the transaction")
                
        except Exception as e:
            self.logger.warning("⚠️ Payment attempt failed", payment_id=payment_id, error=str(e), exc_info=True)
            self.circuit_breaker.record_failure()
            raise
    
    def call_payment_provider(self, payment: Dict) -> bool:
        """Call the external payment provider (mock)."""
        payment_id = payment.get('id', 'unknown')
        order_id = payment.get('order_id')
        
        # Check if delivery address is "123" - force failure for testing (but don't affect circuit breaker)
        is_crash_test = False
        try:
            # Get order details to check delivery address
            self.logger.info("🔍 Checking delivery address for order", payment_id=payment_id, order_id=order_id)
            
            order = self.db.execute_query(
                "SELECT delivery_address FROM orders.orders WHERE id = %s",
                (order_id,),
                fetch='one'
            )
            
            if order:
                delivery_address = order.get('delivery_address', '')
                # Strip whitespace and convert to string for comparison
                delivery_address_clean = str(delivery_address).strip()
                
                self.logger.info("📍 Found delivery address", 
                               payment_id=payment_id, 
                               order_id=order_id, 
                               delivery_address=delivery_address,
                               delivery_address_clean=delivery_address_clean,
                               address_length=len(delivery_address_clean))
                
                # Check for EXACT match with "123" only
                if delivery_address_clean == '123':
                    self.logger.warning("🧪 CRASH TEST - Address is exactly '123', forcing payment failure", 
                                      payment_id=payment_id, order_id=order_id)
                    is_crash_test = True
                else:
                    self.logger.info("✅ Address is not exactly '123', proceeding with payment", 
                                   payment_id=payment_id, 
                                   delivery_address_clean=delivery_address_clean)
            else:
                self.logger.warning("⚠️ Order not found in database", payment_id=payment_id, order_id=order_id)
                
        except Exception as e:
            self.logger.error("Failed to check delivery address", payment_id=payment_id, order_id=order_id, error=str(e))
        
        # If it's a crash test, return failure immediately without affecting circuit breaker
        if is_crash_test:
            return False
        
        # Circuit breaker check (only for real payments, not crash tests)
        if not self.circuit_breaker.can_execute():
            self.logger.warning("⚡ Circuit breaker is open. Skipping payment provider call.", payment_id=payment_id)
            return False

        try:
            # The URL for the mock service endpoint
            mock_url = f"{os.getenv('PAYMENT_MOCK_URL', 'http://payment-mock:5003')}/api/v1/payments/process"
            self.logger.info(f"🌐 Making HTTP request to payment mock", payment_id=payment_id, url=mock_url)
            
            payload = {
                'order_id': payment['order_id'],
                'amount': payment['amount'],
                'card_details': '...sensitive data...'
            }
            self.logger.info(f"📦 Request payload prepared", payment_id=payment_id, payload=payload)
            
            response = requests.post(
                mock_url,
                json=payload,
                timeout=self.payment_timeout
            )
            
            self.logger.info(f"📨 HTTP response received", 
                           payment_id=payment_id, 
                           status_code=response.status_code, 
                           response_text=response.text[:200])
            
            if response.status_code == 200:
                self.logger.info("✅ Payment provider responded with success", payment_id=payment_id)
                self.circuit_breaker.record_success()
                return True
            else:
                self.logger.warning(
                    "❌ Payment provider returned error",
                    payment_id=payment_id,
                    status_code=response.status_code,
                    response=response.text
                )
                self.circuit_breaker.record_failure()
                return False
        except requests.exceptions.RequestException as e:
            self.logger.error("🚨 Payment provider request failed", payment_id=payment_id, error=str(e), exc_info=True)
            self.circuit_breaker.record_failure()
            return False
        except Exception as e:
            self.logger.error("🚨 Unexpected error in payment provider call", payment_id=payment_id, error=str(e), exc_info=True)
            self.circuit_breaker.record_failure()
            return False
    
    def record_payment_attempt(self, payment_id: str) -> int:
        """Record a new payment attempt and return its ID."""
        try:
            # The status is explicitly set to PENDING on creation
            result = self.db.execute_query("""
                INSERT INTO payment_attempts (payment_id, attempt_number, status)
                VALUES (
                    %s, 
                    (SELECT COALESCE(MAX(attempt_number), 0) + 1 FROM payment_attempts WHERE payment_id = %s),
                    'PENDING'
                )
                    RETURNING id
            """, (payment_id, payment_id), fetch='one')
                
            self.logger.info("Recorded new payment attempt", payment_id=payment_id, attempt_id=result['id'])
            return result['id']
                
        except Exception as e:
            self.logger.error("Failed to record payment attempt", error=str(e))
            raise
    
    def update_payment_attempt(self, attempt_id: int, success: bool, error: str = None):
        """Update a payment attempt after it has been processed."""
        try:
            status = 'SUCCESS' if success else 'FAILED'
            
            self.db.execute_query("""
                    UPDATE payment_attempts
                SET status = %s, error_message = %s, completed_at = CURRENT_TIMESTAMP
                    WHERE id = %s
            """, (status, error, attempt_id), fetch=None)
                
            self.logger.info("Updated payment attempt", attempt_id=attempt_id, status=status)
        except Exception as e:
            self.logger.error("Failed to update payment attempt", error=str(e))
            raise
    
    def get_payment_by_id(self, payment_id: str) -> Optional[Dict]:
        """Get payment by ID from database"""
        try:
            payments = self.db.execute_query(
                "SELECT * FROM payments WHERE id = %s",
                (payment_id,),
                fetch=True
            )
            return payments[0] if payments else None
        except Exception as e:
            self.logger.error("Failed to get payment by ID", payment_id=payment_id, error=str(e))
            raise
    
    def get_payment_by_order_id(self, order_id: str) -> Optional[Dict]:
        """Get payment by order ID"""
        try:
            payments = self.db.execute_query(
                "SELECT * FROM payments WHERE order_id = %s",
                (order_id,),
                fetch=True
            )
            return payments[0] if payments else None
        except Exception as e:
            self.logger.error("Failed to get payment by order ID", order_id=order_id, error=str(e))
            raise
    
    def get_payment_attempts(self, payment_id: str) -> List[Dict]:
        """Get payment attempts for a payment"""
        try:
            return self.db.execute_query(
                "SELECT * FROM payment_attempts WHERE payment_id = %s ORDER BY attempt_number",
                (payment_id,),
                fetch=True
            )
        except Exception as e:
            self.logger.error("Failed to get payment attempts", payment_id=payment_id, error=str(e))
            return []
    
    def update_payment_status(self, payment_id: str, status: str, failure_reason: str = None):
        """Update payment status"""
        try:
            with self.db.transaction():
                with self.db.get_cursor() as cursor:
                    cursor.execute("""
                        UPDATE payments
                        SET status = %s, failure_reason = %s, updated_at = CURRENT_TIMESTAMP
                        WHERE id = %s
                    """, (status, failure_reason, payment_id))
                
                self.logger.info("Payment status updated", payment_id=payment_id, status=status)
                
        except Exception as e:
            self.logger.error("Failed to update payment status", payment_id=payment_id, error=str(e))
            raise
    
    def publish_payment_success_event(self, payment_id: str):
        """Publish payment success event"""
        try:
            payment = self.get_payment_by_id(payment_id)
            if not payment:
                raise Exception(f"Payment {payment_id} not found")
            
            event_data = {
                'event_type': 'OrderPaid',
                'payment_id': payment_id,
                'order_id': payment['order_id'],
                'amount': payment['amount'],
                'payment_method': payment['payment_method'],
                'timestamp': self.get_timestamp()
            }
            
            success = self.events.publish_event('payment-events', event_data, payment['order_id'])
            
            if success:
                self.logger.info("Payment success event published", payment_id=payment_id)
            else:
                self.logger.error("Failed to publish payment success event", payment_id=payment_id)
                
        except Exception as e:
            self.logger.error("Failed to publish payment success event", payment_id=payment_id, error=str(e))
    
    def publish_payment_failure_event(self, payment_id: str):
        """Publish payment failure event"""
        try:
            payment = self.get_payment_by_id(payment_id)
            if not payment:
                raise Exception(f"Payment {payment_id} not found")
            
            event_data = {
                'event_type': 'PaymentFailed',
                'payment_id': payment_id,
                'order_id': payment['order_id'],
                'amount': payment['amount'],
                'payment_method': payment['payment_method'],
                'failure_reason': payment.get('failure_reason', 'Unknown error'),
                'timestamp': self.get_timestamp()
            }
            
            success = self.events.publish_event('payment-events', event_data, payment['order_id'])
            
            if success:
                self.logger.info("Payment failure event published", payment_id=payment_id)
            else:
                self.logger.error("Failed to publish payment failure event", payment_id=payment_id)
                
        except Exception as e:
            self.logger.error("Failed to publish payment failure event", payment_id=payment_id, error=str(e))
    
    def start_event_consumer(self):
        """Start Kafka event consumer in background thread"""
        def consume_events():
            self.logger.info("Starting event consumer for order events")
            
            while True:
                try:
                    self.events.process_events(
                        topics=['order-events'],
                        group_id='payment-service-group',
                        handler_func=self.handle_order_event,
                        max_messages=10
                    )
                    time.sleep(1)  # Small delay between polling
                except Exception as e:
                    self.logger.error("Event consumer error", error=str(e))
                    time.sleep(5)  # Wait before retrying
        
        consumer_thread = threading.Thread(target=consume_events, daemon=True)
        consumer_thread.start()
        self.logger.info("Event consumer thread started")
    
    def handle_order_event(self, topic: str, event_data: Dict, key: str):
        """Handle events from order service"""
        
        try:
            self.logger.info(
                "Событие из Kafka принято к обработке",
                raw_event=json.dumps(event_data)
            )
            event_type = event_data.get('eventType')
            order_id = event_data.get('orderId')
            
            self.logger.info("Received order event", event_type=event_type, order_id=order_id)
            
            if event_type == 'ORDER_CREATED':
                self.handle_order_created(event_data, order_id)
            else:
                self.logger.warning("Unknown event type", event_type=event_type)
        
        except Exception as e:
            self.logger.error("Failed to handle order event", error=str(e))
    
    def handle_order_created(self, event_data: Dict, order_id: str):
        """Handle OrderCreated event to initiate payment."""
        if not all(k in event_data for k in ['totalAmount', 'paymentMethod', 'userId']):
            self.logger.warning("Incomplete order data for payment", event_data=event_data)
            return
        
        amount = event_data['totalAmount']
        payment_method = event_data['paymentMethod']
        
        # Log delivery address for debugging
        delivery_address = event_data.get('deliveryAddress', {})
        self.logger.info("📍 Order delivery address", 
                order_id=order_id,
                        delivery_address=delivery_address)

        # Check for existing payment (idempotency)
        if self.get_payment_by_order_id(order_id):
            self.logger.info("Payment already initiated for order", order_id=order_id)
            return
        
        # Create payment record
        payment_id = generate_id('pay_')
        idempotency_key = self.generate_idempotency_key(order_id, amount, payment_method)
        
        payment_record = self.create_payment_record(
            payment_id=payment_id,
            order_id=order_id,
            amount=amount,
            payment_method=payment_method,
            idempotency_key=idempotency_key
        )
        
        # Start async payment processing (for ALL orders, not just crash tests)
        threading.Thread(
            target=self.process_payment_async,
            args=(payment_id,),
            daemon=True
        ).start()
        
        self.logger.info(
            "💳 Payment processing initiated from order event",
            payment_id=payment_id,
            order_id=order_id,
            message="Started async payment processing thread"
        )
        self.metrics.record_business_event('payment_initiated_from_event', 'success')
    
    def get_timestamp(self) -> str:
        """Get current timestamp in ISO format"""
        return datetime.now(timezone.utc).isoformat()


# ========================================
# Application Entry Point
# ========================================

if __name__ == '__main__':
    try:
        # Create and run service
        service = PaymentService()
        service.logger.info("💳 Starting Payment Service")
        
        # Run in debug mode if specified
        debug_mode = os.getenv('FLASK_DEBUG', 'false').lower() == 'true'
        service.run(debug=debug_mode)
        
    except KeyboardInterrupt:
        print("\n🛑 Payment Service stopped by user")
    except Exception as e:
        print(f"❌ Payment Service failed to start: {e}")
        sys.exit(1) 