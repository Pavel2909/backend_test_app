# Warehouse services

## Структура проекта

```
.
├── src/
│   ├── warehouse_common/           общий код сервисов
│   │   ├── settings.py             конфигурация из переменных окружения
│   │   ├── db.py                   схема БД (SQLAlchemy Core), движок asyncpg
│   │   ├── events.py               формат событий и каналы Redis
│   │   ├── broker.py               клиент Redis с повторами при обрыве соединения
│   │   ├── migrate.py              CLI миграций (warehouse-migrate)
│   │   └── migrations/             миграции Alembic
│   ├── inventory_api/              сервис 1: HTTP API (aiohttp)
│   │   ├── app.py                  сборка приложения
│   │   ├── handlers.py             HTTP-обработчики и обработка ошибок
│   │   ├── service.py              бизнес-логика: запись операции и публикация события
│   │   ├── repository.py           SQL-запросы остатков и аналитики
│   │   ├── publisher.py            публикация в Redis pub/sub
│   │   └── schemas.py              модели запросов и ответов
│   └── analytics_worker/           сервис 2: подписчик Redis pub/sub
│       ├── consumer.py             подписка, валидация событий, переподключение
│       └── repository.py           обновление агрегатов stock_agg
├── tests/                          тесты на реальных PostgreSQL и Redis
├── alembic.ini                     конфигурация Alembic для разработки
├── Dockerfile                      сборка wheel и образов runtime/test
├── docker-compose.yml
└── pyproject.toml
```

## Запуск

### Docker Compose

```bash
docker compose up --build -d
```

Поднимаются PostgreSQL, Redis, применяются миграции (`migrate`), стартуют `inventory_api` (http://localhost:8080) и `analytics_worker`.
Порты на хосте переопределяются через `POSTGRES_PORT`, `REDIS_PORT`, `API_PORT`.

```bash
curl -X POST localhost:8080/receipts -H "Content-Type: application/json" -d '{"sku": "A-100", "qty": 50, "warehouse": "WH-1"}'
curl -X POST localhost:8080/issues -H "Content-Type: application/json" -d '{"sku": "A-100", "qty": 20, "warehouse": "WH-1"}'
curl "localhost:8080/stock?warehouse=WH-1"
curl "localhost:8080/stock/summary?top_n=5"
```

### Тесты

В контейнере:

```bash
docker compose --profile test run --rm tests
```

Локально (PostgreSQL и Redis из compose):

```bash
docker compose up -d postgres redis
pip install -e ".[test]"
pytest
```

Подключение задаётся через `TEST_DATABASE_URL` и `TEST_REDIS_URL`; тестовая БД `inventory_test` создаётся автоматически.

### Запуск из wheel без Docker

Готовый `warehouse_services-0.1.0-py3-none-any.whl` приложен к релизу `v0.1.0` в GitHub Releases:

```bash
pip install warehouse_services-0.1.0-py3-none-any.whl
```

Или собрать из исходников:

```bash
python -m build --wheel
pip install dist/warehouse_services-0.1.0-py3-none-any.whl
```

Переменные окружения: `DATABASE_URL`, `REDIS_URL`, `API_HOST`, `API_PORT`, `DB_POOL_SIZE`, `LOG_LEVEL`.

```bash
warehouse-migrate upgrade head
inventory-api
analytics-worker
```

### Миграции

```bash
warehouse-migrate upgrade head
warehouse-migrate downgrade base
warehouse-migrate current
alembic revision --autogenerate -m "description"
```
