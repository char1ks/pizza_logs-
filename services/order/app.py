"""
Pizza Order System - Order Service
Event-Driven Saga Architecture

Manages order creation, status updates, and implements Outbox Pattern
"""

import os
import sys
import json
import threading
import time
import uuid
import hashlib
from typing import Dict, List, Any, Optional
from flask import request, jsonify
from flask_cors import CORS
from datetime import datetime, timezone
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# Add shared module to path
sys.path.insert(0, '/app/shared')

from base_service import BaseService, generate_id, validate_required_fields, ValidationError, retry_with_backoff, format_order_status_message


class OrderService(BaseService):
    """Order Service for managing pizza orders and Saga coordination"""
    
    def __init__(self):
        super().__init__('order-service')
        
        # Enable CORS for web UI
        CORS(self.app, origins=['*'])
        
        # Initialize HTTP session with connection pooling
        self.http_session = self._create_http_session()
        # Simple menu cache to avoid per-item fetches
        self._menu_cache = {
            'data': None,
            'expires_at': 0
        }
        # Pre-warm menu cache to avoid thundering herd on first requests
        try:
            _ = self._get_menu_catalog()
            self.logger.info("Menu cache pre-warmed")
        except Exception as e:
            self.logger.warning("Menu cache pre-warm failed", error=str(e))
        
        # Setup routes
        self.setup_routes()
        
        # Initialize database
        self.init_database_with_schema_creation('orders', 'SELECT 1')
        self.db.default_schema = 'orders'
        self.create_tables_if_not_exist()
        
        # Start event consumer in background thread
        self.start_event_consumer()
        
        self.logger.info("Order Service initialized")
    
    def _create_http_session(self):
        """Create HTTP session with connection pooling and retry strategy"""
        session = requests.Session()
        
        # Configure retry strategy
        retry_strategy = Retry(
            total=3,
            backoff_factor=1,
            status_forcelist=[429, 500, 502, 503, 504],
        )
        
        # Configure adapter with connection pooling
        adapter = HTTPAdapter(
            pool_connections=10,
            pool_maxsize=20,
            max_retries=retry_strategy
        )
        
        session.mount("http://", adapter)
        session.mount("https://", adapter)
        
        return session

    def _get_menu_catalog(self) -> Dict[str, Dict]:
        """Fetch full menu once and cache it for a short TTL"""
        frontend_url = os.getenv('FRONTEND_SERVICE_URL', 'http://frontend-service:5000')
        now = time.time()
        ttl = int(os.getenv('MENU_CACHE_TTL', '30'))
        if self._menu_cache['data'] and self._menu_cache['expires_at'] > now:
            return self._menu_cache['data']

        # Fetch full menu
        resp = self.http_session.get(f"{frontend_url}/api/v1/menu", timeout=10)
        if resp.status_code != 200:
            raise Exception("Failed to fetch menu catalog")
        payload = resp.json()
        if not payload.get('success'):
            raise Exception("Invalid response from Frontend Service menu")
        pizzas = payload.get('pizzas', [])
        # Index by pizza id
        catalog = {p.get('id'): p for p in pizzas if p.get('id')}
        self._menu_cache['data'] = catalog
        self._menu_cache['expires_at'] = now + ttl
        return catalog


    
    def setup_routes(self):
        """Setup API routes for order service"""
        
        @self.app.route('/api/v1/orders', methods=['POST'])
        def create_order():
            """Create new pizza order with Outbox Pattern"""
            try:
                data = request.get_json()
                
                order_id = generate_id('order_')
                user_id = data.get('userId', 'anonymous')
                
                # Generate correlation ID for tracing
                correlation_id = generate_id('corr_')
                
                self.logger.info(
                    "🍕 order-service принял заказ в обработку",
                    order_id=order_id,
                    correlation_id=correlation_id,
                    stage="order_processing_started",
                    service="order-service"
                )
                
                # Validate required fields
                required_fields = ['items', 'deliveryAddress', 'paymentMethod']
                missing_fields = validate_required_fields(data, required_fields)
                
                if missing_fields:
                    self.logger.error(
                        "🍕 ЗАКАЗ ПИЦЦЫ: Ошибка валидации",
                        order_id=order_id,
                        correlation_id=correlation_id,
                        stage="validation_failed",
                        error=f"Missing fields: {', '.join(missing_fields)}",
                        service="order-service"
                    )
                    raise ValidationError(f"Missing required fields: {', '.join(missing_fields)}")
                
                # Validate items
                if not data['items'] or len(data['items']) == 0:
                    self.logger.error(
                        "🍕 ЗАКАЗ ПИЦЦЫ: Пустой заказ",
                        order_id=order_id,
                        correlation_id=correlation_id,
                        stage="validation_failed",
                        error="No items in order",
                        service="order-service"
                    )
                    raise ValidationError("Order must contain at least one item")
                
                # Get pizza details from Frontend Service
                pizza_details = self.get_pizza_details(data['items'])
                total_amount = self.calculate_total(pizza_details)
                
                # Create order using transaction with Outbox Pattern
                order_data = self.create_order_with_outbox(
                    order_id=order_id,
                    user_id=user_id,
                    items=data['items'],
                    pizza_details=pizza_details,
                    total_amount=total_amount,
                    delivery_address=data['deliveryAddress'],
                    payment_method=data['paymentMethod'],
                    force_fail=data.get('forceFail', False), # Pass forceFail from request
                    correlation_id=correlation_id
                )
                
                # Log user-friendly message
                status_message = format_order_status_message(
                    order_id=order_id,
                    status='PENDING',
                    service='order-service',
                    items_count=len(data['items']),
                    total_amount=total_amount
                )
                self.logger.info(status_message, order_id=order_id, correlation_id=correlation_id)
                
                self.metrics.record_business_event('order_created', 'success')
                
                return jsonify({
                    'success': True,
                    'orderId': order_id,
                    'status': 'PENDING',
                    'total': total_amount,
                    'timestamp': self.get_timestamp()
                }), 202  # Accepted - processing asynchronously
                
            except ValidationError as e:
                self.logger.warning("Order validation failed", error=str(e))
                return jsonify({
                    'success': False,
                    'error': 'Validation error',
                    'message': str(e)
                }), 400
                
            except Exception as e:
                self.logger.error("Failed to create order", error=str(e))
                self.metrics.record_business_event('order_created', 'failed')
                
                return jsonify({
                    'success': False,
                    'error': 'Failed to create order',
                    'message': str(e)
                }), 500
        
        @self.app.route('/api/v1/orders/<order_id>', methods=['GET'])
        def get_order(order_id: str):
            """Get order by ID"""
            try:
                order = self.db.execute_query(
                    "SELECT * FROM orders.orders WHERE id = %s",
                    (order_id,),
                    fetch='one'
                )
                
                if not order:
                    return jsonify({
                        'success': False,
                        'error': 'Order not found'
                    }), 404
                
                self.metrics.record_business_event('order_retrieved', 'success')
                
                return jsonify({
                    'success': True,
                    'order': order,
                    'timestamp': self.get_timestamp()
                })
                
            except Exception as e:
                self.logger.error("Failed to get order", order_id=order_id, error=str(e))
                self.metrics.record_business_event('order_retrieved', 'failed')
                
                return jsonify({
                    'success': False,
                    'error': 'Failed to get order'
                }), 500
        
        @self.app.route('/api/v1/orders', methods=['GET'])
        def list_orders():
            """List orders with pagination and filtering"""
            try:
                # Get query parameters
                user_id = request.args.get('userId')
                status = request.args.get('status')
                limit = int(request.args.get('limit', '50'))
                offset = int(request.args.get('offset', '0'))
                
                orders = self.list_orders_with_filters(user_id, status, limit, offset)
                
                self.logger.info(
                    "Orders listed",
                    count=len(orders),
                    user_id=user_id,
                    status=status
                )
                
                return jsonify({
                    'success': True,
                    'orders': orders,
                    'limit': limit,
                    'offset': offset,
                    'timestamp': self.get_timestamp()
                })
                
            except Exception as e:
                self.logger.error("Failed to list orders", error=str(e))
                
                return jsonify({
                    'success': False,
                    'error': 'Failed to list orders'
                }), 500
        
        @self.app.route('/api/v1/orders/<order_id>/status', methods=['PUT'])
        def update_order_status(order_id: str):
            """Update order status (internal API)"""
            try:
                data = request.get_json()
                new_status = data.get('status')
                reason = data.get('reason', '')
                
                if not new_status:
                    raise ValidationError("Status is required")
                
                # Valid status transitions
                valid_statuses = ['PENDING', 'PROCESSING', 'PAID', 'FAILED', 'COMPLETED']
                if new_status not in valid_statuses:
                    raise ValidationError(f"Invalid status. Must be one of: {valid_statuses}")
                
                success = self.update_order_status_internal(order_id, new_status, reason)
                
                if not success:
                    return jsonify({
                        'success': False,
                        'error': 'Order not found'
                    }), 404
                
                # Log user-friendly status change message
                status_message = format_order_status_message(
                    order_id=order_id,
                    status=new_status,
                    service='order-service',
                    reason=reason
                )
                self.logger.info(status_message, order_id=order_id)
                
                return jsonify({
                    'success': True,
                    'message': 'Order status updated'
                })
                
            except ValidationError as e:
                self.logger.warning("Order status update validation failed", error=str(e))
                return jsonify({
                    'success': False,
                    'error': 'Validation error',
                    'message': str(e)
                }), 400
                
            except Exception as e:
                self.logger.error("Failed to update order status", order_id=order_id, error=str(e))
                
                return jsonify({
                    'success': False,
                    'error': 'Failed to update order status'
                }), 500

    def create_tables_if_not_exist(self):
        """Create database tables if they don't exist"""
        try:
            with self.db.transaction() as conn:
                with conn.cursor() as cursor:
                    # Events processed table
                    cursor.execute(
                        """
                        CREATE TABLE IF NOT EXISTS orders.events_processed (
                            event_id VARCHAR(100) PRIMARY KEY,
                            topic VARCHAR(100),
                            partition INTEGER,
                            "offset" BIGINT,
                            consumed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                        )
                        """
                    )
                    self.logger.debug("Table orders.events_processed verified/created")
                    
                    # Orders table
                    cursor.execute(
                        """
                        CREATE TABLE IF NOT EXISTS orders.orders (
                            id VARCHAR(50) PRIMARY KEY,
                            user_id VARCHAR(50) NOT NULL,
                            status VARCHAR(20) DEFAULT 'PENDING',
                            total INTEGER NOT NULL,
                            delivery_address TEXT NOT NULL,
                            payment_method VARCHAR(50),
                            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                        )
                        """
                    )
                    self.logger.debug("Table orders.orders verified/created")
                    
                    # Order items table
                    cursor.execute(
                        """
                        CREATE TABLE IF NOT EXISTS orders.order_items (
                            id SERIAL PRIMARY KEY,
                            order_id VARCHAR(50) REFERENCES orders.orders(id),
                            pizza_id VARCHAR(50) NOT NULL,
                            pizza_name VARCHAR(100) NOT NULL,
                            pizza_price INTEGER NOT NULL,
                            quantity INTEGER NOT NULL DEFAULT 1,
                            subtotal INTEGER NOT NULL,
                            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                        )
                        """
                    )
                    self.logger.debug("Table orders.order_items verified/created")

                    cursor.execute(
                        """
                        CREATE TABLE IF NOT EXISTS orders.order_saga_state (
                            order_id VARCHAR(50) PRIMARY KEY,
                            current_step VARCHAR(50) NOT NULL,
                            steps_completed TEXT[] DEFAULT ARRAY[]::TEXT[],
                            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                        )
                        """
                    )
                    self.logger.debug("Table orders.order_saga_state verified/created")
                    
                    # Outbox events table
                    cursor.execute(
                        """
                        CREATE TABLE IF NOT EXISTS orders.outbox_events (
                            id SERIAL PRIMARY KEY,
                            aggregate_id VARCHAR(50) NOT NULL,
                            event_type VARCHAR(50) NOT NULL,
                            event_data JSONB NOT NULL,
                            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                            processed_at TIMESTAMP,
                            status VARCHAR(20) DEFAULT 'PENDING'
                        )
                        """
                    )
                    self.logger.debug("Table orders.outbox_events verified/created")
            self.logger.info("Database tables verified/created successfully")
        except Exception as e:
            self.logger.error("Failed to create database tables", error=str(e))
            sys.exit(1)

    def get_pizza_details(self, items: List[Dict]) -> List[Dict]:
        """Get pizza details using cached catalog to avoid N network calls"""
        try:
            catalog = self._get_menu_catalog()
            pizza_details = []
            for item in items:
                pizza_id = item.get('pizzaId')
                quantity = item.get('quantity', 1)
                if not pizza_id:
                    raise ValidationError("Pizza ID is required for each item")
                pizza = catalog.get(pizza_id)
                if not pizza:
                    raise ValidationError(f"Pizza not found: {pizza_id}")
                price = pizza.get('price')
                name = pizza.get('name')
                pizza_details.append({
                    'pizza_id': pizza_id,
                    'pizza_name': name,
                    'pizza_price': price,
                    'quantity': quantity,
                    'subtotal': price * quantity
                })
            return pizza_details
        except Exception as e:
            self.logger.error("Failed to get pizza details", error=str(e))
            raise
    
    def calculate_total(self, pizza_details: List[Dict]) -> int:
        return sum(item['pizza_price'] * item['quantity'] for item in pizza_details)
    
    def create_order_with_outbox(self, order_id: str, user_id: str, items: List[Dict], 
                                pizza_details: List[Dict], total_amount: int,
                                delivery_address: str, payment_method: str, force_fail: bool = False, correlation_id: str = None) -> Dict:
        """Create order and outbox event in a single transaction"""
        with self.db.transaction() as conn:
            with conn.cursor() as cursor:
                # 1. Create Order
                cursor.execute("""
                    INSERT INTO orders.orders (id, user_id, status, total, delivery_address, payment_method)
                    VALUES (%s, %s, %s, %s, %s, %s)
                """, (
                    order_id,
                    user_id,
                    'PENDING',
                    total_amount,
                    delivery_address,
                    payment_method
                ))
                
                # 2. Create Order Items
                order_items_to_insert = []
                for item in items:
                    detail = next((p for p in pizza_details if p['pizza_id'] == item['pizzaId']), None)
                    if detail:
                        subtotal = detail['pizza_price'] * item['quantity']
                        order_items_to_insert.append((
                            order_id,
                            detail['pizza_id'],
                            detail['pizza_name'],
                            detail['pizza_price'],
                            item['quantity'],
                            subtotal
                        ))

                cursor.executemany("""
                    INSERT INTO orders.order_items (order_id, pizza_id, pizza_name, pizza_price, quantity, subtotal)
                    VALUES (%s, %s, %s, %s, %s, %s)
                """, order_items_to_insert)

                # Initialize saga state
                cursor.execute("""
                    INSERT INTO orders.order_saga_state (order_id, current_step, steps_completed)
                    VALUES (%s, 'created', ARRAY['created'])
                    ON CONFLICT (order_id) DO NOTHING
                """, (order_id,))

                # 3. Create Outbox Event - минимальные данные для избежания больших сообщений
                simplified_items = [
                    {
                        'pizzaId': item.get('pizzaId'),
                        'quantity': item.get('quantity', 1)
                    }
                    for item in items
                ]
                
                # Use provided correlation ID or generate new one
                if not correlation_id:
                    correlation_id = generate_id('corr_')
                
                payment_id = f"pay_{uuid.uuid4().hex}"
                idempotency_key = hashlib.sha256(f"{order_id}:{total_amount}:{payment_method}".encode()).hexdigest()
                cursor.execute("""
                    INSERT INTO payments.payments (id, order_id, amount, payment_method, status, idempotency_key)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    ON CONFLICT (order_id) DO NOTHING
                """, (payment_id, order_id, total_amount, payment_method, 'PENDING', idempotency_key))
                
                event_data = {
                    'event_type': 'OrderCreated',
                    'orderId': order_id,
                    'userId': user_id,
                    'totalAmount': total_amount,
                    'itemsCount': len(items),
                    'items': simplified_items,
                    'paymentMethod': payment_method,
                    'deliveryAddress': delivery_address,
                    'timestamp': self.get_timestamp(),
                    'forceFail': force_fail,
                    'correlationId': correlation_id,
                    'paymentId': payment_id
                }

                cursor.execute("""
                    INSERT INTO orders.outbox_events (aggregate_id, event_type, event_data)
                    VALUES (%s, %s, %s::jsonb)
                """, (order_id, 'OrderCreated', json.dumps(event_data)))
                
                self.logger.debug(
                    "📤 Event added to outbox",
                    event_type='OrderCreated',
                    order_id=order_id,
                    correlation_id=correlation_id,
                    outbox_event="OrderCreated event queued for publishing"
                )

        return {'id': order_id, 'status': 'PENDING', 'total': total_amount, 'correlationId': correlation_id}
    
    def get_order_by_id(self, order_id: str) -> Optional[Dict]:
        """Get order by ID from database"""
        return self.db.execute_query(
            "SELECT * FROM orders.orders WHERE id = %s",
            (order_id,),
            fetch='one'
        )

    def get_order_items(self, order_id: str) -> List[Dict]:
        """Get order items by order ID"""
        return self.db.execute_query(
            "SELECT * FROM orders.order_items WHERE order_id = %s",
            (order_id,),
            fetch='all'
        )
    
    def list_orders_with_filters(self, user_id: str = None, status: str = None, 
                                limit: int = 50, offset: int = 0) -> List[Dict]:
        """List orders with optional filters"""
        query = "SELECT * FROM orders.orders WHERE 1=1"
        params = []
        
        if user_id:
            query += " AND user_id = %s"
            params.append(user_id)
            
        if status:
            query += " AND status = %s"
            params.append(status)
            
        query += " ORDER BY created_at DESC LIMIT %s OFFSET %s"
        params.extend([limit, offset])
        
        return self.db.execute_query(query, tuple(params), fetch='all')

    def update_order_status_internal(self, order_id: str, new_status: str, reason: str = '', correlation_id: Optional[str] = None) -> bool:
        """Update order status and create outbox event"""
        with self.db.transaction():
            with self.db.get_cursor() as cursor:
                # Update order status
                cursor.execute(
                    "UPDATE orders.orders SET status = %s, updated_at = CURRENT_TIMESTAMP WHERE id = %s",
                    (new_status, order_id)
                )
                
                if cursor.rowcount == 0:
                    return False
                    
                # Create outbox event
                event_data = {
                    'event_type': 'OrderStatusChanged',
                    'orderId': order_id,
                    'newStatus': new_status,
                    'reason': reason,
                    'timestamp': self.get_timestamp(),
                    'correlationId': correlation_id
                }

                cursor.execute("""
                    INSERT INTO orders.outbox_events (aggregate_id, event_type, event_data)
                    VALUES (%s, %s, %s::jsonb)
                """, (order_id, 'OrderStatusChanged', json.dumps(event_data)))
                
                self.logger.debug(
                    "📤 OrderStatusChanged event added to outbox",
                    order_id=order_id,
                    correlation_id=correlation_id,
                    new_status=new_status,
                    reason=reason,
                    outbox_event="Status change event queued for publishing"
                )
        
        return True
    
    def start_event_consumer(self):
        """Start a background thread to consume Kafka events"""
        def consume_events():
            while True:
                try:
                    self.logger.debug("📡 POLLING payment-events topic for new messages...")
                    self.events.process_events(
                        topics=['payment-events'],
                        group_id='order-service-group',
                        handler_func=self.handle_payment_event,
                        max_messages=10
                    )
                    time.sleep(1)  # Small delay between polling
                except Exception as e:
                    self.logger.error("Event consumer error", error=str(e))
                    time.sleep(5)  # Wait before retrying
        
        consumer_thread = threading.Thread(target=consume_events, daemon=True)
        consumer_thread.start()
    
    def handle_payment_event(self, topic: str, event_data: Dict, key: str):
        """Handle payment events (OrderPaid, PaymentFailed)"""
        try:
            event_type = event_data.get('event_type')
            order_id = event_data.get('order_id')
            
            correlation_id = event_data.get('correlationId')
            event_id = event_data.get('event_id')
            if event_id:
                existing = self.db.execute_query(
                    "SELECT 1 FROM orders.events_processed WHERE event_id = %s",
                    (event_id,),
                    fetch='one'
                )
                if existing:
                    self.logger.debug("Skipping already processed event", event_id=event_id)
                    return
            
            self.logger.info(
                "📨 order-service вычитал сообщение из топика о платеже",
                order_id=order_id,
                correlation_id=correlation_id,
                event_type=event_type,
                topic=topic,
                stage="kafka_event_consumed",
                service="order-service"
            )
            
            if not order_id:
                self.logger.warning("Payment event missing order_id", event_data=event_data)
                return
            
            if event_type == 'OrderPaid':
                self.handle_order_paid(order_id, event_data)
            elif event_type == 'PaymentFailed':
                self.handle_payment_failed(order_id, event_data)
            else:
                self.logger.warning("Unknown payment event type", event_type=event_type)
            
            self.metrics.record_business_event('payment_event_processed', 'success')
            if event_id:
                try:
                    with self.db.transaction():
                        with self.db.get_cursor() as cursor:
                            cursor.execute(
                                """
                                INSERT INTO orders.events_processed (event_id, topic, partition, "offset")
                                VALUES (%s, %s, %s, %s)
                                ON CONFLICT (event_id) DO NOTHING
                                """,
                                (event_id, topic, None, None)
                            )
                except Exception:
                    pass
            
        except Exception as e:
            self.logger.error("Failed to handle payment event", error=str(e), event_data=event_data)
            self.metrics.record_business_event('payment_event_processed', 'failed')
    
    def handle_order_paid(self, order_id: str, event_data: Dict):
        """Handle successful payment"""
        try:
            correlation_id = event_data.get('correlationId')
            self.update_order_status_internal(order_id, 'PAID', 'Payment successful', correlation_id=correlation_id)
            
            # Update saga state
            with self.db.transaction():
                with self.db.get_cursor() as cursor:
                    cursor.execute("""
                        UPDATE orders.order_saga_state 
                        SET current_step = 'payment_processed',
                            steps_completed = array_append(COALESCE(steps_completed, ARRAY[]::TEXT[]), 'payment_processed'),
                            updated_at = CURRENT_TIMESTAMP
                        WHERE order_id = %s
                    """, (order_id,))
            
            # Log user-friendly payment success message
            status_message = format_order_status_message(
                order_id=order_id,
                status='PAID',
                service='order-service'
            )
            self.logger.info(status_message, order_id=order_id, correlation_id=correlation_id)
            
            self.logger.info(
                "✅ order-service перевёл заказ в статус PAID",
                order_id=order_id,
                correlation_id=correlation_id,
                stage="order_status_paid",
                service="order-service"
            )
            
            self.logger.info(
                "📤 order-service отдал информацию в UI о смене статуса",
                order_id=order_id,
                correlation_id=correlation_id,
                stage="ui_notification_sent",
                service="order-service"
            )
            
        except Exception as e:
            self.logger.error("Failed to handle order paid", order_id=order_id, error=str(e))
    
    def handle_payment_failed(self, order_id: str, event_data: Dict):
        """Handle failed payment"""
        try:
            failure_reason = event_data.get('failure_reason', 'Payment processing failed')
            correlation_id = event_data.get('correlationId')
            self.update_order_status_internal(order_id, 'FAILED', failure_reason, correlation_id=correlation_id)
            
            # Update saga state for failure
            with self.db.transaction():
                with self.db.get_cursor() as cursor:
                    cursor.execute("""
                        UPDATE orders.order_saga_state 
                        SET current_step = 'failed',
                            compensation_needed = true,
                            updated_at = CURRENT_TIMESTAMP
                        WHERE order_id = %s
                    """, (order_id,))
            
            # Log user-friendly payment failure message
            status_message = format_order_status_message(
                order_id=order_id,
                status='FAILED',
                service='order-service',
                reason=failure_reason
            )
            self.logger.info(status_message, order_id=order_id, correlation_id=correlation_id)
            
        except Exception as e:
            self.logger.error("Failed to handle payment failed", order_id=order_id, error=str(e))
    
    def get_timestamp(self) -> str:
        """Get current timestamp in ISO format"""
        return datetime.now(timezone.utc).isoformat()


# ========================================
# Application Entry Point
# ========================================

if __name__ == '__main__':
    try:
        # Create and run service
        service = OrderService()
        service.logger.info("📦 Starting Order Service")
        
        # Run in debug mode if specified
        debug_mode = os.getenv('FLASK_DEBUG', 'false').lower() == 'true'
        service.run(debug=debug_mode)
        
    except KeyboardInterrupt:
        print("\n🛑 Order Service stopped by user")
    except Exception as e:
        print(f"❌ Order Service failed to start: {e}")
        sys.exit(1)