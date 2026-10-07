# 🍕 Pizza Order System — EDA Lab

Учебный стенд для изучения **Event-Driven Architecture (EDA)** на примере распределённой системы обработки заказов.

Стенд показывает, как несколько микросервисов взаимодействуют **через события**, как данные проходят через Kafka, как используется **Outbox Pattern**, почему возникает **Eventual Consistency** и как система ведёт себя под нагрузкой.

Observability в этом стенде используется как второй уровень обучения: после изучения EDA вы можете наблюдать, что происходит с событиями, сервисами, Kafka, PostgreSQL и инфраструктурой с помощью Prometheus, Grafana и других инструментов.

---

# 1. Что вы изучаете

Главная тема стенда — **Event-Driven Architecture**.

Вы изучаете:

- взаимодействие микросервисов через события;
- Apache Kafka как транспорт событий;
- слабую связанность сервисов;
- асинхронную обработку;
- Eventual Consistency;
- Outbox Pattern;
- обработку событий несколькими consumer'ами;
- идемпотентность и повторную обработку;
- retry и Dead Letter Queue;
- поведение распределённой системы под нагрузкой;
- observability как способ понять, что происходит внутри EDA-системы.

Главная идея:

> **Сервис не должен ждать прямого ответа от каждого следующего сервиса. Он публикует событие, а заинтересованные сервисы самостоятельно реагируют на него.**

---

# 2. Что такое EDA в этом стенде

В обычной синхронной архитектуре цепочка могла бы выглядеть так:

```text
Frontend
   ↓
Order Service
   ↓
Payment Service
   ↓
Notification Service
```

В нашем стенде основное взаимодействие построено иначе:

```text
Frontend
   ↓
Order Service
   ↓
Kafka
   ↓
Payment Service
   ↓
Kafka
   ↓
Order Service / Notification Service
```

Order Service не должен напрямую вызывать Payment Service для каждого изменения состояния заказа.

Вместо этого он создаёт событие:

```text
OrderCreated
```

Kafka доставляет это событие подписанным consumer'ам.

Payment Service получает `OrderCreated`, обрабатывает платеж и публикует:

```text
PaymentCompleted
```

После этого другие сервисы реагируют на новое событие.

Получается распределённая цепочка:

```text
OrderCreated
     ↓
 ┌───┴───────────────┐
 ↓                   ↓
Payment          Notification
 ↓
PaymentCompleted
 ↓
 ┌───────────────────┐
 ↓                   ↓
Order            Notification
 ↓
OrderPaid
```

---

# 3. Архитектура стенда

```text
                         ┌─────────────────────┐
                         │   Главная страница  │
                         │      Pizza Saga     │
                         └──────────┬──────────┘
                                    │
                                    ▼
                              ┌───────────┐
                              │   Nginx   │
                              │   :80     │
                              └─────┬─────┘
                                    │
                                    ▼
                           ┌─────────────────┐
                           │ Frontend Service│
                           │     :5000       │
                           └────────┬────────┘
                                    │
                                    ▼
                           ┌─────────────────┐
                           │  Order Service  │
                           │      :5001      │
                           └───────┬─────────┘
                                   │
                         ┌─────────┴─────────┐
                         │     PostgreSQL    │
                         │       :5433       │
                         └─────────┬─────────┘
                                   │
                              Outbox Events
                                   │
                                   ▼
                           ┌─────────────────┐
                           │      Kafka      │
                           │      :29092     │
                           └───────┬─────────┘
                                   │
                  ┌────────────────┼────────────────┐
                  │                │                │
                  ▼                ▼                ▼
           ┌─────────────┐  ┌─────────────┐  ┌────────────────┐
           │   Payment   │  │    Order    │  │ Notification   │
           │   Service   │  │   Service   │  │    Service     │
           │    :5002    │  │    :5001    │  │     :5004      │
           └──────┬──────┘  └─────────────┘  └────────────────┘
                  │
                  ▼
           ┌─────────────┐
           │ Payment Mock│
           │    :5003    │
           └─────────────┘


                 EDA + Observability
        ┌─────────────────────────────────────┐
        │ Prometheus :9090                    │
        │ Grafana :3000                       │
        │ Kafka Exporter :9308                │
        │ PostgreSQL Exporter :9187           │
        │ Nginx Exporter :9113                │
        │ cAdvisor :8083                      │
        │ Node Exporter :9100                 │
        └─────────────────────────────────────┘

        ┌─────────────────────────────────────┐
        │ Kafka UI :18080                     │
        │ pgAdmin :8081                       │
        └─────────────────────────────────────┘
```

---

# 4. Жизненный цикл заказа как цепочка событий

Это центральная часть лабораторной работы.

## Шаг 1. Создание заказа

Пользователь создаёт заказ через интерфейс.

Order Service одновременно выполняет бизнес-операцию и сохраняет событие в Outbox:

```text
orders
order_items
outbox_events
```

Важное событие:

```text
OrderCreated
```

---

## Шаг 2. Outbox публикует событие в Kafka

Фоновый **Outbox Processor** выбирает ещё не опубликованные события из PostgreSQL и отправляет их в Kafka.

```text
PostgreSQL
    ↓
outbox_events
    ↓
Outbox Processor
    ↓
Kafka
    ↓
order-events
```

Это позволяет не делать ненадёжную последовательность:

```text
сначала сохранить заказ
потом попытаться отправить событие
```

Событие сначала надёжно фиксируется в базе в рамках той же транзакции, что и бизнес-изменение.

---

## Шаг 3. Payment Service получает OrderCreated

Payment Service подписан на `order-events`.

Получив `OrderCreated`, он:

1. создаёт платёж;
2. вызывает Payment Mock;
3. получает результат;
4. обновляет состояние платежа;
5. формирует новое событие.

При успешной оплате появляется:

```text
PaymentCompleted
```

---

## Шаг 4. PaymentCompleted снова попадает в Kafka

Теперь Kafka становится центральной шиной, через которую событие получает несколько потребителей.

```text
PaymentCompleted
        ↓
   ┌────┴─────┐
   ↓          ↓
 Order     Notification
Service       Service
```

Order Service изменяет статус заказа.

Notification Service создаёт уведомление.

---

## Шаг 5. Событие OrderPaid

После обработки успешной оплаты Order Service изменяет состояние заказа и создаёт ещё одно событие:

```text
OrderPaid
```

Таким образом, одно бизнес-действие вызывает цепочку независимых событий.

---

# 5. Kafka как основа взаимодействия

Kafka в этом стенде — не просто технический компонент.

Это **центральная шина событий EDA-архитектуры**.

Основные топики:

```text
order-events
payment-events
notification-events
dlq-events
```

Пример логики:

```text
Order Service
     │
     │ OrderCreated
     ▼
order-events
     │
     ├──────────────► Payment Service
     │
     └──────────────► Notification Service


Payment Service
     │
     │ PaymentCompleted
     ▼
payment-events
     │
     ├──────────────► Order Service
     │
     └──────────────► Notification Service
```

В Kafka UI вы можете увидеть уже не график, а **реальные сообщения событий**.

---

# 6. Почему здесь используется Outbox Pattern

Одна из главных проблем EDA:

> Что произойдёт, если база сохранила заказ, но отправка события в Kafka не удалась?

Без Outbox можно получить:

```text
База:
заказ создан ✅

Kafka:
события нет ❌
```

В итоге остальные сервисы никогда не узнают о заказе.

Outbox меняет этот подход:

```text
┌─────────────────────────────────────┐
│ PostgreSQL transaction              │
│                                     │
│ orders            → сохранён ✅     │
│ order_items       → сохранены ✅    │
│ outbox_events     → сохранено ✅    │
└─────────────────────────────────────┘
                    │
                    ▼
             Outbox Processor
                    │
                    ▼
                  Kafka
```

Поэтому бизнес-данные и событие сначала фиксируются надёжно, а публикация события выполняется отдельным процессом.

---

# 7. Eventual Consistency

В этой архитектуре изменения не обязаны одновременно появляться во всех сервисах.

Например:

```text
t0   Order Service создаёт заказ
 ↓
t1   OrderCreated попадает в Kafka
 ↓
t2   Payment Service создаёт платёж
 ↓
t3   PaymentCompleted попадает в Kafka
 ↓
t4   Order Service получает событие
 ↓
t5   заказ получает статус PAID
```

Между этими моментами может существовать временное расхождение состояния.

Это и есть **Eventual Consistency**:

> данные системы сходятся к согласованному состоянию по мере обработки событий.

Во время нагрузки это особенно хорошо видно через Kafka consumer lag и метрики сервисов.

---

# 8. Сервисы и их роль в EDA

| Сервис | Роль |
|---|---|
| **Frontend Service** | Интерфейс и создание нагрузки |
| **Order Service** | Создание и изменение заказов, публикация бизнес-событий |
| **Outbox Processor** | Передача событий из PostgreSQL в Kafka |
| **Payment Service** | Реакция на OrderCreated и обработка платежа |
| **Payment Mock** | Имитация внешней платёжной системы |
| **Notification Service** | Реакция на события и отправка уведомлений |
| **Kafka** | Асинхронная передача событий |
| **PostgreSQL** | Хранение бизнес-данных и Outbox |

---

# 9. Основные EDA-паттерны в стенде

## Event-Driven Architecture

Сервисы обмениваются событиями вместо построения жёсткой цепочки синхронных вызовов.

## Publish / Subscribe

Один сервис публикует событие, а несколько consumer'ов могут реагировать на него независимо.

## Outbox Pattern

Событие сохраняется вместе с бизнес-изменением в транзакции БД, после чего отдельный процесс публикует его в Kafka.

## Eventual Consistency

Состояние распределённой системы становится согласованным постепенно.

## Idempotency

Повторная обработка одного события не должна приводить к некорректному повторному бизнес-действию.

## Retry

Временные ошибки обработки могут приводить к повторной попытке.

## Dead Letter Queue

Проблемные сообщения могут быть отправлены в отдельный поток для дальнейшего анализа.

---

# 10. Основной сценарий лабораторной работы

Работайте со стендом в следующем порядке:

1. Запустите Docker Compose.
2. Откройте главную страницу.
3. Создайте обычный заказ и убедитесь, что система работает.
4. Откройте Kafka UI и найдите события.
5. Проследите цепочку `OrderCreated → PaymentCompleted → OrderPaid`.
6. Запустите **«Нагрузочный тест 1000 RPS»**.
7. Посмотрите, как изменяется поток событий в Kafka.
8. Откройте Grafana и наблюдайте, как нагрузка влияет на сервисы и инфраструктуру.
9. При необходимости проверьте исходные метрики в Prometheus.
10. Откройте pgAdmin и сравните события с реальными данными PostgreSQL.

Главная задача — **связать архитектурное событие с его фактическим поведением в системе**.

---

# 11. Нагрузочный тест 1000 RPS

На главной странице доступна кнопка:

**⚡ Нагрузочный тест 1000 RPS**

Тест создаёт контролируемую нагрузку примерно на одну минуту.

Идея эксперимента:

```text
1000 HTTP requests/s
        ↓
   Order Service
        ↓
    PostgreSQL
        ↓
      Outbox
        ↓
      Kafka
        ↓
 Payment / Notification
```

При этом вы можете одновременно наблюдать:

```text
HTTP Rate
Kafka message rate
Consumer lag
Database activity
CPU
Memory
Latency
Errors
```

То есть одна нагрузка позволяет увидеть, как **EDA-цепочка ведёт себя в реальной распределённой системе**.

---

# 12. Observability: второй уровень лаборатории

После того как вы разобрались с EDA-потоком, можно исследовать его поведение через observability.

Здесь используются:

- Prometheus;
- Grafana;
- Kafka Exporter;
- PostgreSQL Exporter;
- Nginx Exporter;
- cAdvisor;
- Node Exporter;
- Kafka UI;
- pgAdmin.

Важно различать их назначение:

```text
Kafka UI
    ↓
Реальные события и offsets

pgAdmin
    ↓
Реальные данные PostgreSQL

Prometheus
    ↓
Исходные метрики

Grafana
    ↓
Графики и визуальный анализ

cAdvisor / Node Exporter
    ↓
Ресурсы контейнеров и хоста
```

---

# 13. Grafana

Адрес:

**http://localhost:3000**

Логин:

```text
admin
```

Пароль:

```text
admin
```

Grafana нужна для ответа на вопрос:

> **Что происходит с EDA-системой под нагрузкой?**

Основные dashboards:

| Dashboard | UID | Что показывает |
|---|---|---|
| Overview | `overview` | Общее состояние системы и поток нагрузки |
| Kafka | `kafka` | Kafka traffic, lag и состояние брокера |
| Services | `services` | Работа микросервисов |
| PostgreSQL | `database` | Состояние базы |
| Infrastructure | `infrastructure` | Ресурсы инфраструктуры |
| RED | `red-metrics` | Rate, Errors, Duration |
| USE | `use-metrics` | Utilization, Saturation, Errors |
| LTES | `ltes-metrics` | Latency, Traffic, Errors, Saturation |
| CPU by Service | `cpu-by-service` | Сравнение нагрузки на контейнеры |

---

# 14. Kafka UI

Адрес:

**http://localhost:18080**

Kafka UI позволяет посмотреть:

- топики;
- messages;
- partitions;
- offsets;
- consumer groups;
- consumer lag.

Это особенно важно для EDA.

Grafana может показать:

```text
Kafka traffic ↑
```

А Kafka UI позволяет увидеть:

```text
OrderCreated
PaymentCompleted
OrderPaid
...
```

То есть вы можете перейти от **агрегированной метрики** к **конкретному событию**.

---

# 15. PostgreSQL и pgAdmin

pgAdmin:

**http://localhost/pgadmin/**

Логин:

```text
pgadmin@pgadmin.org
```

Пароль:

```text
admin
```

Подключение к БД:

```text
Host: host.docker.internal
Port: 5433
Database: pizza_system
User: pizza_user
Password: pizza_password
```

В PostgreSQL особенно важно исследовать:

- `orders`;
- `order_items`;
- `outbox_events`;
- `payments`;
- `payment_attempts`;
- `notifications`.

Таблица `outbox_events` позволяет напрямую увидеть механизм Outbox Pattern.

---

# 16. Prometheus

Адрес:

**http://localhost:9090**

Prometheus хранит исходные метрики, которые затем визуализируются в Grafana.

Полезные проверки:

```promql
up
```

```promql
up{job="node-exporter"}
```

```promql
node_load1
```

```promql
node_memory_MemTotal_bytes
```

HTTP traffic:

```promql
sum(rate(http_requests_total{service!=""}[5m]))
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

# 17. RED и USE как инструменты анализа EDA

## RED

**Rate — Errors — Duration**

Помогает понять, что происходит с сервисами:

```text
Rate
 ↓
сколько запросов проходит

Errors
 ↓
сколько запросов завершается ошибкой

Duration
 ↓
сколько времени занимает обработка
```

## USE

**Utilization — Saturation — Errors**

Помогает понять, хватает ли инфраструктурных ресурсов:

```text
CPU
RAM
Load Average
IO Wait
Paging
OOM
```

Таким образом:

```text
EDA-архитектура
      ↓
нагрузка на события
      ↓
поведение сервисов
      ↓
поведение Kafka
      ↓
поведение PostgreSQL
      ↓
поведение инфраструктуры
```

---

# 18. Как проследить одно событие через всю систему

Например, для `OrderCreated`:

```text
1. Пользователь создаёт заказ
          ↓
2. Order Service
          ↓
3. orders + order_items
          ↓
4. outbox_events
          ↓
5. Outbox Processor
          ↓
6. Kafka / order-events
          ↓
7. Payment Service
          ↓
8. Payment Mock
          ↓
9. PaymentCompleted
          ↓
10. Kafka / payment-events
          ↓
11. Order Service
          ↓
12. OrderPaid
          ↓
13. Notification Service
```

Для каждого шага можно задать вопрос:

> **Где сейчас находится событие и какой компонент должен обработать его следующим?**

Это один из ключевых навыков работы с EDA.

---

# 19. Что происходит при задержках и перегрузке

Под нагрузкой события могут обрабатываться медленнее, чем поступают.

Например:

```text
Producer
  │
  │ 1000 events/s
  ▼
Kafka
  │
  │ 700 events/s
  ▼
Consumer
```

Тогда появляется:

```text
Consumer Lag ↑
```

Это позволяет увидеть принципиальную особенность асинхронной архитектуры:

> Producer и Consumer могут работать с разной скоростью.

Вместо мгновенного отказа системы может возникнуть **очередь необработанных событий**.

---

# 20. Диагностика EDA-проблемы

Не начинайте диагностику только с CPU.

Сначала определите, что происходит с самим потоком событий.

Рекомендуемый порядок:

### 1. Главная страница

Проверить, что нагрузка действительно запускается.

### 2. Kafka UI

Проверить:

- приходят ли события;
- какие топики растут;
- меняются ли offsets;
- работают ли consumer groups.

### 3. Grafana Kafka

Проверить:

- message rate;
- consumer lag;
- состояние Kafka.

### 4. Grafana Services / RED

Проверить:

- какой сервис получает нагрузку;
- latency;
- ошибки;
- rate.

### 5. PostgreSQL

Проверить:

- запросы;
- подключения;
- активность базы;
- Outbox.

### 6. USE / Infrastructure

Проверить:

- CPU;
- RAM;
- Load Average;
- saturation.

### 7. Prometheus

Подтвердить вывод конкретными исходными метриками.

---

# 21. Доступы и порты

| Компонент | Порт | Назначение |
|---|---:|---|
| Главная страница / Nginx | 80 | Основной вход |
| Frontend Service | 5000 | Интерфейс и нагрузка |
| Order Service | 5001 | Заказы |
| Payment Service | 5002 | Платежи |
| Payment Mock | 5003 | Внешняя платёжная система |
| Notification Service | 5004 | Уведомления |
| PostgreSQL | 5433 | База данных |
| Prometheus | 9090 | Метрики |
| Grafana | 3000 | Визуализация |
| pgAdmin | 8081 | PostgreSQL UI |
| Kafka UI | 18080 | Kafka UI |
| Node Exporter | 9100 | Метрики хоста |
| cAdvisor | 8083 | Метрики контейнеров |
| PostgreSQL Exporter | 9187 | Метрики PostgreSQL |
| Kafka Exporter | 9308 | Метрики Kafka |
| Nginx Exporter | 9113 | Метрики Nginx |

---

# 22. Запуск стенда

Требования:

- Docker;
- Docker Compose;
- Git.

Клонирование:

```bash
git clone https://github.com/char1ks/pizza_logs-.git
cd pizza_logs-
```

Запуск:

```bash
docker compose up -d
```

Проверка:

```bash
docker compose ps
```

Логи:

```bash
docker compose logs -f
```

---

# 23. Полезные команды

Проверка контейнеров:

```bash
docker compose ps
```

Логи Order Service:

```bash
docker logs order-service --tail 100
```

Логи Kafka:

```bash
docker logs kafka --tail 100
```

Логи Outbox Processor:

```bash
docker logs order-outbox-processor --tail 100
```

Логи Payment Service:

```bash
docker logs payment-service --tail 100
```

Проверка PostgreSQL:

```bash
docker exec postgres pg_isready -U pizza_user -d pizza_system
```

Проверка Node Exporter:

```bash
curl http://localhost:9100/metrics
```

---

# 24. Что вы должны понять после работы со стендом

После выполнения лабораторной работы вы должны понимать:

**Почему сервисам не обязательно напрямую вызывать друг друга.**

**Как Kafka используется как шина событий.**

**Как одно событие может запускать обработку сразу в нескольких сервисах.**

**Зачем нужен Outbox Pattern.**

**Почему в распределённой системе возникает Eventual Consistency.**

**Что происходит, когда consumer не успевает обрабатывать события.**

**Как появляется consumer lag.**

**Как обрабатывать ошибки, retry и DLQ.**

**Как связать архитектурное событие с реальными данными PostgreSQL.**

**Как с помощью observability определить, почему EDA-система деградирует под нагрузкой.**

---

# 25. Главное, что нужно увидеть в лабораторной работе

Не воспринимайте этот стенд как набор отдельных инструментов.

Это одна система:

```text
                  EDA
                   │
        ┌──────────┴──────────┐
        │                     │
      Kafka               PostgreSQL
        │                     │
        │                  Outbox
        │                     │
        └─────────┬───────────┘
                  │
             Microservices
                  │
        ┌─────────┴─────────┐
        │                   │
     Payment          Notification
        │                   │
        └──────────┬────────┘
                   │
              Observability
                   │
       ┌───────────┼───────────┐
       │           │           │
   Prometheus   Grafana     Exporters
```

Сначала вы изучаете **как система взаимодействует через события**.

Затем смотрите **как эта архитектура ведёт себя под нагрузкой**.

И только после этого используете observability, чтобы объяснить увиденное.

---

# 26. Документация проекта

Дополнительные материалы находятся в:

- `docs/message_flow.md` — подробный поток событий;
- `docs/data_models.md` — модели данных и структуры событий;
- `docs/pizza-system-architecture.mmd` — архитектурная схема;
- `docs/c4_architecture.svg` — C4-архитектура;
- `docs/er_diagram.svg` — ER-диаграмма.

Исходный код сервисов:

- `services/frontend/`
- `services/order/`
- `services/payment/`
- `services/payment-mock/`
- `services/notification/`

Мониторинг:

- `infrastructure/monitoring/prometheus.yml`
- `infrastructure/monitoring/alert_rules.yml`
- `infrastructure/monitoring/grafana/`

---

# Итог

**Pizza Order System — это прежде всего учебный стенд по EDA.**

Kafka, Outbox, события, асинхронное взаимодействие, Eventual Consistency и взаимодействие микросервисов — это основа стенда.

Prometheus, Grafana, Kafka UI, pgAdmin, cAdvisor и Node Exporter нужны для того, чтобы вы могли **увидеть, измерить и объяснить поведение этой EDA-системы**.

Финальная цепочка лабораторной работы:

```text
EDA
 ↓
Events
 ↓
Kafka
 ↓
Microservices
 ↓
Outbox
 ↓
Eventual Consistency
 ↓
Load
 ↓
Observability
 ↓
Analysis
```
