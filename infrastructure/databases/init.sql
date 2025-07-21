-- ================================================
-- Pizza Order System - Database Initialization
-- Event-Driven Saga Architecture
-- ================================================

-- ================================================
-- FRONTEND SERVICE SCHEMA
-- ================================================

-- Create schema for frontend service
CREATE SCHEMA IF NOT EXISTS frontend;

-- Pizzas catalog table
CREATE TABLE frontend.pizzas (
    id VARCHAR(50) PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    description TEXT,
    price INTEGER NOT NULL, -- Price in cents
    image_url VARCHAR(255),
    ingredients TEXT[],
    available BOOLEAN DEFAULT true,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Insert sample pizzas
INSERT INTO frontend.pizzas (id, name, description, price, image_url, ingredients, available) VALUES
('margherita', 'Маргарита', 'Классическая пицца с томатным соусом, моцареллой и базиликом', 59900, '/images/margherita.jpg', ARRAY['томатный соус', 'моцарелла', 'базилик'], true),
('pepperoni', 'Пепперони', 'Острая пицца с пепперони и сыром моцарелла', 69900, '/images/pepperoni.jpg', ARRAY['томатный соус', 'моцарелла', 'пепперони'], true),
('quattro-formaggi', 'Четыре сыра', 'Изысканная пицца с четырьмя видами сыра', 79900, '/images/quattro-formaggi.jpg', ARRAY['соус белый', 'моцарелла', 'горгонзола', 'пармезан', 'рикотта'], true);

-- Frontend service logs
CREATE TABLE frontend.service_logs (
    id SERIAL PRIMARY KEY,
    level VARCHAR(20) NOT NULL,
    message TEXT NOT NULL,
    extra_data JSONB,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- ================================================
-- ORDER SERVICE SCHEMA  
-- ================================================

-- Create schema for order service
CREATE SCHEMA IF NOT EXISTS orders;

-- Orders table
CREATE TABLE orders.orders (
    id VARCHAR(50) PRIMARY KEY,
    user_id VARCHAR(50) NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'PENDING', -- PENDING, PROCESSING, PAID, FAILED, COMPLETED
    total INTEGER NOT NULL, -- Total amount in cents
    delivery_address TEXT NOT NULL,
    payment_method VARCHAR(20) NOT NULL DEFAULT 'card',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Order items table
CREATE TABLE orders.order_items (
    id SERIAL PRIMARY KEY,
    order_id VARCHAR(50) NOT NULL REFERENCES orders.orders(id) ON DELETE CASCADE,
    pizza_id VARCHAR(50) NOT NULL,
    pizza_name VARCHAR(100) NOT NULL,
    pizza_price INTEGER NOT NULL,
    quantity INTEGER NOT NULL DEFAULT 1,
    subtotal INTEGER NOT NULL, -- pizza_price * quantity
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Outbox pattern table for event publishing
CREATE TABLE orders.outbox_events (
    id SERIAL PRIMARY KEY,
    aggregate_id VARCHAR(50) NOT NULL, -- order_id
    event_type VARCHAR(50) NOT NULL,   -- OrderCreated, OrderUpdated, etc.
    event_data JSONB NOT NULL,
    processed BOOLEAN DEFAULT false,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    processed_at TIMESTAMP
);

-- Order saga state tracking
CREATE TABLE orders.order_saga_state (
    order_id VARCHAR(50) PRIMARY KEY REFERENCES orders.orders(id) ON DELETE CASCADE,
    current_step VARCHAR(50) NOT NULL, -- created, payment_pending, payment_processed, completed, failed
    steps_completed TEXT[], -- Array of completed steps
    compensation_needed BOOLEAN DEFAULT false,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Order service logs
CREATE TABLE orders.service_logs (
    id SERIAL PRIMARY KEY,
    order_id VARCHAR(50),
    level VARCHAR(20) NOT NULL,
    message TEXT NOT NULL,
    extra_data JSONB,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Indexes for performance
CREATE INDEX idx_orders_user_id ON orders.orders(user_id);
CREATE INDEX idx_orders_status ON orders.orders(status);
CREATE INDEX idx_orders_created_at ON orders.orders(created_at);
CREATE INDEX idx_outbox_events_processed ON orders.outbox_events(processed);
CREATE INDEX idx_outbox_events_created_at ON orders.outbox_events(created_at);

-- ================================================
-- PAYMENT SERVICE SCHEMA
-- ================================================

-- Create schema for payment service
CREATE SCHEMA IF NOT EXISTS payments;

-- Payments table
CREATE TABLE payments.payments (
    id VARCHAR(50) PRIMARY KEY,
    order_id VARCHAR(50) NOT NULL UNIQUE,
    amount INTEGER NOT NULL, -- Amount in cents
    status VARCHAR(20) NOT NULL DEFAULT 'PENDING', -- PENDING, PROCESSING, COMPLETED, FAILED
    payment_method VARCHAR(20) NOT NULL,
    idempotency_key VARCHAR(100) UNIQUE NOT NULL, -- For preventing duplicate payments
    external_payment_id VARCHAR(100), -- ID from external payment provider (mock)
    failure_reason TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Payment attempts for retry pattern
CREATE TABLE payments.payment_attempts (
    id SERIAL PRIMARY KEY,
    payment_id VARCHAR(50) NOT NULL REFERENCES payments.payments(id) ON DELETE CASCADE,
    attempt_number INTEGER NOT NULL,
    status VARCHAR(20) NOT NULL, -- PENDING, SUCCESS, FAILED, TIMEOUT
    request_data JSONB,
    response_data JSONB,
    error_message TEXT,
    attempt_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    completed_at TIMESTAMP
);

-- Payment service logs
CREATE TABLE payments.service_logs (
    id SERIAL PRIMARY KEY,
    payment_id VARCHAR(50),
    order_id VARCHAR(50),
    level VARCHAR(20) NOT NULL,
    message TEXT NOT NULL,
    extra_data JSONB,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Indexes for performance
CREATE INDEX idx_payments_order_id ON payments.payments(order_id);
CREATE INDEX idx_payments_status ON payments.payments(status);
CREATE INDEX idx_payments_idempotency_key ON payments.payments(idempotency_key);
CREATE INDEX idx_payment_attempts_payment_id ON payments.payment_attempts(payment_id);

-- ================================================
-- NOTIFICATION SERVICE SCHEMA
-- ================================================

-- Create schema for notification service
CREATE SCHEMA IF NOT EXISTS notifications;

-- Notifications table
CREATE TABLE notifications.notifications (
    id VARCHAR(50) PRIMARY KEY,
    user_id VARCHAR(50) NOT NULL,
    order_id VARCHAR(50),
    template_type VARCHAR(50),      -- e.g., 'OrderCreated', 'PaymentFailed'
    subject VARCHAR(255) NOT NULL,
    message TEXT NOT NULL,
    channels TEXT[] NOT NULL,       -- e.g., ['EMAIL', 'SMS']
    priority VARCHAR(20) DEFAULT 'normal',
    status VARCHAR(20) DEFAULT 'PENDING', -- PENDING, SENT, FAILED
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Delivery attempts for each notification
CREATE TABLE notifications.delivery_attempts (
    id SERIAL PRIMARY KEY,
    notification_id VARCHAR(50) NOT NULL REFERENCES notifications.notifications(id) ON DELETE CASCADE,
    channel VARCHAR(20) NOT NULL, -- EMAIL, SMS, PUSH, WEBHOOK
    status VARCHAR(20) NOT NULL,  -- SUCCESS, FAILED
    attempt_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    error_message TEXT
);

-- Notification templates
CREATE TABLE notifications.notification_templates (
    id SERIAL PRIMARY KEY,
    type VARCHAR(50) NOT NULL UNIQUE,
    title_template VARCHAR(200) NOT NULL,
    message_template TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Insert default notification templates
INSERT INTO notifications.notification_templates (type, title_template, message_template) VALUES
('order_created', 'Заказ #{order_id} создан', 'Ваш заказ на сумму {total} руб. принят и обрабатывается. Адрес доставки: {delivery_address}'),
('payment_processing', 'Обработка оплаты заказа #{order_id}', 'Ваш заказ на сумму {total} руб. передан в обработку платежной системе.'),
('payment_success', 'Заказ #{order_id} оплачен!', 'Оплата на сумму {total} руб. прошла успешно. Ваш заказ готовится!'),
('payment_failed', 'Ошибка оплаты заказа #{order_id}', 'К сожалению, оплата на сумму {total} руб. не прошла. Причина: {failure_reason}. Попробуйте снова или выберите другой способ оплаты.'),
('order_completed', 'Заказ #{order_id} готов!', 'Ваш заказ готов и отправлен по адресу: {delivery_address}. Спасибо за покупку!');

-- Notification service logs
CREATE TABLE notifications.service_logs (
    id SERIAL PRIMARY KEY,
    notification_id VARCHAR(50),
    user_id VARCHAR(50),
    level VARCHAR(20) NOT NULL,
    message TEXT NOT NULL,
    extra_data JSONB,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Indexes for performance
CREATE INDEX idx_notifications_user_id ON notifications.notifications(user_id);
CREATE INDEX idx_notifications_order_id ON notifications.notifications(order_id);
CREATE INDEX idx_notifications_template_type ON notifications.notifications(template_type);
CREATE INDEX idx_notifications_created_at ON notifications.notifications(created_at);

-- ================================================
-- TRIGGERS FOR UPDATED_AT COLUMNS
-- ================================================

-- Function to update updated_at column
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ language 'plpgsql';

-- Apply triggers to tables with updated_at columns
CREATE TRIGGER update_orders_updated_at 
    BEFORE UPDATE ON orders.orders 
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_order_saga_state_updated_at 
    BEFORE UPDATE ON orders.order_saga_state 
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_payments_updated_at 
    BEFORE UPDATE ON payments.payments 
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

-- ================================================
-- GRANTS AND PERMISSIONS
-- ================================================

-- Grant usage on schemas
GRANT USAGE ON SCHEMA frontend TO PUBLIC;
GRANT USAGE ON SCHEMA orders TO PUBLIC;
GRANT USAGE ON SCHEMA payments TO PUBLIC;
GRANT USAGE ON SCHEMA notifications TO PUBLIC;

-- Grant permissions on all tables
GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA frontend TO PUBLIC;
GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA orders TO PUBLIC;
GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA payments TO PUBLIC;
GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA notifications TO PUBLIC;

-- Grant permissions on sequences
GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA frontend TO PUBLIC;
GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA orders TO PUBLIC;
GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA payments TO PUBLIC;
GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA notifications TO PUBLIC; 