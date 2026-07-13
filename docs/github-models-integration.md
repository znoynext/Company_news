# GitHub Models integration

## Current architecture

- **Стек:** Python 3.12, `httpx`, `feedparser`, BeautifulSoup, Pydantic и PyYAML; пакет устанавливается через `pyproject.toml` и запускается как `python -m dividend_monitor.runner`.
- **Точки входа:** `src/dividend_monitor/runner.py` выполняет один мониторинговый запуск; `daily_summary.py` отправляет ежедневную сводку. Оба запускаются только GitHub Actions: `.github/workflows/monitor.yml` по расписанию раз в час и вручную, `.github/workflows/daily-summary.yml` раз в сутки.
- **Фактический pipeline:** адаптеры в `src/dividend_monitor/sources/` получают RSS/HTML → нормализуют в `Publication` → `runner.py` извлекает контекст отчётов/дивидендов → `deduplication.is_new` сравнивает SHA-256 fingerprint с `sent_items` → новая публикация форматируется и отправляется через `TelegramClient` → `mark_sent` и статусы источников сохраняются в `data/state.json` → workflow коммитит только этот файл.
- **Состояние:** JSON без базы данных. `JsonStateStorage` делает атомарную локальную замену файла; общий `concurrency` в двух workflows не допускает одновременной записи.
- **Отправка:** Telegram Bot API вызывается из `telegram.py` с тайм-аутом, ограниченными повторами и HTML-экранированием.

## Problems found

1. До интеграции у проекта не было AI-слоя: `summarizer.py` только очищал и обрезал исходный текст, а важность оставалась заданной источником.
2. В `monitor.yml` отсутствовало минимально необходимое разрешение `models: read` и `GITHUB_TOKEN` не передавался приложению, поэтому GitHub Models было невозможно вызвать без отдельного ключа.
3. После успешной Telegram-отправки состояние попадает в Git только на финальном шаге workflow. Если runner упадёт между этими операциями, следующий запуск теоретически может повторить уже доставленную новость — ограничение архитектуры с JSON и внешней отправкой, которое нельзя сделать транзакционным без сервера/очереди.
4. Документация содержала устаревшее утверждение о fixture как единственном источнике, хотя конфигурация и адаптеры уже поддерживают реальные RSS/HTML-источники.

## Integration design

1. После существующей дедупликации и до форматирования `GitHubModelsClient` передаёт ограниченные поля новой `Publication` в `https://models.github.ai/inference/chat/completions`.
2. Клиент использует только автоматически созданный `GITHUB_TOKEN`, а workflow выдаёт ровно `models: read`. Значение токена не записывается в файл, состояние или журнал.
3. Модель по умолчанию — `openai/gpt-4o` через GitHub Models (не OpenAI API); запрос требует JSON Schema с кратким русским резюме и `low`/`medium`/`high`. Результат валидируется Pydantic, а размер текста ограничен.
4. AI получает недоверенный текст новости как справочный материал. Системная инструкция запрещает выполнять инструкции из этого текста, а ответ не может изменить URL, дату, категорию, данные дивидендов или fingerprint.
5. `ai_summary` используется только в сообщении Telegram, а AI-важность сохраняется в уже существующем `SentItem` для ежедневной сводки. Дедупликация остаётся детерминированной и происходит раньше AI.
6. Любая сетевая ошибка, `429`, ошибка авторизации или невалидный ответ отключают AI до конца запуска. Публикация отправляется через старый детерминированный путь. Платный fallback отсутствует.

## GitHub Actions operation

`monitor.yml` уже является единственным рабочим планировщиком: GitHub-hosted runner устанавливает зафиксированные зависимости, запускает монитор, затем коммитит изменённый `data/state.json`. Компьютер пользователя и собственный сервер не участвуют.

Для Telegram по-прежнему нужны только repository secrets `TELEGRAM_BOT_TOKEN` и `TELEGRAM_CHAT_ID`. Для AI ничего добавлять не нужно: GitHub автоматически создаёт `GITHUB_TOKEN` на время job. Бесплатное использование GitHub Models ограничено; при исчерпании лимита GitHub блокирует следующий AI-запрос, а этот проект продолжает обработку без AI. Не включайте оплату GitHub Models и не добавляйте Azure/API-ключи.

Официальные источники: [GitHub Models quickstart](https://docs.github.com/en/github-models/quickstart), [GitHub Models billing](https://docs.github.com/en/billing/concepts/product-billing/github-models), [GITHUB_TOKEN](https://docs.github.com/en/actions/concepts/security/github_token).

## Validation plan

- модульные тесты проверяют корректный запрос, строгую валидацию JSON и отсутствие токена в ошибке;
- тест runner подтверждает порядок: AI вызывается один раз только для новой публикации, после дедупликации;
- `pytest` и Ruff выполняются локально и в workflow `Tests`;
- после публикации изменений GitHub Actions должен выполнить `Tests`; первый плановый `Dividend monitor` подтвердит доступность GitHub Models в конкретном аккаунте без риска для доставки новостей.
