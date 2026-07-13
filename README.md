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
