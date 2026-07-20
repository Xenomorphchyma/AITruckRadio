# NewsAgent: проверяемые новости без UI

`ai_truck_radio_app/news_agent.py` собирает доказательную новостную ленту отдельно от эфирного текста ведущих. Поиск и чтение страниц передаются в конструктор как `search_fn(query, timeout, limit)` и `read_fn(url, timeout, max_chars)`, поэтому backend полностью тестируется без сети.

## Проверка новости

1. Обычный поиск дополняется отдельными `site:official-domain` запросами.
2. Прочитанным страницам назначаются последовательные `source_id`.
3. Для каждого источника сохраняются URL, домен, `published_at`, `fetched_at`, `expires_at` и признак официальности.
4. Первый LM-проход создаёт только черновики со ссылками на SOURCE.
5. Второй независимый проход возвращает решение и подтверждающие source IDs, не переписывая исходный черновик.
6. `verified` требует официального источника либо минимум двух независимых доменов. Недостаточно подтверждённый материал получает `review`, ошибочный — `rejected`.
7. Exact/fuzzy-дубликаты уже запланированных или вышедших новостей отклоняются.

Все элементы имеют `status_history`. Поддерживаемые состояния: `draft`, `verified`, `review`, `rejected`, `scheduled`, `aired`. Переходы `scheduled` и `aired` записываются в `news_agent_history_file`.

Если источники или LM недоступны, агент читает существующий `news_file` (`data/news.txt`). Ручные строки помечаются `review`: это редакционный fallback, а не автоматически проверенная интернет-новость.

## Backend API

```python
agent = NewsAgent(cfg, lm, search_fn=search_pages, read_fn=read_page)
pack = agent.build(force=False)
scheduled = agent.select_next(pack, mode="live")
if scheduled:
    aired = agent.mark_aired(scheduled, mode="live")
```

Кэш содержит источники, решения фактчека, статусы и TTL. Валидный кэш не запускает повторный поиск или LM.

## Ключи для будущей интеграции в config/UI

- `news_agent_enabled`;
- `news_agent_model`, `news_agent_queries`, `news_agent_official_domains`;
- `news_agent_results_per_query`, `news_agent_max_pages`;
- `news_agent_min_page_chars`, `news_agent_page_chars`, `news_agent_total_evidence_chars`;
- `news_agent_page_timeout_sec`, `news_agent_timeout_sec`, `news_agent_max_tokens`, `news_agent_temperature`;
- `news_agent_factcheck_enabled`, `news_agent_structured_output`, `news_agent_no_think`;
- `news_agent_min_independent_domains`, `news_agent_max_items`;
- `news_agent_source_ttl_sec`, `news_agent_cache_ttl_sec`, `news_agent_cache_file`;
- `news_agent_history_file`, `news_agent_history_max_items`.

Существующие `news_enabled`, `news_chance`, `news_file` и `news_lines_per_insert` сохраняются. `news_chance` теперь применяется ровно один раз через `should_include_news`; `read_news_line` только выбирает данные из файла.
