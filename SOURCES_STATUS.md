# Статус официальных источников

Дата проверки: **13.07.2026**.

Статусы источников:

- `working` — источник проверен и используется адаптером;
- `limited` — официальный источник подтверждён, но HTML-структура или полнота публикаций требуют наблюдения;
- `manual` — официальный раздел найден, но стабильный автоматический способ чтения не подтверждён;
- `unavailable` — источник не добавлен в автоматический мониторинг, потому что публичная доступность или структура не подтверждены.

## Компании и тикеры

| Компания | Тикер | Официальное подтверждение |
|---|---|---|
| ПАО «ЛУКОЙЛ» | `LKOH` | [акционерный капитал и тикер](https://www.lukoil.com/InvestorAndShareholderCenter/Securities/sharecapital) |
| ПАО «Транснефть» | `TRNFP` | [карточка бумаги Московской биржи](https://www.moex.com/ru/stocks/trnfp) |
| ПАО «Корпоративный центр ИКС 5» | `X5` | [акции и акционерный капитал X5](https://www.x5.ru/ru/investors/shares/) |
| ПАО «Татнефть» имени В.Д. Шашина | `TATNP` | [сообщение Московской биржи о листинге](https://www.moex.com/n97717) |
| МКПАО «Хэдхантер» | `HEAD` | [официальный сайт для инвесторов](https://investor.hh.ru/ru/shareholders-and-investors) |
| ПАО «Интер РАО» | `IRAO` | [материалы для акционеров и инвесторов](https://www.interrao.ru/investors/) |
| ПАО «НМТП» | `NMTP` | [карточка эмитента Московской биржи](https://www.moex.com/ru/stocks/nmtp) |

## Источники в автоматическом мониторинге

| Источник | Компания | Новости | Отчётность | Статус |
|---|---|---|---|---|
| [LUKOIL Press Center](https://www.lukoil.com/PressCenter/Pressreleases) | LKOH | [пресс-релизы](https://www.lukoil.com/PressCenter/Pressreleases) | [Financial Results](https://www.lukoil.com/InvestorAndShareholderCenter/FinancialReports) | `limited` |
| [X5 — раздел инвесторов](https://x5.ru/ru/investors/) | X5 | [новости](https://x5.ru/ru/investors/statements/) | [раздел инвесторов](https://x5.ru/ru/investors/) | `limited` |
| [HeadHunter Press Center](https://investor.hh.ru/ru/press-center) | HEAD | [пресс-центр](https://investor.hh.ru/ru/press-center) | [отчёты и результаты](https://investor.hh.ru/ru/shareholders-and-investors) | `limited` |
| [Интер РАО — новости](https://www.interrao.ru/press-center/news/) | IRAO | [новости](https://www.interrao.ru/press-center/news/) | [раскрытие информации](https://www.interrao.ru/investors/disclosure/) | `limited` |

Для `limited`-источников используется осторожный HTML-парсер: публикация принимается только при наличии ссылки на материал и даты рядом с заголовком. Изменение вёрстки может потребовать обновления адаптера.

## Источники без автоматического подключения

| Компания | Официальные разделы | Статус | Причина |
|---|---|---|---|
| ПАО «Транснефть» (`TRNFP`) | [официальный сайт](https://www.transneft.ru/) | `manual` | Официальный сайт и эмитент подтверждены, но стабильный публичный раздел новостей/отчётности для безопасного автоматического чтения не подтверждён. |
| ПАО «Татнефть» имени В.Д. Шашина (`TATNP`) | [официальный сайт](https://www.tatneft.ru/) | `manual` | Найдены корпоративные дочерние пресс-центры, но они не являются подтверждённой лентой новостей и отчётности самого эмитента. |
| ПАО «НМТП» (`NMTP`) | [официальный сайт](https://nmtp.info/) | `unavailable` | Стабильная доступная страница новостей/отчётности для автоматического чтения не подтверждена. Источник в конфигурацию не добавлялся. |

## Ранее подключённые источники

| Источник | Компания | Статус |
|---|---|---|
| [MOEX Investor Relations RSS](https://www.moex.com/export/news.aspx?cat=207) | MOEX | `working` |
| [Россети Ленэнерго — пресс-центр](https://rosseti-lenenergo.ru/press/) | LSNGP | `working` |
| [Сбербанк — раскрытие информации](https://www.sberbank.com/ru/investor-relations/disclosure/) | SBER | `unavailable` — сайт возвращает WAF-страницу `user_blocked`; защиту не обходили. |

## Безопасность

- Используются только официальные сайты компаний или официальные страницы Московской биржи.
- Неподтверждённые страницы не добавляются в `config/sources.yaml`.
- CAPTCHA, WAF и другие защитные механизмы не обходятся.
- Один сбой источника изолирован в `runner.py` и не останавливает обработку остальных источников.
