# Dividend Monitor

> Исходное описание репозитория: my bot for news.

Бесплатный пакетный Telegram-монитор публикаций компаний. Каждый запуск выполняет проверку источников, отправляет новые публикации и сохраняет историю в JSON. Постоянного сервера, polling-процесса и базы данных нет.

## Локальный запуск

Нужен Python 3.12.

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
pytest
ruff check .
```

Для реальной отправки задайте переменные окружения:

```powershell
$env:TELEGRAM_BOT_TOKEN = "..."
$env:TELEGRAM_CHAT_ID = "..."
dividend-monitor
```

Приложение завершится с понятной ошибкой, если переменная отсутствует. Её значение в ошибку не выводится.

Сейчас подключён только локальный RSS fixture из `tests/fixtures/news.xml`; реальные источники намеренно не добавлены.

## Тесты и качество

```powershell
pytest
ruff check .
```

Конфигурация компаний находится в `config/companies.yaml`, источников — в `config/sources.yaml`, состояние — в `data/state.json`.

## GitHub Actions usage

Проект использует два плановых workflow:

- `Dividend monitor` — один job каждые 30 минут (`7` и `37` минут каждого часа);
- `Daily portfolio summary` — один job в день в `08:17 UTC`.

Оба workflow работают на Ubuntu, не используют matrix jobs, Docker, artifacts или pip-кэш и завершаются сразу после запуска Python-приложения. Рабочие workflow устанавливают только runtime-зависимости из проекта. Dev-зависимости нужны только workflow `Tests`, который запускается при изменениях кода или вручную.

В конце каждого запуска в логе выводятся:

```text
Duration:
Sources:
New publications:
Telegram messages:
Errors:
```

Примерная оценка для месяца из 30 дней: основной workflow — `48 × 30 = 1440` запусков, ежедневный — ещё `30`, всего около `1470` job-запусков. Если каждый запуск занимает до одной минуты, это примерно `1470 runner-minutes` в месяц. Фактический расход зависит от длительности запусков и правил округления GitHub для конкретного типа репозитория и runner.
