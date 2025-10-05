# Модели данных Pizza Order System

## Обзор

Данный документ содержит описание всех моделей данных, используемых в системе заказа пиццы. Система построена на основе Event-Driven Saga Architecture с использованием Outbox Pattern.

## Схемы базы данных

### 1. Frontend Schema

#### Таблица: pizzas
```sql
CREATE TABLE frontend.pizzas (
    id VARCHAR(50) PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    description TEXT,
    price INTEGER NOT NULL, -- цена в копейках
    image_url VARCHAR(255),
    ingredients TEXT[], -- массив ингредиентов
    available BOOLEAN DEFAULT true,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

**Описание полей:**
- `id` - уникальный идентификатор пиццы
- `name` - название пиццы
- `description` - описание пиццы
- `price` - цена в копейках (например, 59900 = 599 рублей)
- `image_url` - URL изображения пиццы
- `ingredients` - массив ингредиентов
- `available` - доступность для заказа

### 2. Orders Schema

#### Таблица: orders
```sql
CREATE TABLE orders.orders (
    id VARCHAR(50) PRIMARY KEY,
    user_id VARCHAR(50) NOT NULL,
    status VARCHAR(20) DEFAULT 'PENDING',
    total_amount INTEGER NOT NULL, -- общая сумма в копейках
    delivery_address TEXT NOT NULL,
    phone VARCHAR(20),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

#### Таблица: order_items
```sql
CREATE TABLE orders.order_items (
    id SERIAL PRIMARY KEY,
    order_id VARCHAR(50) REFERENCES orders.orders(id),
    pizza_id VARCHAR(50) NOT NULL,
    pizza_name VARCHAR(100) NOT NULL,
    quantity INTEGER NOT NULL DEFAULT 1,
    unit_price INTEGER NOT NULL, -- цена за единицу в копейках
    total_price INTEGER NOT NULL, -- общая цена позиции в копейках
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

#### Таблица: outbox_events
```sql
CREATE TABLE orders.outbox_events (
    id SERIAL PRIMARY KEY,
    aggregate_id VARCHAR(50) NOT NULL,
    event_type VARCHAR(50) NOT NULL,
    event_data JSONB NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    processed_at TIMESTAMP,
    status VARCHAR(20) DEFAULT 'PENDING'
);
```

### 3. Payments Schema

#### Таблица: payments
```sql
CREATE TABLE payments.payments (
    id VARCHAR(50) PRIMARY KEY,
    order_id VARCHAR(50) NOT NULL,
    amount INTEGER NOT NULL, -- сумма в копейках
    payment_method VARCHAR(50) NOT NULL,
    status VARCHAR(20) DEFAULT 'PENDING',
    idempotency_key VARCHAR(255) UNIQUE,
    failure_reason TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

#### Таблица: payment_attempts
```sql
CREATE TABLE payments.payment_attempts (
    id SERIAL PRIMARY KEY,
    payment_id VARCHAR(50) REFERENCES payments.payments(id),
    attempt_number INTEGER NOT NULL,
    success BOOLEAN DEFAULT false,
    error_message TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

### 4. Notifications Schema

#### Таблица: notifications
```sql
CREATE TABLE notifications.notifications (
    id VARCHAR(50) PRIMARY KEY,
    user_id VARCHAR(50) NOT NULL,
    order_id VARCHAR(50),
    subject VARCHAR(255),
    message TEXT NOT NULL,
    channels TEXT[], -- массив каналов уведомлений
    priority VARCHAR(20) DEFAULT 'normal',
    template_type VARCHAR(50),
    status VARCHAR(20) DEFAULT 'PENDING',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    sent_at TIMESTAMP
);
```

#### Таблица: notification_templates
```sql
CREATE TABLE notifications.notification_templates (
    id SERIAL PRIMARY KEY,
    type VARCHAR(50) UNIQUE NOT NULL,
    title_template TEXT NOT NULL,
    message_template TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

#### Таблица: notification_deliveries
```sql
CREATE TABLE notifications.notification_deliveries (
    id SERIAL PRIMARY KEY,
    notification_id VARCHAR(50) REFERENCES notifications.notifications(id),
    channel VARCHAR(20) NOT NULL,
    recipient VARCHAR(255) NOT NULL,
    status VARCHAR(20) DEFAULT 'PENDING',
    sent_at TIMESTAMP,
    delivered_at TIMESTAMP,
    error_message TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

## Перечисления (Enums)

### OrderStatus
```python
class OrderStatus(Enum):
    PENDING = "PENDING"
    CONFIRMED = "CONFIRMED"
    PAID = "PAID"
    PREPARING = "PREPARING"
    READY = "READY"
    DELIVERED = "DELIVERED"
    CANCELLED = "CANCELLED"
```

### PaymentStatus
```python
class PaymentStatus(Enum):
    PENDING = "PENDING"
    PROCESSING = "PROCESSING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
```

### NotificationType
```python
class NotificationType(Enum):
    EMAIL = "EMAIL"
    SMS = "SMS"
    PUSH = "PUSH"
    WEBHOOK = "WEBHOOK"
```

### NotificationStatus
```python
class NotificationStatus(Enum):
    PENDING = "PENDING"
    SENT = "SENT"
    FAILED = "FAILED"
    DELIVERED = "DELIVERED"
```

### CircuitBreakerState
```python
class CircuitBreakerState(Enum):
    CLOSED = "CLOSED"
    OPEN = "OPEN"
    HALF_OPEN = "HALF_OPEN"
```

## Структуры событий

### OrderCreated Event
```json
{
  "orderId": "order_abc123",
  "userId": "user_123",
  "items": [
    {
      "pizzaId": "margherita",
      "pizzaName": "Маргарита",
      "quantity": 2,
      "unitPrice": 59900,
      "totalPrice": 119800
    }
  ],
  "totalAmount": 119800,
  "deliveryAddress": "ул. Примерная, д. 1",
  "phone": "+7 (999) 123-45-67",
  "timestamp": "2024-01-15T10:30:00Z"
}
```

### PaymentCompleted Event
```json
{
  "paymentId": "payment_xyz789",
  "orderId": "order_abc123",
  "amount": 119800,
  "paymentMethod": "card",
  "timestamp": "2024-01-15T10:35:00Z"
}
```

### PaymentFailed Event
```json
{
  "paymentId": "payment_xyz789",
  "orderId": "order_abc123",
  "amount": 119800,
  "failureReason": "Insufficient funds",
  "timestamp": "2024-01-15T10:35:00Z"
}
```

## Индексы

```sql
-- Orders
CREATE INDEX idx_orders_user_id ON orders.orders(user_id);
CREATE INDEX idx_orders_status ON orders.orders(status);
CREATE INDEX idx_orders_created_at ON orders.orders(created_at);
CREATE INDEX idx_order_items_order_id ON orders.order_items(order_id);
CREATE INDEX idx_outbox_events_status ON orders.outbox_events(status);
CREATE INDEX idx_outbox_events_created_at ON orders.outbox_events(created_at);

-- Payments
CREATE INDEX idx_payments_order_id ON payments.payments(order_id);
CREATE INDEX idx_payments_status ON payments.payments(status);
CREATE INDEX idx_payment_attempts_payment_id ON payments.payment_attempts(payment_id);

-- Notifications
CREATE INDEX idx_notifications_user_id ON notifications.notifications(user_id);
CREATE INDEX idx_notifications_order_id ON notifications.notifications(order_id);
CREATE INDEX idx_notifications_status ON notifications.notifications(status);
CREATE INDEX idx_notification_deliveries_notification_id ON notifications.notification_deliveries(notification_id);
```

## Триггеры

```sql
-- Автоматическое обновление updated_at
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ language 'plpgsql';

CREATE TRIGGER update_orders_updated_at BEFORE UPDATE ON orders.orders
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_payments_updated_at BEFORE UPDATE ON payments.payments
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
```

## Ключевые особенности

1. **Outbox Pattern**: Используется для обеспечения консистентности между изменениями в базе данных и публикацией событий
2. **Идемпотентность**: Платежи используют idempotency_key для предотвращения дублирования
3. **Retry Pattern**: Система поддерживает повторные попытки для платежей
4. **Circuit Breaker**: Защита от каскадных сбоев в платежном сервисе
5. **Мультиканальные уведомления**: Поддержка EMAIL, SMS, PUSH, WEBHOOK
6. **Аудит**: Все таблицы содержат временные метки создания и обновления