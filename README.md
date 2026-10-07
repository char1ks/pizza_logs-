# 🍕 Pizza Order System — EDA Lab

Учебный стенд для изучения **Event-Driven Architecture (EDA)** на примере распределённой системы обработки заказов.

Здесь вы изучаете, как микросервисы взаимодействуют через **события и Kafka**, зачем нужен **Outbox Pattern**, как работает **Eventual Consistency**, что происходит с системой под нагрузкой и как это наблюдать с помощью observability-инструментов.

> **Главная тема стенда — EDA. Observability используется, чтобы увидеть и объяснить поведение этой архитектуры.**

---

## 1. Что вы изучаете

Основные темы:

- Event-Driven Architecture и асинхронное взаимодействие;
- Kafka как шина событий;
- Publish/Subscribe;
- Outbox Pattern;
- Eventual Consistency;
- идемпотентность, retry и DLQ;
- взаимодействие нескольких микросервисов через события;
- поведение EDA-системы под нагрузкой.

Главный принцип:

```text
Сервис создаёт событие
        ↓
      Kafka
        ↓
Другие сервисы реагируют на событие
```

Сервисы не образуют одну длинную цепочку синхронных вызовов. Они реагируют на события независимо.

---

## 2. Архитектура системы

Основная архитектура уже подробно представлена в документации проекта:

![C4 Architecture](docs/c4_architecture.svg)

Также доступны [исходная Mermaid-схема архитектуры](docs/pizza-system-architecture.mmd) и [диаграмма потока сообщений](docs/message_flow.md).

Упрощённо основной EDA-поток выглядит так:

```text
Frontend
   ↓
Order Service
   ↓
PostgreSQL + Outbox
   ↓
Outbox Processor
   ↓
Kafka
   ├──→ Payment Service
   └──→ Notification Service
             ↓
       новые события
```

---

## 3. Жизненный цикл заказа

Центральный сценарий стенда:

```text
Создание заказа
      ↓
OrderCreated
      ↓
Kafka / order-events
      ├──────────────→ Payment Service
      │                       ↓
      │                PaymentCompleted
      │                       ↓
      └────────────────── Kafka
                              ├──→ Order Service
                              └──→ Notification Service
                                     
Order Service
      ↓
OrderPaid
```

То есть одно событие может запускать работу сразу нескольких компонентов.

Подробный flow находится в [docs/message_flow.md](docs/message_flow.md).

---

## 4. Outbox Pattern

При создании заказа Order Service сохраняет бизнес-данные и событие в одной транзакции:

```text
PostgreSQL transaction

orders
order_items
outbox_events
      ↓
    COMMIT
      ↓
Outbox Processor
      ↓
     Kafka
```

Это решает проблему, когда заказ уже сохранён в БД, а публикация события не состоялась.

В базе для изучения Outbox особенно важна таблица:

```text
orders.outbox_events
```

---

## 5. Eventual Consistency

Сервисы обновляют своё состояние не одновременно:

```text
t0  OrderCreated
 ↓
t1  событие опубликовано в Kafka
 ↓
t2  Payment Service обработал заказ
 ↓
t3  PaymentCompleted
 ↓
t4  Order Service получил событие
 ↓
t5  заказ стал PAID
```

Поэтому некоторое время разные части системы могут видеть разное состояние. Со временем состояние сходится.

Это особенно хорошо наблюдать через **Kafka consumer lag**.

---

## 6. Роли компонентов

| Компонент | Роль |
|---|---|
| **Frontend Service** | Интерфейс и запуск нагрузки |
| **Order Service** | Работа с заказами и событиями |
| **Outbox Processor** | Публикация Outbox-событий в Kafka |
| **Payment Service** | Обработка платежных событий |
| **Payment Mock** | Имитация внешней платёжной системы |
| **Notification Service** | Обработка событий и уведомления |
| **PostgreSQL** | Бизнес-данные и Outbox |
| **Kafka** | Асинхронная шина событий |

---

## 7. Kafka

Kafka — центральный элемент EDA-архитектуры.

Основные топики:

```text
order-events
payment-events
notification-events
dlq-events
```

В [Kafka UI](http://localhost:18080) вы можете увидеть:

- реальные события;
- partitions;
- offsets;
- consumer groups;
- consumer lag.

Например, после создания заказа можно проследить событие:

```text
OrderCreated
    ↓
PaymentCompleted
    ↓
OrderPaid
```

---

## 8. Нагрузка 1000 RPS

На главной странице есть кнопка:

**⚡ Нагрузочный тест 1000 RPS**

Она создаёт нагрузку примерно на одну минуту.

Во время теста смотрите, как один поток нагрузки проходит через EDA:

```text
HTTP
 ↓
Order Service
 ↓
PostgreSQL / Outbox
 ↓
Kafka
 ↓
Payment / Notification
```

И одновременно наблюдайте:

```text
HTTP Rate
Kafka Message Rate
Consumer Lag
Latency
Errors
CPU / Memory
PostgreSQL Activity
```

---

## 9. Observability

После понимания EDA используйте observability, чтобы исследовать её поведение.

| Инструмент | Что смотрите |
|---|---|
| **Grafana** | графики и состояние системы |
| **Prometheus** | исходные метрики и PromQL |
| **Kafka UI** | реальные сообщения и consumer groups |
| **pgAdmin** | реальные данные PostgreSQL и Outbox |
| **cAdvisor** | ресурсы Docker-контейнеров |
| **Node Exporter** | ресурсы хоста |
| **Kafka Exporter** | метрики Kafka |
| **PostgreSQL Exporter** | метрики PostgreSQL |
| **Nginx Exporter** | метрики Nginx |

Главный вопрос:

> **Что произошло с EDA-системой и почему?**

---

## 10. Grafana

Адрес: **http://localhost:3000**

Логин и пароль:

```text
Login:    admin
Password: admin
```

Основные dashboards:

| Dashboard | UID | Назначение |
|---|---|---|
| Overview | `overview` | общее состояние и нагрузка |
| Kafka | `kafka` | messages, lag, broker |
| Services | `services` | работа микросервисов |
| PostgreSQL | `database` | состояние БД |
| Infrastructure | `infrastructure` | ресурсы инфраструктуры |
| RED | `red-metrics` | Rate, Errors, Duration |
| USE | `use-metrics` | Utilization, Saturation, Errors |
| LTES | `ltes-metrics` | Latency, Traffic, Errors, Saturation |
| CPU by Service | `cpu-by-service` | CPU по контейнерам |

---

## 11. PostgreSQL

Подключение:

```text
Host:     localhost
Port:     5433
Database: pizza_system
User:     pizza_user
Password: pizza_password
```

Для pgAdmin:

```text
Host:     host.docker.internal
Port:     5433
Database: pizza_system
User:     pizza_user
Password: pizza_password
```

pgAdmin:

**http://localhost:8081**

Логин и пароль:

```text
Login:    pgadmin@pgadmin.org
Password: admin
```

ER-структура базы есть в документации:

![ER Diagram](docs/er_diagram.svg)

---

## 12. Prometheus

Адрес: **http://localhost:9090**

Проверка targets:

```promql
up
```

Проверка Node Exporter:

```promql
up{job="node-exporter"}
```

HTTP traffic:

```promql
sum(rate(http_requests_total{service!="\""}[5m]))
```

Kafka traffic:

```promql
sum(rate(kafka_messages_sent_total[5m]))
```

Consumer lag:

```promql
sum(kafka_consumergroup_lag_sum)
```

---

## 13. Запуск стенда

Требования:

- Docker;
- Docker Compose;
- Git.

Запуск:

```bash
git clone https://github.com/char1ks/pizza_logs-.git
cd pizza_logs-
docker compose up -d
```

Проверка:

```bash
docker compose ps
```

Главная страница:

**http://localhost/**

---

## 14. Рекомендуемый сценарий работы

1. Запустите стенд.
2. Создайте заказ.
3. Откройте Kafka UI.
4. Найдите `OrderCreated`.
5. Проследите обработку платежа и появление `PaymentCompleted`.
6. Проверьте изменение заказа в PostgreSQL.
7. Запустите нагрузку **1000 RPS**.
8. Посмотрите Kafka lag, latency, errors и ресурсы.
9. Сравните графики Grafana с реальными событиями Kafka и данными PostgreSQL.

---

## 15. Что должно остаться после лабораторной работы

Вы должны понимать:

- как устроена EDA;
- зачем нужна Kafka;
- как работает Publish/Subscribe;
- зачем нужен Outbox Pattern;
- почему возникает Eventual Consistency;
- как несколько сервисов реагируют на одно событие;
- почему producer и consumer могут работать с разной скоростью;
- откуда появляется consumer lag;
- как retry и DLQ влияют на обработку событий;
- как observability помогает объяснить поведение распределённой системы.

---

## Документация

- [Message Flow](docs/message_flow.md)
- [Data Models](docs/data_models.md)
- [C4 Architecture](docs/c4_architecture.svg)
- [ER Diagram](docs/er_diagram.svg)
- [Architecture Source](docs/pizza-system-architecture.mmd)

Исходный код сервисов:

- `services/frontend/`
- `services/order/`
- `services/payment/`
- `services/payment-mock/`
- `services/notification/`

Мониторинг:

- `infrastructure/monitoring/`
