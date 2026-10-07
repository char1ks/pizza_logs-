# 🍕 Pizza Order System — Monitoring Lab

Учебный стенд для изучения **мониторинга, наблюдаемости и поведения распределённой системы** под нагрузкой.

Вам не нужно разбираться в исходном коде сервисов или вручную вызывать API. Основной сценарий работы:

**запустить стенд → открыть главную страницу → запустить нагрузочный тест → наблюдать изменения в Kafka, PostgreSQL, Prometheus, Grafana, cAdvisor и Node Exporter.**

---

## 1. Что вы изучаете

Стенд показывает, как одна нагрузка проходит через несколько компонентов распределённой системы и как это отражается в разных системах мониторинга.

Во время работы можно увидеть:

- HTTP-трафик и задержки;
- ошибки 5xx;
- загрузку CPU и памяти;
- Load Average;
- работу Docker-контейнеров;
- работу PostgreSQL;
- сообщения и consumer lag в Kafka;
- бизнес-события заказов и платежей;
- связь между нагрузкой, метриками и фактическими событиями.

Главная идея:

> **Не просто увидеть, что система работает медленно, а определить, где именно появилась проблема и чем она вызвана.**

---

# 2. Архитектура стенда

Система состоит из нескольких сервисов и инфраструктурных компонентов.

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
                         ┌──────────┴──────────┐
                         ▼                     ▼
                ┌────────────────┐     ┌───────────────┐
                │ Frontend       │     │ Order Service │
                │ :5000          │     │ :5001         │
                └────────────────┘     └───────┬───────┘
                                               │
                                               ▼
                                          ┌─────────┐
                                          │  Kafka  │
                                          │ :29092  │
                                          └────┬────┘
                                               │
                             ┌─────────────────┼─────────────────┐
                             ▼                 ▼                 ▼
                       Payment Service   Order Service    Notification
                           :5002             :5001           :5004
                             │
                             ▼
                       Payment Mock
                           :5003

                ┌────────────────────────────────────┐
                │           PostgreSQL :5433         │
                └────────────────────────────────────┘

                ┌────────────────────────────────────┐
                │          Monitoring Stack           │
                │                                    │
                │ Prometheus :9090                   │
                │ Grafana :3000                      │
                │ cAdvisor :8083                     │
                │ Node Exporter :9100                │
                │ PostgreSQL Exporter :9187          │
                │ Kafka Exporter :9308               │
                │ Nginx Exporter :9113               │
                └────────────────────────────────────┘

                ┌────────────────────────────────────┐
                │ Kafka UI :18080                    │
                │ pgAdmin :8081                      │
                └────────────────────────────────────┘
```

---

# 3. Основной сценарий работы

Вы работаете по следующему сценарию:

1. Запускает Docker Compose.
2. Открывает главную страницу Pizza Saga.
3. Проверяет, что сервисы запущены.
4. Запускает **«Нагрузочный тест 1000 RPS»**.
5. Открывает Kafka UI и смотрит события.
6. Открывает Grafana и наблюдает изменение метрик.
7. При необходимости открывает Prometheus и проверяет исходные метрики.
8. В pgAdmin смотрит реальные данные PostgreSQL.
9. В cAdvisor и Node Exporter смотрит использование ресурсов.

Нагрузочный тест запускается на **1000 запросов в секунду примерно на 1 минуту**.

Параметр процента ошибок можно изменить в настройках тестирования на главной странице.

---

# 4. Запуск стенда

## Требования

Нужны:

- Docker
- Docker Compose
- Git

## Запуск

Клонировать репозиторий:

```bash
git clone https://github.com/char1ks/pizza_logs-.git
cd pizza_logs-
```

Запустить весь стенд:

```bash
docker compose up -d
```

Проверить состояние:

```bash
docker compose ps
```

Все основные контейнеры должны находиться в состоянии `Up`, а сервисы с healthcheck — в состоянии `healthy`.

Для просмотра логов:

```bash
docker compose logs -f
```

---

# 5. Главная страница

Локально:

**http://localhost/**

На главной странице находятся ссылки на все инструменты мониторинга.

Главная страница также содержит кнопку:

**⚡ Нагрузочный тест 1000 RPS**

Именно её следует использовать для создания контролируемой нагрузки.

Во время теста один и тот же поток нагрузки должен отражаться сразу в нескольких системах.

---

# 6. Доступы и учётные данные

## Grafana

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

Grafana используется для анализа готовых дашбордов.

---

## Prometheus

Адрес:

**http://localhost:9090**

Авторизация не требуется.

Prometheus используется для проверки исходных метрик и выполнения PromQL-запросов.

---

## Kafka UI

Адрес:

**http://localhost:18080**

Авторизация не требуется.

Kafka UI используется для просмотра:

- топиков;
- сообщений;
- partition;
- offsets;
- consumer groups.

---

## pgAdmin

Открывать через:

**http://localhost/pgadmin/**

Логин:

```text
pgadmin@pgadmin.org
```

Пароль:

```text
admin
```

В pgAdmin автоматически должен быть доступен сервер:

**Pizza System Database**

Для подключения к PostgreSQL используется:

```text
Host: host.docker.internal
Port: 5433
Database: pizza_system
User: pizza_user
Password: pizza_password
```

---

## PostgreSQL

Параметры подключения:

```text
Host: localhost
Port: 5433
Database: pizza_system
User: pizza_user
Password: pizza_password
```

Внутри pgAdmin используется host gateway:

```text
host.docker.internal:5433
```

---

# 7. Порты стенда

| Компонент | Порт | Назначение |
|---|---:|---|
| Главная страница / Nginx | 80 | Основной вход |
| Frontend Service | 5000 | Сервис каталога и запуска нагрузки |
| Order Service | 5001 | Работа с заказами |
| Payment Service | 5002 | Обработка платежей |
| Payment Mock | 5003 | Тестовый платёжный провайдер |
| Notification Service | 5004 | Уведомления |
| PostgreSQL | 5433 | База данных |
| Prometheus | 9090 | Сбор и хранение метрик |
| Grafana | 3000 | Визуализация метрик |
| pgAdmin | 8081 | Администрирование PostgreSQL |
| Kafka UI | 18080 | Просмотр Kafka |
| Node Exporter | 9100 | Метрики хоста |
| cAdvisor | 8083 | Метрики Docker-контейнеров |
| PostgreSQL Exporter | 9187 | Метрики PostgreSQL |
| Kafka Exporter | 9308 | Метрики Kafka |
| Nginx Exporter | 9113 | Метрики Nginx |

---

# 8. Grafana

Grafana — основной инструмент для визуального анализа.

В стенде используются несколько специализированных экранов.

## Overview — обзор системы

UID:

`overview`

Используется как первая точка диагностики.

Здесь можно увидеть:

- доступность сервисов;
- HTTP-трафик;
- долю 5xx;
- P95 latency;
- Kafka traffic;
- consumer lag;
- количество заказов;
- количество платежей.

Рекомендуемый вопрос:

> **В системе вообще есть проблема или всё работает нормально?**

---

## Kafka

UID:

`kafka`

Показывает:

- состояние Kafka;
- количество брокеров;
- топики;
- partition;
- consumer groups;
- consumer lag;
- поток сообщений;
- under-replicated partitions.

После запуска нагрузки здесь должен быть заметен рост Kafka activity.

Основные топики:

```text
order-events
payment-events
notification-events
dlq-events
```

---

## Services

UID:

`services`

Используется для поиска конкретного проблемного микросервиса.

Показывает:

- Rate;
- 5xx;
- P95;
- бизнес-события;
- CPU;
- память контейнеров.

Основной вопрос:

> **Какой сервис стал узким местом?**

---

## PostgreSQL

UID:

`database`

Показывает состояние базы данных:

- активные подключения;
- cache hit ratio;
- sequential scans;
- index scans;
- медленные SQL-запросы;
- бизнес-метрики заказов и платежей.

Основной вопрос:

> **Не стала ли база данных причиной деградации системы?**

---

## Infrastructure / Server

UID:

`infrastructure`

Показывает состояние самого хоста и инфраструктуры:

- CPU;
- RAM;
- disk;
- network;
- Load Average;
- Docker resources.

Основной вопрос:

> **Не упёрлась ли вся машина в ресурсы?**

---

# 9. USE Dashboard

UID:

`use-metrics`

USE означает:

**Utilization — Saturation — Errors**

На экране находятся:

### CPU Utilization

Показывает, насколько загружен CPU.

PromQL:

```promql
100 - (avg by (instance) (irate(node_cpu_seconds_total{mode="idle"}[5m])) * 100)
```

### CPU Saturation

Показывает Load Average:

```promql
node_load1
```

```promql
node_load5
```

```promql
node_load15
```

### CPU Errors

Показывает IO Wait:

```promql
rate(node_cpu_seconds_total{mode="iowait"}[5m]) * 100
```

### Memory Utilization

Показывает использование оперативной памяти:

```promql
(1 - (node_memory_MemAvailable_bytes / node_memory_MemTotal_bytes)) * 100
```

### Memory Saturation

Показывает paging:

```promql
rate(node_vmstat_pgpgin[5m])
```

```promql
rate(node_vmstat_pgpgout[5m])
```

### Memory Errors

Показывает OOM kills:

```promql
rate(node_vmstat_oom_kill[5m])
```

---

# 10. RED Dashboard

UID:

`red-metrics`

RED означает:

**Rate — Errors — Duration**

Это основной подход для анализа сервисов.

### Rate

Сколько запросов проходит через сервис.

### Errors

Сколько запросов завершилось ошибкой.

### Duration

Сколько времени занимает обработка.

Во время нагрузки вы можете наблюдать:

```text
1000 RPS
   ↓
Rate увеличивается
   ↓
CPU и DB activity увеличиваются
   ↓
Latency может увеличиваться
   ↓
при перегрузке могут появиться 5xx
```

---

# 11. LTES Dashboard

UID:

`ltes-metrics`

Используется для анализа:

- Latency;
- Traffic;
- Errors;
- Saturation.

Этот экран помогает связать пользовательский трафик с поведением внутренних компонентов системы.

---

# 12. CPU по сервисам

UID:

`cpu-by-service`

Этот экран нужен для сравнения контейнеров.

Можно увидеть, какой сервис потребляет больше CPU:

- frontend;
- order;
- payment;
- notification;
- другие контейнеры.

Основной вопрос:

> **Какой конкретно контейнер получает основную нагрузку?**

---

# 13. cAdvisor

Адрес:

**http://localhost:8083**

cAdvisor собирает метрики Docker-контейнеров.

Особенно полезен для анализа:

- CPU контейнера;
- памяти контейнера;
- количества контейнеров;
- поведения контейнеров под нагрузкой.

Связка выглядит так:

```text
Нагрузка
   ↓
Order Service CPU ↑
   ↓
cAdvisor фиксирует рост
   ↓
Prometheus собирает метрику
   ↓
Grafana показывает график
```

---

# 14. Node Exporter

Адрес:

**http://localhost:9100**

Node Exporter предоставляет Prometheus системные метрики хоста.

Основные группы:

- CPU;
- memory;
- load average;
- filesystem;
- network;
- VM statistics;
- kernel/system metrics.

Node Exporter отвечает именно за **машину**, а cAdvisor — за **Docker-контейнеры**.

---

# 15. Prometheus

Адрес:

**http://localhost:9090**

Prometheus — это технический источник метрик.

Grafana показывает данные, а Prometheus их собирает и хранит.

Полезные запросы для проверки:

### Проверить доступность targets

```promql
up
```

### Проверить Node Exporter

```promql
up{job="node-exporter"}
```

Ожидаемое значение:

```text
1
```

### Проверить Load Average

```promql
node_load1
```

### Проверить CPU

```promql
node_cpu_seconds_total
```

### Проверить память

```promql
node_memory_MemTotal_bytes
```

### Проверить HTTP-трафик сервисов

```promql
sum(rate(http_requests_total{service!=""}[5m]))
```

### Проверить Kafka traffic

```promql
sum(rate(kafka_messages_sent_total[5m]))
```

### Проверить Kafka lag

```promql
sum(kafka_consumergroup_lag_sum)
```

---

# 16. Почему Prometheus важен для вас

Prometheus позволяет проверить **реальное состояние системы**, а не только то, что показывает интерфейс.

Например:

Grafana показывает рост CPU.

Вы можете открыть Prometheus и проверить исходную метрику:

```promql
node_load1
```

или:

```promql
node_memory_MemAvailable_bytes
```

Это позволяет отличить реальную проблему от ошибки самого дашборда.

---

# 17. Kafka UI

Адрес:

**http://localhost:18080**

Kafka UI нужен, когда нужно посмотреть не агрегированную метрику, а **сами сообщения**.

Основные объекты:

### order-events

События жизненного цикла заказа.

### payment-events

События оплаты.

### notification-events

События для Notification Service.

### dlq-events

Сообщения, которые были направлены в Dead Letter Queue.

После запуска нагрузочного теста основное внимание следует обратить на:

- количество сообщений;
- скорость появления сообщений;
- offsets;
- consumer groups;
- lag.

---

# 18. PostgreSQL и pgAdmin

pgAdmin нужен не для графиков, а для просмотра **реальных данных базы**.

После подключения к:

```text
Pizza System Database
```

можно исследовать созданные схемы и таблицы.

В базе хранятся данные, необходимые для работы:

- заказов;
- позиций заказа;
- платежей;
- уведомлений;
- Outbox событий.

Таким образом:

**Grafana показывает состояние БД, а pgAdmin позволяет посмотреть, что физически находится в базе.**

---

# 19. Как одна нагрузка отображается во всех мониторингах

Когда вы нажимает:

**«Нагрузочный тест 1000 RPS»**

начинается реальный поток запросов.

Упрощённо:

```text
k6
 ↓
Nginx
 ↓
Order Service
 ↓
PostgreSQL
 ↓
Outbox
 ↓
Kafka
 ↓
Payment Service
 ↓
Kafka
 ↓
Notification Service
```

И параллельно мониторинг фиксирует изменения:

```text
HTTP запросы
   ↓
Prometheus
   ↓
Grafana RED / Overview

CPU и RAM
   ↓
Node Exporter / cAdvisor
   ↓
Prometheus
   ↓
Grafana USE / Infrastructure

Kafka messages
   ↓
Kafka Exporter / application metrics
   ↓
Prometheus
   ↓
Grafana Kafka

PostgreSQL activity
   ↓
PostgreSQL Exporter
   ↓
Prometheus
   ↓
Grafana PostgreSQL

Реальные Kafka events
   ↓
Kafka UI

Реальные записи БД
   ↓
pgAdmin
```

Поэтому во время теста вы должны видеть взаимосвязанную картину, а не один отдельный график.

---

# 20. Правильный порядок диагностики

Не нужно хаотично открывать все экраны.

Используйте последовательность:

### Шаг 1. Overview

Посмотреть:

- живы ли сервисы;
- есть ли трафик;
- появились ли 5xx;
- выросла ли latency;
- есть ли Kafka lag.

### Шаг 2. Services / RED

Определить:

- какой сервис получает нагрузку;
- какой сервис увеличил latency;
- какой сервис начал отдавать ошибки.

### Шаг 3. CPU / USE / Infrastructure

Проверить:

- не перегружен ли CPU;
- хватает ли RAM;
- вырос ли Load Average;
- есть ли paging или OOM.

### Шаг 4. Kafka

Проверить:

- появляются ли события;
- не растёт ли consumer lag;
- нет ли проблем с partitions;
- не появились ли DLQ события.

### Шаг 5. PostgreSQL

Проверить:

- подключения;
- запросы;
- cache hit ratio;
- scans;
- медленные запросы.

### Шаг 6. Prometheus

Проверить конкретную исходную метрику через PromQL.

### Шаг 7. Kafka UI / pgAdmin

Посмотреть фактические сообщения и данные.

---

# 21. Что должен уметь вы после работы со стендом

После прохождения задания вы должны уметь ответить на вопросы:

**Где находится нагрузка?**

**Какой сервис является узким местом?**

**Увеличился ли CPU?**

**Хватает ли памяти?**

**Появился ли Kafka lag?**

**Есть ли ошибки 5xx?**

**Увеличилась ли latency?**

**Не стала ли PostgreSQL узким местом?**

**Есть ли проблемы непосредственно на сервере?**

**Подтверждается ли проблема исходными метриками Prometheus?**

---

# 22. Полезные команды

Проверка всех контейнеров:

```bash
docker compose ps
```

Логи конкретного сервиса:

```bash
docker logs order-service --tail 100
```

Логи Kafka:

```bash
docker logs kafka --tail 100
```

Логи PostgreSQL:

```bash
docker logs postgres --tail 100
```

Логи Prometheus:

```bash
docker logs prometheus --tail 100
```

Логи Grafana:

```bash
docker logs grafana --tail 100
```

Проверка PostgreSQL:

```bash
docker exec postgres pg_isready -U pizza_user -d pizza_system
```

Проверка Node Exporter:

```bash
curl http://localhost:9100/metrics
```

Проверка Prometheus:

```text
http://localhost:9090
```

---

# 23. GitHub Codespaces

Стенд также рассчитан на запуск в GitHub Codespaces.

В Codespaces основная страница и инструменты мониторинга доступны через опубликованные Ports.

Используются порты:

```text
80      → главная страница
3000    → Grafana
9090    → Prometheus
18080   → Kafka UI
8081    → pgAdmin
8083    → cAdvisor
9100    → Node Exporter
```

Главная страница автоматически формирует ссылки на инструменты мониторинга для Codespaces.

---

# 24. Что делать, если Grafana показывает No data

Сначала открой Prometheus:

**http://localhost:9090**

Проверь:

```promql
up
```

Затем:

```promql
up{job="node-exporter"}
```

И:

```promql
node_load1
```

Если `node_load1` возвращает данные, Node Exporter и Prometheus работают, и проблему нужно искать в Grafana/datasource/dashboard.

Если данных нет уже в Prometheus, проблема находится раньше:

```text
Exporter → Prometheus
```

---

# 25. Главное правило лабораторной работы

Не делайте вывод только по одному экрану.

Например:

> «CPU высокий, значит виноват Order Service»

— это только гипотеза.

Нужно подтвердить её несколькими источниками:

```text
Grafana CPU
      +
cAdvisor
      +
Prometheus
      +
Services / RED
      +
Kafka
      +
PostgreSQL
```

Только после этого можно уверенно определить причину деградации.

---

# 26. Короткая схема инструментов

| Инструмент | Главный вопрос |
|---|---|
| **Grafana Overview** | Что сейчас происходит с системой? |
| **Grafana RED** | Как работают сервисы? |
| **Grafana USE** | Не перегружен ли сервер? |
| **Grafana Kafka** | Что происходит с Kafka? |
| **Grafana PostgreSQL** | Не тормозит ли база? |
| **Grafana CPU by Service** | Какой контейнер потребляет CPU? |
| **Prometheus** | Какие метрики реально собраны? |
| **Kafka UI** | Какие сообщения реально существуют? |
| **pgAdmin** | Какие данные реально лежат в БД? |
| **cAdvisor** | Какие ресурсы потребляют контейнеры? |
| **Node Exporter** | Что происходит с самим хостом? |

---

# 27. Итог

Этот стенд предназначен прежде всего для изучения **observability**.

Вы видите полный путь:

```text
Нагрузка
   ↓
Приложение
   ↓
HTTP
   ↓
PostgreSQL
   ↓
Outbox
   ↓
Kafka
   ↓
Другие сервисы
   ↓
Метрики
   ↓
Prometheus
   ↓
Grafana
```

И получает возможность посмотреть на одну и ту же проблему с разных уровней:

**сервисы → контейнеры → сервер → БД → Kafka → метрики → реальные данные.**

Это позволяет перейти от подхода **«система тормозит»** к подходу:

> **«Я вижу, где возникла деградация, какой компонент является причиной и какими метриками это подтверждается».**

---

## Документация проекта

Дополнительные материалы находятся в:

- `docs/data_models.md`
- `docs/message_flow.md`
- `docs/pizza-system-architecture.mmd`
- `docs/c4_architecture.svg`
- `docs/er_diagram.svg`

Исходный код сервисов находится в:

- `services/frontend/`
- `services/order/`
- `services/payment/`
- `services/payment-mock/`
- `services/notification/`

Мониторинг:

- `infrastructure/monitoring/prometheus.yml`
- `infrastructure/monitoring/alert_rules.yml`
- `infrastructure/monitoring/grafana/`
