# 🍕 Pizza Order System - Event-Driven Saga Architecture

## 🎯 Цель проекта

Демонстрация отказоустойчивой, масштабируемой системы для создания, оплаты и подтверждения заказов на основе событийной архитектуры и паттерна **Saga (Choreography-based)**.

## 🏗️ Архитектура системы

```mermaid
flowchart TD
    User["👤 User"] --> Nginx["🔒 Nginx API Gateway"]
    Nginx --> Frontend["🍕 Frontend Service"]
    Nginx --> Order["📦 Order Service"]
    
    subgraph Frontend_Stack ["Frontend Stack"]
        Frontend --> DB_Pizzas["🗄️ Pizzas DB"]
    end
    
    Order --> Kafka["🔄 Kafka Event Bus"]
    
    Kafka --> Payment["💳 Payment Service"]
    Kafka --> Notification["🔔 Notification Service"]
    Kafka --> DLQ["☠️ DLQ Handler"]
    
    Payment --> PMock["🏦 Payment Mock"]
    Notification --> Monitoring["📊 Prometheus + Grafana"]
```

## 🔄 Saga Flow

1. **Создание заказа** → Order Service → `OrderCreated` event
2. **Обработка оплаты** → Payment Service → `OrderPaid` / `PaymentFailed` 
3. **Уведомления** → Notification Service → User notification

## 🚀 Быстрый старт

### 🌐 Запуск в GitHub Codespaces (Рекомендуется)

[![Open in GitHub Codespaces](https://github.com/codespaces/badge.svg)](https://codespaces.new/your-username/pizza-order-system)

1. **Нажмите кнопку "Open in GitHub Codespaces"** выше
2. **Дождитесь инициализации** (займет 2-3 минуты)
3. **Запустите систему:**
   ```bash
   docker compose up --build
   ```
4. **Откройте главную страницу** через forwarded port 80
5. **Мониторинг будет доступен** через соответствующие порты (автоматически настроится)

**Преимущества Codespaces:**
- ✅ Не требует локальной установки Docker
- ✅ Автоматическая настройка портов
- ✅ Быстрый старт за 1 клик
- ✅ Доступ к мониторингу из любого места

### 💻 Локальная разработка

**Предварительные требования:**
- Docker & Docker Compose
- 8GB RAM (рекомендуется)

**Запуск системы:**

```bash
# Клонируем репозиторий
git clone <repo-url>
cd pizza-order-system

# Запуск всей системы
docker-compose up --build

# Проверка статуса
docker-compose ps
```

### Доступные сервисы

| Сервис | Локальный URL | Codespaces | Описание |
|--------|---------------|------------|----------|
| **Frontend UI** | http://localhost | Порт 80 | Веб-интерфейс заказов |
| **API Gateway** | http://localhost/api | Порт 80/api | Nginx роутинг |
| **Grafana** | http://localhost:3000 | Порт 3000 | Мониторинг (admin/admin) |
| **Kafka UI** | http://localhost:8080 | Порт 8080 | Просмотр событий |
| **Prometheus** | http://localhost:9090 | Порт 9090 | Метрики |

> 💡 **В Codespaces** все ссылки на мониторинг автоматически обновляются на правильные forwarded URLs!

## 📖 Использование системы

### 🍕 Создание заказа

1. Откройте http://localhost
2. Просмотрите меню пицц
3. Выберите пиццу и количество
4. Нажмите "Заказать"
5. Укажите адрес доставки
6. Отследите статус заказа

### 📊 Мониторинг системы

#### 🎯 Доступные интерфейсы мониторинга:

| Сервис | URL | Логин | Описание |
|--------|-----|-------|----------|
| **Kafka UI** | http://localhost:8080 | - | События в реальном времени |
| **Grafana** | http://localhost:3000 | admin/admin | Дашборды метрик |
| **Prometheus** | http://localhost:9090 | - | Сырые метрики |
| **pgAdmin** | http://localhost:8081 | admin@pizza.app/admin | Управление БД |
| **cAdvisor** | http://localhost:8083 | - | Мониторинг контейнеров |
| **Node Exporter** | http://localhost:9100 | - | Системные метрики |
| **PostgreSQL Exporter** | http://localhost:9187 | - | Метрики базы данных |
| **Kafka Exporter** | http://localhost:9308 | - | Метрики Kafka |

#### 📈 Дашборды Grafana:
- **Бизнес-метрики**: Заказы, платежи, уведомления
- **Системные метрики**: CPU, память, диск, сеть
- **Метрики контейнеров**: Docker ресурсы
- **Метрики инфраструктуры**: Kafka, PostgreSQL

#### 🎯 Методологии мониторинга:
| Методология | URL | Описание |
|-------------|-----|----------|
| **USE Metrics** | http://localhost:3000/d/use-metrics | Utilization, Saturation, Errors |
| **RED Metrics** | http://localhost:3000/d/red-metrics | Rate, Errors, Duration |
| **LTES Metrics** | http://localhost:3000/d/ltes-metrics | Latency, Traffic, Errors, Saturation |

##### 📊 USE (для инфраструктуры):
- **Utilization**: Использование CPU, памяти, дисков
- **Saturation**: Загрузка системы, очереди
- **Errors**: Ошибки ОС, IO Wait, OOM kills

##### 🔴 RED (для сервисов):
- **Rate**: Количество запросов в секунду
- **Errors**: Процент ошибок (4xx, 5xx)
- **Duration**: Время отклика (P50, P95, P99)

##### 🌐 LTES (для распределенных систем):
- **Latency**: Время обработки заказов, платежей
- **Traffic**: Поток данных Kafka, DB transactions
- **Errors**: Сбои сервисов, откаты транзакций
- **Saturation**: Утилизация пулов соединений

#### 🔄 Kafka события:
- `order-events` - создание заказов
- `payment-events` - результаты оплаты
- `notification-events` - уведомления
- `dlq-events` - неудачные события

#### 🗄️ Доступ к базе данных:
- **Хост**: localhost:5433
- **Пользователь**: pizza_user
- **Пароль**: pizza_password
- **База данных**: pizza_system

### 🧪 Тестирование отказоустойчивости

```bash
# Остановить Payment Service (симуляция сбоя)
docker-compose stop payment-service

# Создать заказ - увидите retry и DLQ
curl -X POST http://localhost/api/v1/orders \
  -H "Content-Type: application/json" \
  -d '{
    "items": [{"pizzaId": "margherita", "quantity": 1}],
    "deliveryAddress": "Test Street 123",
    "paymentMethod": "card"
  }'

# Восстановить сервис
docker-compose start payment-service
```

## 🛠️ Технологический стек

| Компонент | Технология | Назначение |
|-----------|------------|------------|
| **Backend** | Python Flask | REST API микросервисы |
| **Frontend** | HTML/CSS/JS | Веб-интерфейс |
| **Message Broker** | Apache Kafka | Событийная архитектура |
| **Database** | PostgreSQL | Хранение данных |
| **Gateway** | Nginx | API роутинг и балансировка |
| **Monitoring** | Prometheus + Grafana | Метрики и алерты |
| **Orchestration** | Docker Compose | Инфраструктура |

## 📋 Основные паттерны

### 🔄 Saga Choreography
- Децентрализованная координация через события
- Каждый сервис знает свою роль в бизнес-процессе
- Отсутствие единой точки отказа

### 📦 Outbox Pattern  
- Транзакционная публикация событий
- Гарантия доставки сообщений
- Согласованность данных и событий

### 🔁 Retry Pattern
- Автоматические повторы при сбоях
- Экспоненциальная задержка
- Идемпотентность операций

### ☠️ Dead Letter Queue
- Обработка неудачных событий
- Предотвращение потери данных
- Мониторинг проблем системы

## 🗂️ Структура проекта

```
pizza-order-system/
├── services/
│   ├── frontend/              # 🍕 Frontend Service
│   ├── order/                 # 📦 Order Service  
│   ├── payment/               # 💳 Payment Service
│   ├── notification/          # 📧 Notification Service
│   └── payment-mock/          # 🏦 Payment Provider Mock
├── infrastructure/
│   ├── nginx/                 # 🚪 API Gateway
│   ├── kafka/                 # 🔄 Message Broker
│   ├── monitoring/            # 📊 Prometheus + Grafana
│   └── databases/             # 🗄️ PostgreSQL схемы
├── ui/                        # 💻 Web Interface
├── docker-compose.yml         # 🐳 Инфраструктура
└── README.md                  # 📖 Документация
```

## 🔧 Разработка

### Локальная разработка

```bash
# Запуск только инфраструктуры
docker-compose up -d postgres kafka zookeeper

# Установка зависимостей для разработки
pip install -r requirements-dev.txt

# Запуск отдельного сервиса
cd services/order
python app.py
```

### Логирование

Все сервисы используют структурированное логирование:

```python
import logging
logger = logging.getLogger(__name__)

logger.info("Order created", extra={
    "order_id": order_id,
    "user_id": user_id, 
    "total": total,
    "event_type": "order_created"
})
```

## 🎓 Образовательные сценарии

### Happy Path
1. Создание заказа → успешная оплата → уведомление
2. Наблюдение событий в Kafka
3. Мониторинг метрик в Grafana

### Failure Scenarios  
1. Сбой Payment Service → retry → DLQ
2. Перегрузка системы → circuit breaker
3. Сетевые проблемы → eventual consistency

### Load Testing
```bash
# Генерация нагрузки
ab -n 1000 -c 10 http://localhost/api/v1/menu
```

## 🚨 Troubleshooting

### Общие проблемы

**Сервис не запускается:**
```bash
docker-compose logs <service-name>
```

**Kafka не подключается:**
```bash
# Проверить топики
docker exec kafka kafka-topics --list --bootstrap-server localhost:9092
```

**База данных недоступна:**
```bash
# Проверить подключение
docker exec postgres psql -U pizza_user -d pizza_db -c "SELECT 1;"
```

## 📈 Производительность

### Ожидаемые показатели
- **Throughput**: 1000+ заказов/мин
- **Latency**: < 100ms для создания заказа
- **Availability**: 99.9% uptime
- **Recovery Time**: < 30 секунд

### Масштабирование
```bash
# Масштабирование Order Service
docker-compose up -d --scale order-service=3

# Мониторинг распределения нагрузки
docker-compose logs nginx | grep order-service
```

## 🤝 Участие в разработке

1. Fork репозитория
2. Создайте feature branch
3. Добавьте тесты для новой функциональности  
4. Убедитесь что все тесты проходят
5. Создайте Pull Request

---

**Автор**: Vladimir Pizza Team  
**Лицензия**: MIT  
**Версия**: 1.0.0 