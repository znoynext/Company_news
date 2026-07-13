# Production checklist

Дата аудита: 2026-07-13

Проверенный commit приложения: `80262e0 fix: harden production configuration`

Итог: **WARNING** — 19 пунктов имеют статус PASS, 1 пункт имеет статус WARNING, FAIL отсутствуют. Основной workflow готов к работе; требуется дождаться первого фактического scheduled-запуска ежедневного workflow.

| № | Проверка | Статус | Фактическое подтверждение |
|---:|---|---|---|
| 1 | Проект запускается с чистого checkout | **PASS** | Из `git archive` commit `80262e0` создана чистая копия. В новом venv установлены `requirements-dev.lock` и editable-пакет; `pip check`, CLI `--help`, 41 тест и Ruff завершились успешно. |
| 2 | Python 3.12 поддерживается | **PASS** | GitHub Actions run [29273394631](https://github.com/znoynext/Company_news/actions/runs/29273394631) на commit `80262e0`: шаги `Set up Python 3.12`, установка, pytest и Ruff успешны. Ручной run [29273413845](https://github.com/znoynext/Company_news/actions/runs/29273413845) также выполнен на Python 3.12. |
| 3 | Зависимости фиксированы | **PASS** | Прямые зависимости и build backend используют `==`; полный runtime/dev набор зафиксирован в `requirements-runtime.lock` и `requirements-dev.lock`. Изолированная установка точных версий и `pip check` успешны. |
| 4 | pytest проходит | **PASS** | Локально и в чистой копии: `41 passed`. GitHub Actions run `29273394631`: шаг `Run pytest` успешен. |
| 5 | Ruff проходит | **PASS** | Локально и в чистой копии: `All checks passed!`. GitHub Actions run `29273394631`: шаг `Run Ruff` успешен. |
| 6 | YAML GitHub Actions корректен | **PASS** | Все три YAML-файла загружены PyYAML без ошибок; GitHub показывает workflows активными. CI и ручной workflow на commit `80262e0` успешно обработаны GitHub Actions. |
| 7 | Секреты не находятся в коде | **PASS** | В tracked-файлах нет `.env`; поиск Telegram token, GitHub token, AWS key и private-key шаблонов не нашёл совпадений. Секреты используются только через `${{ secrets.* }}`. |
| 8 | Секреты не выводятся в логи | **PASS** | Ошибки Telegram преобразуются в `TelegramDeliveryError` без секретного URL и без exception chain. Тест с HTTP 401 подтверждает отсутствие bot token в `str` и `repr` ошибки; сообщение диагностики содержит только имена отсутствующих переменных. |
| 9 | Telegram HTML экранируется | **PASS** | Тесты проверяют экранирование компании, заголовка, описания, URL и имени workflow. Daily summary и health-сообщения также используют `html.escape`; Telegram отправляет сообщения с `parse_mode=HTML`. |
| 10 | HTTP-запросы имеют тайм-ауты | **PASS** | Фактически проверены настройки: источники `connect=10s`, остальные операции `30s`; Telegram `connect=10s`, остальные операции `30s`. `SourceConfig.timeout_seconds` ограничен диапазоном до 120 секунд. |
| 11 | Ошибки одного источника изолированы | **PASS** | Каждый источник обёрнут отдельным `try/except`; тест с источником, падающим три запуска подряд, подтверждает продолжение работы, единичное предупреждение и восстановление. |
| 12 | Дедупликация работает | **PASS** | Тесты подтверждают повторный external ID, нормализацию URL, fingerprint, различение отдельных официальных отчётов и хранение 180 дней истории. |
| 13 | `state.json` не повреждается при ошибке | **PASS** | Новый тест имитирует сбой финальной замены файла и подтверждает, что прежний JSON остаётся читаемым и неизменным. Тест ошибки источника подтверждает сохранение валидного состояния. |
| 14 | Запись `state.json` атомарная | **PASS** | Запись выполняется во временный `.tmp`, затем `flush`, `os.fsync` и атомарный `Path.replace`. Поведение при ошибке замены проверено тестом. |
| 15 | Параллельные workflow заблокированы | **PASS** | Основной и ежедневный workflow используют общую concurrency-группу `dividend-monitor` с `cancel-in-progress: false`, поэтому запуски ставятся в очередь. |
| 16 | Автоматический commit не создаёт рекурсивные workflow | **PASS** | Рабочие workflows запускаются только по `schedule`/`workflow_dispatch`; автоматический commit добавляет только `data/state.json`. Tests workflow имеет path-фильтры, не включающие state-файл. |
| 17 | Ручной запуск работает | **PASS** | Ручной workflow_dispatch run [29273413845](https://github.com/znoynext/Company_news/actions/runs/29273413845) на commit `80262e0` завершён успешно, включая Python 3.12, мониторинг, сохранение state и метрики. |
| 18 | Расписание работает | **WARNING** | Основной scheduled-run [29272853080](https://github.com/znoynext/Company_news/actions/runs/29272853080) завершён успешно; cron `7,37 * * * *` подтверждён фактически. Daily cron `17 8 * * *` корректен и workflow активен, но фактического scheduled-run ежедневного workflow на момент аудита ещё нет. |
| 19 | Ежедневная сводка не дублируется | **PASS** | Тест выполняет ежедневную сводку дважды в одну дату: Telegram получает одно сообщение, `last_daily_summary_date` сохраняется. Heartbeat-предупреждение также не повторяется. |
| 20 | Превышение длины Telegram-сообщения обработано | **PASS** | Форматтер проверен на враждебных длинных данных и остаётся в пределах 4096 символов. Telegram client отклоняет 4097 символов до HTTP-запроса; это подтверждено тестом. |

## Выполненные проверки

- чистая установка из lock-файлов в новом virtual environment;
- `python -m pip check`;
- `python -m pytest -q` — 41 тест;
- `python -m ruff check . --no-cache`;
- сборка wheel без зависимостей и build isolation;
- загрузка всех workflow YAML;
- проверка точных версий и согласованности lock-файлов;
- поиск credential-шаблонов и tracked `.env`;
- проверка HTTP timeout-конфигурации;
- проверка workflow triggers, concurrency и автоматических state-коммитов;
- GitHub Actions CI на Python 3.12;
- ручной и scheduled запуск основного workflow.

## Исправления по результатам аудита

- добавлены точные runtime/dev lock-файлы и воспроизводимая установка в workflows;
- исключена утечка Telegram bot token через URL в HTTP traceback;
- добавлено HTML-экранирование имени workflow в тестовом Telegram-сообщении;
- добавлены тесты лимита Telegram и сохранности state при сбое атомарной замены;
- CI теперь запускается при изменении lock-файлов и любых workflow.
