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
from typing import Dict, List, Any, Optional
from flask import request, jsonify
from flask_cors import CORS
from datetime import datetime, timezone

# Add shared module to path
sys.path.insert(0, '/app/shared')

from base_service import BaseService, generate_id, validate_required_fields, ValidationError, retry_with_backoff


class OrderService(BaseService):
    """Order Service for managing pizza orders and Saga coordination"""
    
    def __init__(self):
        super().__init__('order-service')
        
        # Enable CORS for web UI
        CORS(self.app, origins=['*'])
        
        # Setup routes
        self.setup_routes()
        
        # Initialize database
        self.init_database_with_schema_creation('orders', 'SELECT 1')
        
        # Start event consumer in background thread
        self.start_event_consumer()
        
        self.logger.info("Order Service initialized")
    

    
    def setup_routes(self):
        """Setup API routes for order service"""
        
        @self.app.route('/api/v1/orders', methods=['POST'])
        def create_order():
            """Create new pizza order with Outbox Pattern"""
            try:
                data = request.get_json()
                
                # Validate required fields
                required_fields = ['items', 'deliveryAddress', 'paymentMethod']
                missing_fields = validate_required_fields(data, required_fields)
                
                if missing_fields:
                    raise ValidationError(f"Missing required fields: {', '.join(missing_fields)}")
                
                # Validate items
                if not data['items'] or len(data['items']) == 0:
                    raise ValidationError("Order must contain at least one item")
                
                # Generate order ID
                order_id = generate_id('order_')
                user_id = data.get('userId', 'anonymous')
                
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
                    payment_method=data['paymentMethod']
                )
                
                self.logger.info(
                    "Order created",
                    order_id=order_id,
                    user_id=user_id,
                    total_amount=total_amount,
                    items_count=len(data['items'])
                )
                
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
            """Get order details by ID"""
            try:
                order = self.get_order_by_id(order_id)
                
                if not order:
                    return jsonify({
                        'success': False,
                        'error': 'Order not found'
                    }), 404
                
                # Get order items
                order_items = self.get_order_items(order_id)
                order['items'] = order_items
                
                self.logger.info("Order retrieved", order_id=order_id)
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
                    'error': 'Failed to retrieve order'
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
                
                self.logger.info(
                    "Order status updated",
                    order_id=order_id,
                    new_status=new_status,
                    reason=reason
                )
                
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
    
    def get_pizza_details(self, items: List[Dict]) -> List[Dict]:
        """Get pizza details from Frontend Service"""
        try:
            import requests
            
            frontend_url = os.getenv('FRONTEND_SERVICE_URL', 'http://frontend-service:5000')
            pizza_details = []
            
            for item in items:
                pizza_id = item.get('pizzaId')
                quantity = item.get('quantity', 1)
                
                if not pizza_id:
                    raise ValidationError("Pizza ID is required for each item")
                
                # Get pizza from Frontend Service
                response = requests.get(f"{frontend_url}/api/v1/menu/{pizza_id}", timeout=10)
                
                if response.status_code == 404:
                    raise ValidationError(f"Pizza not found: {pizza_id}")
                elif response.status_code != 200:
                    raise Exception(f"Failed to get pizza details for {pizza_id}")
                
                pizza_data = response.json()
                if not pizza_data.get('success'):
                    raise Exception(f"Invalid response for pizza {pizza_id}")
                
                pizza = pizza_data['pizza']
                pizza_details.append({
                    'pizza_id': pizza_id,
                    'pizza_name': pizza['name'],
                    'pizza_price': pizza['price'],
                    'quantity': quantity,
                    'subtotal': pizza['price'] * quantity
                })
            
            return pizza_details
            
        except requests.RequestException as e:
            self.logger.error("Failed to connect to Frontend Service", error=str(e))
            raise Exception("Unable to validate pizza items")
        except Exception as e:
            self.logger.error("Failed to get pizza details", error=str(e))
            raise
    
    def calculate_total(self, pizza_details: List[Dict]) -> int:
        return sum(item['pizza_price'] * item['quantity'] for item in pizza_details)
    
    def create_order_with_outbox(self, order_id: str, user_id: str, items: List[Dict], 
                                pizza_details: List[Dict], total_amount: int,
                                delivery_address: str, payment_method: str) -> Dict:
        """Create order and outbox event in a single transaction"""
        with self.db.transaction():
            with self.db.get_cursor() as cursor:
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

                # 3. Create Outbox Event - минимальные данные для избежания больших сообщений
                simplified_items = [
                    {
                        'pizzaId': item.get('pizzaId'),
                        'quantity': item.get('quantity', 1)
                    }
                    for item in items
                ]
                
                event_data = {
                    'event_type': 'OrderCreated',
                    'orderId': order_id,
                    'userId': user_id,
                    'totalAmount': total_amount,
                    'itemsCount': len(items),
                    'items': simplified_items,
                    'paymentMethod': payment_method,
                    'deliveryAddress': delivery_address,
                    'timestamp': self.get_timestamp()
                }

                cursor.execute("""
                    INSERT INTO orders.outbox_events (aggregate_id, event_type, event_data)
                    VALUES (%s, %s, %s::jsonb)
                """, (order_id, 'OrderCreated', json.dumps(event_data)))
                
                self.logger.info(
                    "📤 Event added to outbox",
                    event_type='OrderCreated',
                    order_id=order_id,
                    outbox_event="OrderCreated event queued for publishing"
                )

        return {'id': order_id, 'status': 'PENDING', 'total': total_amount}
    
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

    def update_order_status_internal(self, order_id: str, new_status: str, reason: str = '') -> bool:
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
                    'timestamp': self.get_timestamp()
                }

                cursor.execute("""
                    INSERT INTO orders.outbox_events (aggregate_id, event_type, event_data)
                    VALUES (%s, %s, %s::jsonb)
                """, (order_id, 'OrderStatusChanged', json.dumps(event_data)))
                
                self.logger.info(
                    "📤 OrderStatusChanged event added to outbox",
                    order_id=order_id,
                    new_status=new_status,
                    reason=reason,
                    outbox_event="Status change event queued for publishing"
                )
        
        return True
    
    def start_event_consumer(self):
        """Start a background thread to consume Kafka events"""
        def consume_events():
            self.logger.info("🔄 Starting event consumer for payment events")
            
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
        self.logger.info("Event consumer thread started")
    
    def handle_payment_event(self, topic: str, event_data: Dict, key: str):
        """Handle payment events (OrderPaid, PaymentFailed)"""
        try:
            event_type = event_data.get('event_type')
            order_id = event_data.get('order_id')
            
            if not order_id:
                self.logger.warning("Payment event missing order_id", event_data=event_data)
                return
            
            self.logger.info(
                "📥 Received new payment event from Kafka",
                event_type=event_type,
                order_id=order_id,
                message="Processing payment event from payment-events topic"
            )
            
            if event_type == 'OrderPaid':
                self.handle_order_paid(order_id, event_data)
            elif event_type == 'PaymentFailed':
                self.handle_payment_failed(order_id, event_data)
            else:
                self.logger.warning("Unknown payment event type", event_type=event_type)
            
            self.metrics.record_business_event('payment_event_processed', 'success')
            
        except Exception as e:
            self.logger.error("Failed to handle payment event", error=str(e), event_data=event_data)
            self.metrics.record_business_event('payment_event_processed', 'failed')
    
    def handle_order_paid(self, order_id: str, event_data: Dict):
        """Handle successful payment"""
        try:
            self.update_order_status_internal(order_id, 'PAID', 'Payment successful')
            
            # Update saga state
            with self.db.transaction():
                with self.db.get_cursor() as cursor:
                    cursor.execute("""
                        UPDATE order_saga_state 
                        SET current_step = 'payment_processed',
                            steps_completed = array_append(steps_completed, 'payment_processed'),
                            updated_at = CURRENT_TIMESTAMP
                        WHERE order_id = %s
                    """, (order_id,))
            
            self.logger.info("Order marked as PAID", order_id=order_id)
            
        except Exception as e:
            self.logger.error("Failed to handle order paid", order_id=order_id, error=str(e))
    
    def handle_payment_failed(self, order_id: str, event_data: Dict):
        """Handle failed payment"""
        try:
            failure_reason = event_data.get('failure_reason', 'Payment processing failed')
            self.update_order_status_internal(order_id, 'FAILED', failure_reason)
            
            # Update saga state for failure
            with self.db.transaction():
                with self.db.get_cursor() as cursor:
                    cursor.execute("""
                        UPDATE order_saga_state 
                        SET current_step = 'failed',
                            compensation_needed = true,
                            updated_at = CURRENT_TIMESTAMP
                        WHERE order_id = %s
                    """, (order_id,))
            
            self.logger.info("Order marked as FAILED", order_id=order_id, reason=failure_reason)
            
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