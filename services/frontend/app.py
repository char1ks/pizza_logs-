"""
Pizza Order System - Frontend Service
Event-Driven Saga Architecture

Manages pizza menu and serves as API gateway for catalog
"""

import os
import sys
import time
from typing import Dict, List, Any
from flask import request, jsonify
from flask_cors import CORS
import subprocess
import json

# Add shared module to path
sys.path.insert(0, '/app/shared')

from base_service import BaseService, generate_id, validate_required_fields, ValidationError


class FrontendService(BaseService):
    """Frontend Service for pizza menu management"""
    
    def __init__(self):
        super().__init__('frontend-service')
        
        # Enable CORS for web UI
        CORS(self.app, origins=['*'])
        
        # Setup routes
        self.setup_routes()
        
        # Initialize database if needed
        self.init_database_with_schema_creation('frontend', 'SELECT 1')
        
        self.logger.info("Frontend Service initialized")
    

    
    def create_sample_data(self):
        """Create sample pizza data if the table is empty."""
        try:
            with self.db.transaction():
                # Insert sample pizzas
                sample_pizzas = [
                    {
                        'id': 'margherita',
                        'name': 'Маргарита',
                        'description': 'Классическая пицца с томатным соусом, моцареллой и базиликом',
                        'price': 59900,  # 599 руб in cents
                        'image_url': '/images/margherita.jpg',
                        'ingredients': ['томатный соус', 'моцарелла', 'базилик'],
                        'available': True
                    },
                    {
                        'id': 'pepperoni',
                        'name': 'Пепперони',
                        'description': 'Острая пицца с пепперони и сыром моцарелла',
                        'price': 69900,  # 699 руб in cents
                        'image_url': '/images/pepperoni.jpg',
                        'ingredients': ['томатный соус', 'моцарелла', 'пепперони'],
                        'available': True
                    },
                    {
                        'id': 'quattro-formaggi',
                        'name': 'Четыре сыра',
                        'description': 'Изысканная пицца с четырьмя видами сыра',
                        'price': 79900,  # 799 руб in cents
                        'image_url': '/images/quattro-formaggi.jpg',
                        'ingredients': ['соус белый', 'моцарелла', 'горгонзола', 'пармезан', 'рикотта'],
                        'available': True
                    }
                ]
                
                with self.db.get_cursor() as cursor:
                    cursor.execute("SET search_path TO frontend, public")
                    # Check if pizzas already exist
                    cursor.execute("SELECT COUNT(*) FROM frontend.pizzas")
                    if cursor.fetchone()[0] > 0:
                        return

                    for pizza in sample_pizzas:
                        cursor.execute("""
                            INSERT INTO frontend.pizzas (id, name, description, price, image_url, ingredients, available)
                            VALUES (%s, %s, %s, %s, %s, %s, %s)
                            ON CONFLICT (id) DO NOTHING
                        """, (
                            pizza['id'],
                            pizza['name'],
                            pizza['description'],
                            pizza['price'],
                            pizza['image_url'],
                            pizza['ingredients'],
                            pizza['available']
                        ))
                
        except Exception as e:
            self.logger.error("Failed to create sample data", error=str(e))
    
    def setup_routes(self):
        """Setup API routes for frontend service"""
        
        @self.app.route('/api/v1/menu', methods=['GET'])
        def get_menu():
            """Get pizza menu with optional filtering"""
            try:
                # Get query parameters
                available_only = request.args.get('available', 'true').lower() == 'true'
                category = request.args.get('category')
                
                # Build query
                query = "SELECT * FROM frontend.pizzas"
                params = []
                
                if available_only:
                    query += " WHERE available = %s"
                    params.append(True)
                
                query += " ORDER BY name"
                
                # Execute query
                pizzas = self.db.execute_query(query, tuple(params), fetch='all')
                
                # Record business metrics
                self.metrics.record_business_event('menu_request', 'success')
                
                return jsonify({
                    'success': True,
                    'pizzas': pizzas,
                    'total': len(pizzas),
                    'timestamp': self.get_timestamp()
                })
                
            except Exception as e:
                self.logger.error("Failed to get menu", error=str(e))
                self.metrics.record_business_event('menu_request', 'failed')
                
                return jsonify({
                    'success': False,
                    'error': 'Failed to load menu',
                    'message': str(e)
                }), 500
        
        @self.app.route('/api/v1/menu/<pizza_id>', methods=['GET'])
        def get_pizza(pizza_id: str):
            """Get specific pizza by ID"""
            try:
                pizza = self.db.execute_query(
                    "SELECT * FROM frontend.pizzas WHERE id = %s",
                    (pizza_id,),
                    fetch='one'
                )
                
                if not pizza:
                    return jsonify({
                        'success': False,
                        'error': 'Pizza not found'
                    }), 404
                
                self.metrics.record_business_event('pizza_detail_request', 'success')
                
                return jsonify({
                    'success': True,
                    'pizza': pizza,
                    'timestamp': self.get_timestamp()
                })
                
            except Exception as e:
                self.logger.error("Failed to get pizza", pizza_id=pizza_id, error=str(e))
                self.metrics.record_business_event('pizza_detail_request', 'failed')
                
                return jsonify({
                    'success': False,
                    'error': 'Failed to load pizza details'
                }), 500
        
        @self.app.route('/api/v1/menu', methods=['POST'])
        def add_pizza():
            """Add new pizza to menu (admin function)"""
            try:
                data = request.get_json()
                
                # Validate required fields
                required_fields = ['id', 'name', 'description', 'price', 'ingredients']
                missing_fields = validate_required_fields(data, required_fields)
                
                if missing_fields:
                    raise ValidationError(f"Missing required fields: {', '.join(missing_fields)}")
                
                # Validate price is positive
                if data['price'] <= 0:
                    raise ValidationError("Price must be positive")
                
                # Set defaults
                data.setdefault('image_url', f"/images/{data['id']}.jpg")
                data.setdefault('available', True)
                
                # Insert pizza
                with self.db.transaction():
                    with self.db.get_cursor() as cursor:
                        cursor.execute("SET search_path TO frontend, public")
                        cursor.execute("""
                            INSERT INTO frontend.pizzas (id, name, description, price, image_url, ingredients, available)
                            VALUES (%s, %s, %s, %s, %s, %s, %s)
                            ON CONFLICT (id) DO UPDATE SET
                                name = EXCLUDED.name,
                                description = EXCLUDED.description,
                                price = EXCLUDED.price,
                                image_url = EXCLUDED.image_url,
                                ingredients = EXCLUDED.ingredients,
                                available = EXCLUDED.available
                        """, (
                            data['id'],
                            data['name'],
                            data['description'],
                            data['price'],
                            data['image_url'],
                            data['ingredients'],
                            data['available']
                        ))
                
                self.metrics.record_business_event('pizza_added', 'success')
                
                return jsonify({
                    'success': True,
                    'message': 'Pizza added successfully',
                    'pizza_id': data['id']
                }), 201
                
            except ValidationError as e:
                self.logger.warning("Pizza validation failed", error=str(e))
                return jsonify({
                    'success': False,
                    'error': 'Validation error',
                    'message': str(e)
                }), 400
                
            except Exception as e:
                self.logger.error("Failed to add pizza", error=str(e))
                self.metrics.record_business_event('pizza_added', 'failed')
                
                return jsonify({
                    'success': False,
                    'error': 'Failed to add pizza'
                }), 500
        
        @self.app.route('/api/v1/menu/<pizza_id>', methods=['PUT'])
        def update_pizza(pizza_id: str):
            """Update existing pizza in menu (admin function)"""
            try:
                data = request.get_json()
                
                # Build update query dynamically
                update_fields = []
                params = []
                
                allowed_fields = ['name', 'description', 'price', 'image_url', 'ingredients', 'available']
                
                for field in allowed_fields:
                    if field in data:
                        update_fields.append(f"{field} = %s")
                        params.append(data[field])
                
                if not update_fields:
                    raise ValidationError("No valid fields to update")
                
                # Add pizza_id to params
                params.append(pizza_id)
                
                # Execute update
                with self.db.transaction():
                    with self.db.get_cursor() as cursor:
                        cursor.execute("SET search_path TO frontend, public")
                        cursor.execute(f"""
                            UPDATE frontend.pizzas 
                            SET {', '.join(update_fields)}, updated_at = CURRENT_TIMESTAMP
                            WHERE id = %s
                        """, tuple(params))
                        
                        if cursor.rowcount == 0:
                            raise ValidationError("Pizza not found")
                
                self.metrics.record_business_event('pizza_updated', 'success')
                
                return jsonify({
                    'success': True,
                    'message': 'Pizza updated successfully'
                })
                
            except ValidationError as e:
                self.logger.warning("Pizza update validation failed", pizza_id=pizza_id, error=str(e))
                return jsonify({
                    'success': False,
                    'error': 'Validation error',
                    'message': str(e)
                }), 400
                
            except Exception as e:
                self.logger.error("Failed to update pizza", pizza_id=pizza_id, error=str(e))
                self.metrics.record_business_event('pizza_updated', 'failed')
                
                return jsonify({
                    'success': False,
                    'error': 'Failed to update pizza'
                }), 500
        
        @self.app.route('/api/v1/menu/<pizza_id>', methods=['DELETE'])
        def delete_pizza(pizza_id: str):
            """Delete a pizza from the menu (admin function)"""
            try:
                with self.db.transaction():
                    with self.db.get_cursor() as cursor:
                        cursor.execute("SET search_path TO frontend, public")
                        cursor.execute(
                            "DELETE FROM frontend.pizzas WHERE id = %s",
                            (pizza_id,)
                        )
                        
                        if cursor.rowcount == 0:
                            return jsonify({
                                'success': False,
                                'error': 'Pizza not found'
                            }), 404
                
                self.metrics.record_business_event('pizza_deleted', 'success')
                
                return jsonify({
                    'success': True,
                    'message': 'Pizza deleted successfully'
                })
                
            except Exception as e:
                self.logger.error("Failed to delete pizza", pizza_id=pizza_id, error=str(e))
                self.metrics.record_business_event('pizza_deleted', 'failed')
                
                return jsonify({
                    'success': False,
                    'error': 'Failed to delete pizza'
                }), 500
        
        @self.app.route('/api/v1/stats', methods=['GET'])
        def get_stats():
            """Get frontend service statistics"""
            try:
                # Get pizza count
                total_pizzas = self.db.execute_query(
                    "SELECT COUNT(*) as count FROM frontend.pizzas",
                    fetch='one'
                )['count']
                
                available_pizzas = self.db.execute_query(
                    "SELECT COUNT(*) as count FROM frontend.pizzas WHERE available = true",
                    fetch='one'
                )['count']
                
                return jsonify({
                    'success': True,
                    'stats': {
                        'total_pizzas': total_pizzas,
                        'available_pizzas': available_pizzas,
                        'service': 'frontend-service',
                        'version': os.getenv('SERVICE_VERSION', '1.0.0'),
                        'uptime': time.time() - self.start_time
                    },
                    'timestamp': self.get_timestamp()
                })
                
            except Exception as e:
                self.logger.error("Failed to get stats", error=str(e))
                return jsonify({
                    'success': False,
                    'error': 'Failed to get statistics'
                }), 500

        @self.app.route('/api/v1/logs', methods=['GET'])
        def get_recent_logs():
            """Get recent logs from all microservices."""
            service_name = request.args.get('service')
            
            if service_name:
                # Get logs for a specific service
                logs = self.get_service_logs(service_name)
                return jsonify({'service': service_name, 'logs': logs})
            
            # Get logs for all services
            services = [
                'frontend-service',
                'order-service',
                'payment-service',
                'notification-service',
                'payment-mock'
            ]
            
            all_logs = {}
            for service in services:
                try:
                    all_logs[service] = self.get_service_logs(service)
                except Exception as e:
                    self.logger.warning(f"Could not fetch logs for {service}", error=str(e))
                    all_logs[service] = [{"line": f"Error fetching logs: {e}"}]


            return jsonify(all_logs)

        @self.app.route('/api/v1/load-test/start', methods=['POST'])
        def start_load_test():
            """Start load testing simulation"""
            try:
                data = request.get_json() or {}
                rps = data.get('rps', 1000)
                duration = data.get('duration', '1m')
                fail_rate = data.get('failRate', 0)
                # Генерируем идентификатор теста и фиксируем параметры
                test_id = generate_id('load_')
                start_ts = self.get_timestamp()

                # Формируем команду запуска k6 (RATE/DURATION из env)
                cmd = [
                    'k6', 'run',
                    '--env', f'FAIL_RATE={fail_rate}',
                    '--env', f'RATE={rps}',
                    '--env', f'DURATION={duration}',
                    '/app/load-testing/order-create.js'
                ]
                # Сохраняем параметры теста в файл для последующего расчёта
                try:
                    os.makedirs('/app/logs', exist_ok=True)
                    tests_file = '/app/logs/load_tests.json'
                    record = {
                        'test_id': test_id,
                        'rps': rps,
                        'duration': duration,
                        'fail_rate': fail_rate,
                        'started_at': start_ts
                    }
                    # Читаем существующие записи (если есть)
                    existing = []
                    if os.path.exists(tests_file):
                        with open(tests_file, 'r') as f:
                            try:
                                existing = json.load(f) or []
                            except Exception:
                                existing = []
                    existing.append(record)
                    with open(tests_file, 'w') as f:
                        json.dump(existing, f)
                except Exception as e:
                    self.logger.warning("Failed to persist load test record", error=str(e))

                # Запускаем k6 в фоне
                subprocess.Popen(cmd)
                return jsonify({
                    'success': True,
                    'test_id': test_id,
                    'message': f'k6 started with {rps} RPS, {fail_rate}% fail, duration {duration}'
                })
                
            except Exception as e:
                self.logger.error("Failed to start load test simulation", error=str(e))
                self.metrics.record_business_event('load_test_started', 'failed')
                
                return jsonify({
                    'success': False,
                    'error': 'Failed to start load test simulation',
                    'message': str(e)
                }), 500

        @self.app.route('/api/v1/load-test/results/<test_id>', methods=['GET'])
        def get_load_test_results(test_id: str):
            """Get load test results"""
            try:
                # Читаем параметры теста из файла
                tests_file = '/app/logs/load_tests.json'
                matched = None
                if os.path.exists(tests_file):
                    with open(tests_file, 'r') as f:
                        try:
                            records = json.load(f) or []
                            matched = next((r for r in records if r.get('test_id') == test_id), None)
                        except Exception:
                            matched = None

                if not matched:
                    return jsonify({
                        'success': False,
                        'error': 'Test not found',
                        'message': 'Unknown test_id; results unavailable'
                    }), 404

                # Рассчитываем ожидаемое количество запросов
                rps = int(matched.get('rps', 1000))
                duration_str = str(matched.get('duration', '1m'))
                # Переводим duration в секунды (поддерживаем "Xs" и "Xm")
                seconds = 60
                if duration_str.endswith('s'):
                    seconds = int(duration_str[:-1])
                elif duration_str.endswith('m'):
                    seconds = int(duration_str[:-1]) * 60
                total_requests = rps * seconds

                # Интервал времени теста
                started_at = matched.get('started_at')
                # Поскольку timestamp в ISO, используем PostgreSQL для сравнения
                start_time = started_at
                with self.db.get_cursor() as cursor:
                    cursor.execute("SET search_path TO orders, public")
                    cursor.execute(
                        """
                        SELECT 
                            COUNT(*) AS total_created,
                            COUNT(*) FILTER (WHERE status IN ('PAID','COMPLETED')) AS total_success
                        FROM orders.orders
                        WHERE created_at >= %s 
                          AND created_at <= (%s::timestamp + make_interval(secs => %s))
                        """,
                        (start_time, start_time, seconds)
                    )
                    row = cursor.fetchone()
                    total_created = row['total_created'] if isinstance(row, dict) else row[0]
                    total_success = row['total_success'] if isinstance(row, dict) else row[1]

                success_rate = 0.0 if total_created == 0 else round((total_success / total_created) * 100, 2)
                errors = max(total_created - total_success, 0)

                return jsonify({
                    'success': True,
                    'test_id': test_id,
                    'results': {
                        'total_requests_expected': total_requests,
                        'total_orders_created': total_created,
                        'success_rate': success_rate,
                        'errors': errors
                    },
                    'message': 'Результаты рассчитаны по данным БД orders за интервал теста',
                    'timestamp': self.get_timestamp()
                })
                
            except Exception as e:
                self.logger.error("Failed to get load test results", test_id=test_id, error=str(e))
                
                return jsonify({
                    'success': False,
                    'error': 'Failed to get test results',
                    'message': str(e)
                }), 500

        @self.app.route('/api/v1/k6/start', methods=['POST'])
        def start_k6_direct():
            """Direct load test start (fallback)"""
            try:
                # Use the same simulation as the main load test
                data = request.get_json() or {}
                rps = data.get('rps', 1000)
                duration = data.get('duration', '1m')
                
                # Call the main load test function
                response = start_load_test()
                
                return response
                
            except Exception as e:
                self.logger.error("Failed to start direct load test", error=str(e))
                return jsonify({
                    'success': False,
                    'error': str(e)
                }), 500
    
    def get_service_logs(self, service_name: str, tail: int = 50) -> List[str]:
        """Get last N lines from a service's log file, whitelisting only key business events."""
        log_file = f"/app/logs/{service_name}.log"
        if not os.path.exists(log_file):
            return ["Log file not found."]
        
        try:
            with open(log_file, 'r') as f:
                lines = f.readlines()
                # Разрешаем только ключевые события процесса заказа/оплаты (whitelist)
                allowed_substrings = [
                    'order-outbox-processor',
                    'Failed to publish event',
                    'Failed to publish payment failure event',
                    'PaymentFailed routed to DLQ',
                    'Failed to publish PaymentFailed to DLQ',
                    'DLQ fallback failed',
                    'Error processing Kafka event',
                    'Consumer error',
                    # Order Service: приём заказа
                    '📥 Received order request',
                    'Новый заказ принят',
                    # Order Service: сохранение заказа в БД
                    'Создаём заказ в базе данных',
                    'Order saved to database',
                    # Outbox Processor: публикация события в Kafka
                    '🍕 ЗАКАЗ ПИЦЦЫ: Отправляем событие в Kafka',
                    'kafka_publishing',
                    '🍕 ЗАКАЗ ПИЦЦЫ: Событие успешно отправлено в Kafka',
                    'kafka_published_success',
                    # Payment Service: чтение из Kafka
                    'Событие из Kafka принято к обработке',
                    # Payment Service: отправка на оплату
                    'Запись платежа создана, запускаем асинхронную обработку',
                    'Асинхронная обработка платежа запущена',
                    # Payment Service: подтверждение успешной оплаты
                    'Обработка платежа успешно завершена',
                    # Payment Service: публикация результата в Kafka
                    'Payment success event published',
                    'Отправляем событие успешного платежа в Kafka',
                    # Order Service: чтение оплаты из Kafka
                    '📥 Received new payment event from Kafka',
                    # Order Service: перевод статуса в PAID
                    'OrderStatusChanged event added to outbox',
                    'status": "PAID',
                    'переведён в статус PAID',
                    # Order Service: отдача информации в UI
                    'Order retrieved',
                    # Custom explicit Russian phrases for required scenario
                    'order-service принял заказ в обработку',
                    'order-service вычитал сообщение из топика',
                    'order-service перевёл заказ в статус PAID',
                    'payment-service вычитал сообщение из топика',
                    'payment-service отправил на оплату',
                    'payment-service принял сообщение об успешной оплате',
                    'payment-service отослал в кафку',
                ]

                allowed_stages = {
                    # Outbox
                    'outbox_processing',
                    'kafka_publishing',
                    'kafka_published_success',
                    # Payment lifecycle
                    'payment_record_creating',
                    'payment_async_starting',
                    'payment_async_started',
                    'payment_processing_success',
                    'payment_success_event_publishing',
                    # Custom explicit stages
                    'order_processing_started',
                    'payment_event_consumed',
                    'sent_to_gateway',
                    'payment_confirmed',
                    'payment_event_sent_kafka',
                    'order_status_paid',
                    'kafka_event_consumed',
                }

                def is_allowed(line: str) -> bool:
                    # Разрешение по подстрокам (для простых текстовых логов)
                    if any(s in line for s in allowed_substrings):
                        return True
                    # Разрешение по структурированным полям (JSON)
                    try:
                        obj = json.loads(line)
                        # По stage
                        if obj.get('stage') in allowed_stages:
                            return True
                        # Специфические события
                        msg_text = obj.get('event') or obj.get('message') or obj.get('msg')
                        if msg_text and any(s in msg_text for s in allowed_substrings):
                            return True
                    except Exception:
                        pass
                    return False

                filtered = [ln for ln in lines if is_allowed(ln)]

                # Дедупликация: убираем повторяющиеся строки, сохраняя порядок последних сообщений
                seen = set()
                unique_reversed = []
                for ln in reversed(filtered):
                    key = ln.strip()
                    if key not in seen:
                        seen.add(key)
                        unique_reversed.append(ln)
                unique = list(reversed(unique_reversed))

                # Возвращаем последние tail записей, конвертируя JSON-строки в объекты для UI
                result_lines = unique[-tail:]
                structured = []
                for ln in result_lines:
                    line = ln.strip()
                    try:
                        obj = json.loads(line)
                        # Гарантируем наличие ключевых полей для UI
                        if 'event_type' not in obj:
                            obj['event_type'] = 'LOG'
                        if 'service' not in obj:
                            obj['service'] = service_name
                        structured.append(obj)
                    except Exception:
                        # Текстовая строка — отдаём как есть
                        structured.append(line)
                return structured
        except Exception as e:
            self.logger.error(f"Failed to read log file {log_file}", error=str(e))
            return [f"Error reading log file: {e}"]

    def get_timestamp(self) -> str:
        """Get current timestamp in ISO format"""
        from datetime import datetime, timezone
        return datetime.now(timezone.utc).isoformat()


# ========================================
# Application Entry Point
# ========================================

if __name__ == '__main__':
    try:
        # Create and run service
        service = FrontendService()
        service.logger.info("🍕 Starting Frontend Service")
        
        # Run in debug mode if specified
        debug_mode = os.getenv('FLASK_DEBUG', 'false').lower() == 'true'
        service.run(debug=debug_mode)
        
    except KeyboardInterrupt:
        print("\n🛑 Frontend Service stopped by user")
    except Exception as e:
        print(f"❌ Frontend Service failed to start: {e}")
        sys.exit(1)