# Pizza Order System - Event-Driven Architecture Demo

## Обзор проекта

Данный проект представляет собой демонстрационный стенд системы заказа пиццы, построенной на принципах **Event-Driven Architecture** с использованием паттерна **Outbox** для обеспечения консистентности данных.

## Архитектурные принципы

### Event-Driven Architecture (EDA)
- **Асинхронное взаимодействие** между сервисами через события
- **Слабая связанность** компонентов системы
- **Eventual Consistency** для обеспечения целостности данных
- **Горизонтальная масштабируемость** каждого сервиса

### Outbox Pattern
- **Транзакционная безопасность** при публикации событий
- **Гарантированная доставка** событий в брокер сообщений
- **Идемпотентность** обработки событий

## Структура системы

### Микросервисы

1. **Frontend Service** (`/services/frontend/`)
   - Управление каталогом пицц
   - REST API для клиентских приложений
   - Технологии: Python, Flask, PostgreSQL

2. **Order Service** (`/services/orders/`)
   - Управление жизненным циклом заказов
   - Реализация Outbox Pattern
   - Технологии: Python, Flask, PostgreSQL, Kafka

3. **Payment Service** (`/services/payments/`)
   - Обработка платежей через внешние провайдеры
   - Управление статусами платежей
   - Технологии: Python, Flask, PostgreSQL, Kafka

4. **Notification Service** (`/services/notification/`)
   - Отправка уведомлений (Email, SMS, Push)
   - Управление шаблонами уведомлений
   - Технологии: Python, Flask, PostgreSQL, Kafka

### Инфраструктура

- **Apache Kafka**: Брокер сообщений для event streaming
- **PostgreSQL**: Основная база данных для всех сервисов
- **Docker**: Контейнеризация сервисов

## Документация

### 📊 Диаграммы и схемы

1. **[Модели данных](docs/data_models.md)**
   - Схемы баз данных всех сервисов
   - Описание таблиц, индексов и триггеров
   - Структуры событий и перечислений

2. **[ER-диаграмма](docs/er_diagram.svg)**
   - Визуализация взаимосвязей между сущностями
   - Схемы баз данных: frontend, orders, payments, notifications
   - Связи между таблицами (1:1, 1:N)

3. **[C4 Architecture Diagram](docs/c4_architecture.svg)**
   - Многоуровневая архитектурная диаграмма
   - Level 1: System Context
   - Level 2: Container Diagram
   - Level 3: Component Diagram
   - Event Flow Visualization

4. **[Message Flow Documentation](docs/message_flow.md)**
   - Детальное описание потока сообщений
   - Диаграмма последовательности
   - Обработка ошибок и retry логика
   - Мониторинг и метрики

### 🔄 Процесс заказа (End-to-End)

```
1. Customer создает заказ → Frontend Service
2. Frontend Service → Order Service (создание заказа)
3. Order Service → Kafka (событие OrderCreated)
4. Payment Service ← Kafka (обработка платежа)
5. Payment Service → External Payment Provider
6. Payment Service → Kafka (событие PaymentCompleted)
7. Order Service ← Kafka (обновление статуса заказа)
8. Notification Service ← Kafka (отправка уведомлений)
9. Customer получает уведомления (Email/SMS)
```

## Ключевые особенности реализации

### Outbox Pattern Implementation

```sql
-- Атомарная транзакция в Order Service
BEGIN;
  INSERT INTO orders (...) VALUES (...);
  INSERT INTO order_items (...) VALUES (...);
  INSERT INTO outbox_events (event_type, event_data, ...) VALUES ('OrderCreated', '...', ...);
COMMIT;
```

### Event Publishing

```python
# Фоновый процесс публикации событий
while True:
    unpublished_events = get_unpublished_events()
    for event in unpublished_events:
        kafka_producer.send(topic, event)
        mark_as_published(event.id)
    time.sleep(5)
```

### Error Handling

- **Retry Logic**: Экспоненциальная задержка при ошибках
- **Dead Letter Queue**: Для сообщений, которые не удалось обработать
- **Circuit Breaker**: Защита от каскадных отказов
- **Health Checks**: Мониторинг состояния сервисов

## Запуск системы

### Предварительные требования

- Docker и Docker Compose
- Python 3.9+
- PostgreSQL 15+
- Apache Kafka 2.8+

### Локальный запуск

```bash
# Клонирование репозитория
git clone <repository-url>
cd pizza_logs

# Запуск инфраструктуры
docker-compose up -d kafka postgres

# Запуск сервисов
cd services/orders && python app.py &
cd services/payments && python app.py &
cd services/notification && python app.py &
cd services/frontend && python app.py &
```

### API Endpoints

#### Frontend Service (Port 5001)
```
GET  /api/v1/menu           # Получить каталог пицц
POST /api/v1/menu           # Добавить пиццу
GET  /api/v1/menu/{id}      # Получить пиццу по ID
```

#### Order Service (Port 5002)
```
POST /api/v1/orders         # Создать заказ
GET  /api/v1/orders/{id}    # Получить заказ по ID
GET  /api/v1/orders         # Получить список заказов
```

#### Payment Service (Port 5003)
```
POST /api/v1/payments       # Обработать платеж
GET  /api/v1/payments/{id}  # Получить статус платежа
```

#### Notification Service (Port 5004)
```
POST /api/v1/notifications  # Отправить уведомление
GET  /api/v1/notifications  # Получить историю уведомлений
```

## Мониторинг и наблюдаемость

### Метрики

- **Business Metrics**:
  - Время обработки заказа (end-to-end)
  - Процент успешных платежей
  - Количество отправленных уведомлений

- **Technical Metrics**:
  - Kafka Consumer Lag
  - Outbox Events Processing Time
  - Database Connection Pool Usage
  - HTTP Response Times

### Логирование

```python
# Структурированное логирование
logger.info(
    "Order created",
    extra={
        'order_id': order.id,
        'customer_email': order.customer_email,
        'total_amount': order.total_amount,
        'timestamp': datetime.utcnow().isoformat()
    }
)
```

## Тестирование

### Unit Tests
```bash
# Запуск тестов для каждого сервиса
cd services/orders && python -m pytest tests/
cd services/payments && python -m pytest tests/
cd services/notification && python -m pytest tests/
```

### Integration Tests
```bash
# End-to-end тестирование
python tests/integration/test_order_flow.py
```

### Load Testing
```bash
# Нагрузочное тестирование с помощью Apache Bench
ab -n 1000 -c 10 -H "Content-Type: application/json" \
   -p order_payload.json http://localhost:5002/api/v1/orders
```

## Масштабирование

### Горизонтальное масштабирование

- **Stateless Services**: Все сервисы не хранят состояние
- **Database Sharding**: Разделение данных по ключам
- **Kafka Partitioning**: Распределение нагрузки по партициям
- **Load Balancing**: Распределение запросов между инстансами

### Вертикальное масштабирование

- **Database Optimization**: Индексы, query optimization
- **Connection Pooling**: Эффективное использование соединений
- **Caching**: Redis для кэширования частых запросов

## Безопасность

### Аутентификация и авторизация
- JWT токены для API аутентификации
- Role-based access control (RBAC)
- API Rate Limiting

### Защита данных
- Шифрование данных в покое и в движении
- PII (Personally Identifiable Information) protection
- Audit logging для критических операций

## Развертывание

### Production Environment

```yaml
# docker-compose.prod.yml
version: '3.8'
services:
  order-service:
    image: pizza-order-service:latest
    replicas: 3
    environment:
      - DATABASE_URL=postgresql://...
      - KAFKA_BROKERS=kafka1:9092,kafka2:9092,kafka3:9092
    deploy:
      resources:
        limits:
          memory: 512M
          cpus: '0.5'
```

### CI/CD Pipeline

```yaml
# .github/workflows/deploy.yml
name: Deploy to Production
on:
  push:
    branches: [main]
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v2
      - name: Run tests
        run: python -m pytest
  
  deploy:
    needs: test
    runs-on: ubuntu-latest
    steps:
      - name: Deploy to Kubernetes
        run: kubectl apply -f k8s/
```

## Заключение

Данный стенд демонстрирует современные подходы к построению распределенных систем:

✅ **Event-Driven Architecture** для слабой связанности сервисов  
✅ **Outbox Pattern** для гарантированной доставки событий  
✅ **Microservices** для независимого развертывания и масштабирования  
✅ **Observability** для мониторинга и отладки  
✅ **Fault Tolerance** для обработки ошибок и отказов  

Система готова к production использованию и может служить основой для реальных e-commerce проектов.

---

## Контакты и поддержка

Для вопросов по архитектуре и реализации обращайтесь к документации в папке `/docs/` или создавайте issues в репозитории.

**Документация обновлена**: January 2024