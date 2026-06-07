# -*- coding: utf-8 -*-
from __future__ import annotations

import html
import json
from typing import Any, Dict, List


def render_panel(engine: Any, cfg: Dict[str, Any], snap: Dict[str, Any], default_config: Dict[str, Any], app_name: str, app_version: str) -> str:
    def esc(x: Any) -> str:
        return html.escape(str(x if x is not None else ""), quote=True)

    def checked_attr(v: bool) -> str:
        return " checked" if v else ""

    def selected_attr(a: Any, b: Any) -> str:
        return " selected" if str(a) == str(b) else ""

    def changed(key: str) -> bool:
        if key not in default_config:
            return False
        try:
            return json.dumps(cfg.get(key), ensure_ascii=False, sort_keys=True) != json.dumps(default_config.get(key), ensure_ascii=False, sort_keys=True)
        except Exception:
            return cfg.get(key) != default_config.get(key)

    def reset_button(key: str) -> str:
        hidden = "" if changed(key) else " is-hidden"
        return f'<button type="button" class="reset-key{hidden}" data-key="{esc(key)}" title="Сбросить этот параметр к стандартному значению">×</button>'

    def label_for(key: str, label: str, tip: str = "") -> str:
        tip_html = f'<span class="tip" title="{esc(tip)}">?</span>' if tip else ""
        return f'<div class="setting-title"><span>{esc(label)}</span>{tip_html}{reset_button(key)}</div>'

    def input_text(key: str, label: str, tip: str = "", placeholder: str = "") -> str:
        return f'<label class="setting">{label_for(key,label,tip)}<input name="{esc(key)}" value="{esc(cfg.get(key, default_config.get(key, "")))}" placeholder="{esc(placeholder)}"></label>'

    def input_num(key: str, label: str, tip: str = "", minv: str = "", maxv: str = "", step: str = "1") -> str:
        # type=number в русской Windows/Chrome не даёт нормально сохранять 0,24.
        # Поэтому это текстовое поле с inputmode=decimal; сервер принимает и точку, и запятую.
        attrs = ['inputmode="decimal"', 'data-number="1"']
        if minv != "": attrs.append(f'data-min="{esc(minv)}"')
        if maxv != "": attrs.append(f'data-max="{esc(maxv)}"')
        if step != "": attrs.append(f'data-step="{esc(step)}"')
        return f'<label class="setting">{label_for(key,label,tip)}<input name="{esc(key)}" type="text" {" ".join(attrs)} value="{esc(cfg.get(key, default_config.get(key, "")))}"></label>'

    def checkbox(key: str, label: str, tip: str = "") -> str:
        tip_line = f'<small>{esc(tip)}</small>' if tip else ""
        return (
            f'<div class="check setting-bool" data-setting-key="{esc(key)}">'
            f'<label class="check-main">'
            f'<input type="checkbox" name="{esc(key)}"{checked_attr(bool(cfg.get(key, default_config.get(key, False))))}>'
            f'<span class="check-copy"><b>{esc(label)}</b>{tip_line}</span>'
            f'<span class="switch-ui" aria-hidden="true"></span>'
            f'</label>{reset_button(key)}</div>'
        )

    def select_box(key: str, label: str, options: List[str], tip: str = "") -> str:
        opts = "".join(f'<option value="{esc(o)}"{selected_attr(cfg.get(key), o)}>{esc(o)}</option>' for o in options)
        return f'<label class="setting">{label_for(key,label,tip)}<select name="{esc(key)}">{opts}</select></label>'

    checkbox_keys = [
        "weather_enabled", "news_enabled", "two_hosts_enabled", "tts_speak_host_names", "fade_enabled", "speech_bed_enabled", "speech_takeover_enabled", "speech_takeover_only_if_prepared",
        "track_profiles_enabled", "track_profiles_web_lookup_enabled", "track_profiles_force_rebuild_existing", "track_profiles_wikipedia_enabled", "track_profiles_wikidata_enabled", "track_profiles_deezer_enabled", "track_profiles_itunes_enabled", "track_profiles_enrich_missing_web_only", "track_profiles_enrich_only_if_no_sources", "night_mode_enabled", "hotkey_enabled", "lm_enabled", "lm_append_no_think",
        "intro_before_first_track", "startup_intro_blocking", "async_prepare_dj", "show_experimental_tts_backends", "omnivoice_persistent_worker", "omnivoice_prewarm_on_radio_start", "omnivoice_normalize_ru", "omnivoice_nonverbal_tags_enabled",
        "speech_radio_processing_enabled", "speech_compressor_enabled", "speech_presence_eq_enabled", "speech_loudnorm_enabled", "speech_limiter_enabled", "jingle_enabled", "auto_generate_sweep_jingle",
        "show_plan_enabled", "show_plan_block_until_ready", "show_plan_include_intro", "show_plan_rebuild_on_start", "show_plan_continuous_extend", "show_plan_live_after_exhausted",
        "show_plan_intro_long_opening", "show_plan_unique_greetings", "show_plan_fill_music_while_generating", "show_plan_auto_enable_after_generation", "exact_hour_time_announce_enabled", "listener_greetings_enabled", "tts_parse_validation_enabled", "radio_autostart",
        "clean_generated_on_start", "clean_generated_on_restart", "station_id_enabled", "station_id_fallback_tts_enabled", "live_blocking_dj_when_due", "live_prepare_at_track_start_when_due", "startup_intro_reserve_first_track", "host_should_use_stress_marks", "host_duo_intro_in_mostly_solo", "strict_duo_intro_require_both", "avoid_road_cliche_prompt", "season_reality_guard_enabled", "host_creative_fact_mode", "host_strict_clock_guard", "live_expected_speech_time_enabled", "omnivoice_prewarm_on_radio_start", "entertainment_enabled", "entertainment_in_live", "entertainment_in_planned", "horoscope_enabled", "horoscope_generate_before_radio", "riddles_enabled", "wrong_answer_game_enabled", "entertainment_generate_with_lm", "entertainment_agent_enabled", "entertainment_agent_factcheck_enabled", "entertainment_agent_no_think", "entertainment_agent_structured_output", "entertainment_status_in_panel", "guest_enabled", "guest_in_live", "guest_in_planned", "guest_generate_before_radio", "guest_voice_warning_in_panel",
    ]
    checkbox_keys = list(dict.fromkeys(checkbox_keys))
    hidden_checkbox_keys = ",".join(checkbox_keys)

    styles = cfg.get("available_styles") or default_config["available_styles"]
    if str(cfg.get("station_style")) not in styles:
        styles = list(styles) + [str(cfg.get("station_style"))]

    hosts_editor_json = json.dumps(cfg.get("hosts") or default_config.get("hosts") or [], ensure_ascii=False)
    guest_status = engine._guest_ref_status() if hasattr(engine, "_guest_ref_status") else {"audio_exists": False, "audio": "references/guest_ref.wav"}
    guest_voice_mode = str(cfg.get("guest_voice_mode", default_config.get("guest_voice_mode", "design")) or "design")
    guest_warning = "" if guest_voice_mode != "reference" or guest_status.get("audio_exists") else f"<div class='warn-box'>Reference-файл гостя не найден: {esc(guest_status.get('audio'))}. Переключи режим голоса гостя на design или добавь файл.</div>"
    hosts_settings = "".join([
        '<div class="host-editor-note">Для каждого ведущего отдельно задаётся участие во вступлении, обычном эфире и относительная частота появления. Вес 1.0 — основной ведущий; 0.2 — появляется примерно в пять раз реже при одиночном составе.</div>',
        f'<input type="hidden" name="hosts_json" id="hostsJson" value="{esc(hosts_editor_json)}">',
        '<div id="hostsEditor" class="hosts-editor"></div>',
        '<div class="actions-row"><button type="button" id="addHostBtn" class="secondary">+ Добавить ведущего</button><button type="button" id="resetHostsBtn" class="ghost">Вернуть стандартных</button></div>',
        input_num("host_intro_count", "Ведущих во вступлении", "Сколько включённых ведущих участвует в первом блоке.", "1", "8", "1"),
        input_num("host_regular_count_min", "Обычно ведущих в блоке", "Минимальное число ведущих после вступления.", "1", "8", "1"),
        input_num("host_regular_count_max", "Максимум ведущих в блоке", "Верхняя граница для редких расширенных разговоров.", "1", "8", "1"),
        input_num("host_regular_multi_chance", "Шанс расширенного состава", "Вероятность выбрать больше обычного минимума ведущих.", "0", "1", "0.05"),
        checkbox("strict_duo_intro_require_both", "Не выпускать старт без второго ведущего", "Если LM не дала обоих ведущих, запрос повторяется, а соло-вступление не выпускается."),
        checkbox("guest_enabled", "Гость в эфире", "Включает редкие короткие истории гостя/слушателя как отдельную рубрику."),
        checkbox("guest_in_live", "Гость в Live", "Гость может появляться в live-режиме."),
        checkbox("guest_in_planned", "Гость в плановом эфире", "Гость может попадать в заранее подготовленный план."),
        checkbox("guest_generate_before_radio", "Готовить гостевые истории перед стартом", "Истории гостя попадут в общий пакет рубрик."),
        input_text("guest_name", "Имя гостя", "Имя, с которого начинаются реплики гостя. Например: Гость, Алексей, Слушатель."),
        input_text("guest_role", "Роль гостя", "Например: слушатель с историей, музыкальный гость, человек с забавной ситуацией."),
        select_box("guest_voice_mode", "Голос гостя", ["design", "auto", "reference"], "design — голос без reference, удобно для звонящих; auto — reference если файл есть, иначе design; reference — строго указанный файл."),
        input_text("guest_voice_instruct", "Описание голоса гостя", "Только официальные OmniVoice-теги через запятую: male/female, young adult, middle-aged, russian accent, moderate pitch и т.п."),
        input_text("guest_ref_audio", "Reference-аудио гостя", "Нужно только в режиме reference или auto."),
        input_text("guest_ref_text", "Reference-текст гостя", "Текст рядом с reference-аудио, если используешь clone."),
        input_num("guest_chance", "Шанс появления гостя", "Вероятность гостевого блока среди рубрик.", "0", "1", "0.05"),
        input_num("guest_min_blocks_between", "Пауза между гостями", "Минимум выходов ведущих между гостевыми историями.", "1", "50", "1"),
        input_num("guest_story_count", "Сколько историй гостя готовить", "Сколько коротких историй подготовить в пакете рубрик.", "1", "20", "1"),
        guest_warning,
    ])

    live_settings = "".join([
        select_box("station_style", "Стиль станции", list(styles), "Меняет общий тон ведущих: душевное радио, уютное радио, киберпанк и т.п."),
        input_num("dj_every_n_tracks_min", "Live: минимум песен между речью", "Минимальный интервал между вставками ведущих в live-режиме.", "1", "20"),
        input_num("dj_every_n_tracks_max", "Live: максимум песен между речью", "Максимальный интервал между вставками ведущих в live-режиме.", "1", "30"),
        select_box("dj_talk_profile", "Длина live-блоков", ["short", "medium", "long", "mixed"], "mixed позволяет радио иногда делать короткие, иногда длинные блоки."),
        select_box("dj_topic_mode", "Тема live-блоков", ["auto", "music", "news", "weather", "listener_story"], "auto сам смешивает музыку, новости, погоду и живые зарисовки слушателей."),
        checkbox("intro_before_first_track", "Первое вступление перед первой песней", "Ведущие сначала открывают эфир, обсуждают время/погоду/настроение, потом включают трек."),
        checkbox("startup_intro_blocking", "Ждать первое вступление до музыки", "Если включено — радио не начнёт первую песню, пока стартовая речь не готова."),
        input_num("startup_intro_time_lead_sec", "Старт: время с запасом, сек", "В стартовой речи передаётся время немного вперёд, чтобы ведущие не называли время начала генерации.", "0", "300", "5"),
        checkbox("listener_greetings_enabled", "Приветы слушателям", "Берёт строки из data/greetings.txt; в плане не повторяет их внутри одного блока."),
        checkbox("exact_hour_time_announce_enabled", "Объявлять ровный час", "Если эфир проходит около 14:00, 15:00 и т.п., ведущие могут сказать точное время."),
        checkbox("live_blocking_dj_when_due", "Если ведущий должен быть — ждать/сгенерировать", "Если заранее подготовленная вставка не успела, live-режим не перескакивает на следующую песню, а готовит ведущего перед переходом."),
        checkbox("live_prepare_at_track_start_when_due", "Live: готовить речь сразу в начале нужного трека", "Когда после текущей песни должен быть ведущий, генерация запускается в начале этой песни, а не в финале."),
        checkbox("live_expected_speech_time_enabled", "Live: передавать время будущего выхода", "Если речь готовится во время песни, LM получает время, когда речь реально выйдет в эфир, а не время начала генерации."),
        input_num("live_prepare_trigger_fraction", "Live: контрольная подготовка на доле трека", "0.5 = дополнительная проверка на половине песни. Это страховка, если стартовый запуск не сработал.", "0.05", "0.9", "0.05"),
        checkbox("host_should_use_stress_marks", "Просить ударения для TTS", "В промпт и постобработку добавляются ударения в спорных словах."),
        input_num("listener_greetings_chance", "Шанс привета", "Вероятность вставить привет, когда он уже пора по интервалу.", "0", "1", "0.05"),
        input_num("listener_greetings_every_tracks_min", "Приветы: минимум песен", "Минимум песен между приветами.", "1", "50"),
        input_num("listener_greetings_every_tracks_max", "Приветы: максимум песен", "Максимум песен между приветами.", "1", "80"),
    ])

    plan_settings = "".join([
        input_num("show_plan_duration_minutes", "Длина одного подготовленного блока, минут", "15/60/120 минут. Это длина программы: музыка + речи + джинглы.", "5", "240", "5"),
        checkbox("show_plan_block_until_ready", "Ждать готовности плана перед стартом", "Для настоящего подготовленного эфира лучше включить: сначала готовим речь/переходы, потом запускаем."),
        checkbox("show_plan_include_intro", "Включать вступление в план", "Первый блок плана: время, погода, настроение ведущих, пожелание поездки и первый трек."),
        checkbox("show_plan_intro_long_opening", "Длинное первое вступление", "Делает первое вступление полноценным, а не одной короткой фразой."),
        input_num("show_plan_min_tracks_between_speech", "План: минимум песен между речью", "Как часто в подготовленном эфире появятся ведущие.", "1", "20"),
        input_num("show_plan_max_tracks_between_speech", "План: максимум песен между речью", "Верхняя граница интервала между блоками ведущих.", "1", "30"),
        input_num("show_plan_long_block_chance", "Шанс длинного блока", "Вероятность разговорного блока на 6–10 предложений.", "0", "1", "0.05"),
        checkbox("show_plan_continuous_extend", "Заранее готовить следующий блок", "Когда текущий план подходит к концу, радио заранее готовит следующие 15/60/120 минут."),
        input_num("show_plan_prepare_next_threshold_items", "Готовить следующий блок за N элементов", "Когда в плане осталось столько песен/речей, начинается подготовка следующего блока.", "1", "30"),
        input_num("show_plan_prepare_next_threshold_minutes", "Или за N минут до конца", "Временной порог для подготовки следующего блока.", "1", "60"),
        input_num("show_plan_prepare_next_fraction", "Готовить следующий план после доли программы", "0.5 = как только прошла половина текущего подготовленного эфира, начинает собираться следующий план.", "0.1", "0.9", "0.05"),
        checkbox("show_plan_fill_music_while_generating", "Если следующий план не успел — играть случайную музыку", "Радио не молчит: включает треки, которые не попадут в готовящийся план, и продолжает после окончания песни."),
        checkbox("show_plan_live_after_exhausted", "Аварийно перейти в live, если план не собирается", "Если генерация совсем сорвалась, радио может уйти в live-режим."),
        checkbox("show_plan_unique_greetings", "Приветы без повторов внутри плана", "Один и тот же привет не будет читаться повторно в пределах подготовленного блока."),
    ])

    music_settings = "".join([
        checkbox("track_profiles_enabled", "Давать ведущим описания треков", "Профили из cache/track_profiles.json попадут в промпт ведущих."),
        checkbox("track_profiles_web_lookup_enabled", "Искать сведения о музыке в интернете", "Агент составит запросы, откроет найденные страницы и передаст их текст локальной модели."),
        checkbox("track_profiles_force_rebuild_existing", "Сгенерировать заново даже для уже существующих песен", "Выключено: обрабатываются только новые/неописанные треки. Включено: пересобираются все профили, удобно после фикса ошибок."),
        select_box("track_profiles_research_mode", "Режим исследования", ["web_agent", "legacy_apis"], "web_agent — поиск и чтение обычных страниц; legacy_apis — прежние MusicBrainz/Wikipedia/Deezer/iTunes API."),
        input_text("track_analyzer_model", "Модель для описаний музыки", "Отдельная модель LM Studio только для исследования треков. Список загруженных моделей обновляется из LM Studio."),
        input_num("track_profiles_agent_max_queries", "Поисковых запросов на трек", "Агент сам формулирует запросы. Обычно достаточно 3–4.", "1", "8"),
        input_num("track_profiles_agent_search_results_per_query", "Результатов на один запрос", "Сколько ссылок брать из поисковой выдачи до фильтрации и чтения.", "2", "20"),
        input_num("track_profiles_agent_max_pages", "Прочитать страниц на трек", "Больше страниц повышает шанс проверки фактов, но заметно замедляет обработку.", "1", "8"),
        input_num("track_profiles_agent_min_page_chars", "Минимум символов страницы", "Слишком короткие заглушки и пустые страницы будут отброшены.", "100", "3000", "50"),
        input_num("track_profiles_agent_page_chars", "Текста с одной страницы", "Максимальный объём очищенного текста страницы, передаваемый локальной модели.", "1500", "20000", "500"),
        input_num("track_profiles_agent_total_evidence_chars", "Общий текст исследования", "Общий лимит материалов всех страниц для одного запроса к небольшой локальной модели.", "2000", "30000", "500"),
        input_num("track_profiles_agent_page_timeout_sec", "Таймаут страницы, сек", "Сколько ждать загрузки одной найденной страницы.", "5", "60"),
        input_num("track_profiles_agent_max_tokens", "Токенов на ответ профиля", "Лимит ответа модели для черновика и фактчека. Обычно 1000–1600.", "400", "4000", "100"),
        input_num("track_profiles_agent_temperature", "Творчество модели", "Низкое значение уменьшает выдумки. Для фактов рекомендуется 0.05–0.2.", "0", "1", "0.05"),
        checkbox("track_profiles_agent_factcheck_enabled", "Второй проход фактчека", "После черновика модель повторно сверяет поля с прочитанными страницами. Медленнее, но надёжнее."),
        checkbox("track_profiles_agent_append_no_think", "Отключать длинные рассуждения", "Добавляет системную no_think-инструкцию: reasoning-модель быстрее переходит к готовому JSON."),
        checkbox("track_profiles_agent_structured_output", "Принудительный JSON-режим", "LM Studio ограничивает ответ валидным JSON. Особенно важно для reasoning-моделей."),
        checkbox("track_profiles_wikipedia_enabled", "Wikipedia для фактов", "Берёт краткие открытые сведения об исполнителе/треке, если нашло подходящую страницу."),
        input_text("track_profiles_wikipedia_languages", "Языки Wikipedia", "Через запятую: ru,en,uk,de. Скрипт пробует по порядку и не долбит один язык бесконечно."),
        checkbox("track_profiles_wikidata_enabled", "Wikidata как запасной источник", "Если Wikipedia/MusicBrainz не дали фактов, пробует найти краткую карточку в Wikidata."),
        checkbox("track_profiles_deezer_enabled", "Deezer как запасной источник", "Публичный поиск Deezer помогает найти исполнителя/альбом/название без ключей API."),
        checkbox("track_profiles_itunes_enabled", "iTunes как запасной источник", "Публичный iTunes Search API иногда находит трек/альбом, когда Wikipedia не подходит."),
        checkbox("track_profiles_enrich_missing_web_only", "Дописать веб-факты только там, где их нет", "Если профиль уже есть, но вообще нет источников и веб-метаданных, скрипт попробует добавить факты без полной пересборки."),
        checkbox("track_profiles_enrich_only_if_no_sources", "Не трогать профили, где уже есть источники", "Если у трека уже есть sources/_original_web_meta, он не будет повторно обрабатываться только из-за web_fact='нет надёжного факта'."),
        select_box("track_profiles_fact_mode", "Режим фактов", ["web_then_lm", "safe_lm_only"], "web_then_lm — факты только из интернета + LM формулирует; safe_lm_only — без веб-фактов, только осторожное описание вайба."),
        input_text("track_profiles_file", "Файл описаний", "Куда сохраняются описания музыки для ведущих."),
        input_text("track_profiles_web_lookup_provider", "Поисковый провайдер", "Для web_agent используется обычная веб-выдача без ключа API, затем агент читает найденные страницы."),
        input_num("track_profiles_web_delay_sec", "Пауза между веб-запросами, сек", "Помогает не ловить 429 Too Many Requests. Для Wikipedia/MusicBrainz лучше 1–2 секунды.", "0", "10", "0.1"),
        input_num("track_profiles_wikipedia_cooldown_sec", "Пауза после 429 Wikipedia, сек", "Если Wikipedia отвечает Too Many Requests, скрипт временно перестаёт её мучить и продолжает без неё.", "10", "600", "10"),
        input_text("weather_city", "Город погоды", "Город для прогноза Open-Meteo/wttr."),
        select_box("weather_provider", "Провайдер погоды", ["open-meteo", "wttr", "auto"], "auto сначала пробует Open-Meteo, потом wttr."),
        checkbox("weather_enabled", "Включить погоду", "Погода будет попадать в live/plan блоки, но не в каждую фразу."),
        checkbox("news_enabled", "Включить новости из data/news.txt", "Без интернета не выдумывает новости: читает только то, что ты положил в файл."),
        input_text("listener_greetings_file", "Файл приветов", "Каждая непустая строка — отдельный привет/пожелание."),
    ])

    entertainment_settings = "".join([
        checkbox("entertainment_enabled", "Включить рубрики и игры", "Глобальный переключатель: гороскопы, загадки и мини-игры могут появляться между песнями."),
        checkbox("entertainment_in_live", "Использовать в Live", "Рубрики могут вклиниваться в обычные live-выходы ведущих."),
        checkbox("entertainment_in_planned", "Использовать в плановом эфире", "При генерации плана рубрики будут добавляться в речевые блоки заранее."),
        select_box("entertainment_integration_mode", "Как смешивать с обычным общением", ["auto_mix", "separate", "combine"], "auto_mix — модель сама решает; separate — отдельная рубрика; combine — рубрика плюс музыка/факт/пожелание."),
        input_num("entertainment_chance", "Шанс рубрики в выходе", "Вероятность, что в очередной выход ведущих попадёт гороскоп/загадка/игра. Обычное общение не отключается.", "0", "1", "0.05"),
        input_num("entertainment_min_blocks_between", "Минимум выходов между рубриками", "Чтобы рубрики не лезли в каждый блок подряд.", "0", "20", "1"),
        checkbox("horoscope_enabled", "Гороскопы", "Ведущие озвучивают несколько знаков за раз. Когда все знаки закончились, гороскоп больше не выходит."),
        select_box("horoscope_source_mode", "Источник гороскопов", ["web_then_lm", "lm_by_date", "web_only"], "web_then_lm — сначала интернет, потом LM; lm_by_date — нейронка генерирует по дате; web_only — только веб, при сбое fallback."),
        checkbox("horoscope_generate_before_radio", "Готовить рубрики перед стартом радио", "Перед включением эфира собирает пакет гороскопов/загадок/игр. Если LM недоступна, берёт fallback."),
        input_num("horoscope_chunk_min", "Гороскоп: минимум знаков за раз", "Сколько знаков зодиака назвать в одном выходе.", "1", "12", "1"),
        input_num("horoscope_chunk_max", "Гороскоп: максимум знаков за раз", "Сколько знаков зодиака максимум назвать в одном выходе.", "1", "12", "1"),
        input_num("horoscope_blocks_before_riddle_min", "Гороскопов перед загадкой: минимум", "Когда включены гороскопы и загадки, они чередуются: 2–3 гороскопа, затем загадка.", "1", "10", "1"),
        input_num("horoscope_blocks_before_riddle_max", "Гороскопов перед загадкой: максимум", "Верхняя граница чередования перед загадкой.", "1", "10", "1"),
        checkbox("riddles_enabled", "Загадки с вариантами", "В одном выходе ведущий задаёт загадку, в следующем — отвечает и обсуждает."),
        select_box("riddle_source_mode", "Источник загадок", ["web_then_lm", "lm_by_date", "web_only"], "web_then_lm — сначала интернет, потом LM; lm_by_date — нейронка по дате; web_only — только веб, при сбое fallback."),
        input_num("riddle_min_blocks_between", "Загадки: пауза между загадками", "Минимум выходов ведущих между загадками.", "1", "30", "1"),
        input_num("riddle_options_count", "Количество вариантов ответа", "Сколько вариантов ответа просить у модели/использовать в подсказке.", "2", "6", "1"),
        checkbox("wrong_answer_game_enabled", "Игра “ответь неправильно”", "Ведущие играют: нужно дать явно неправильный ответ. Если ответ хоть как-то правильный — ведущий проиграл."),
        input_num("wrong_answer_game_chance", "Шанс игры", "Игра может вклиниться между гороскопами и загадками.", "0", "1", "0.05"),
        input_num("wrong_answer_game_min_blocks_between", "Игра: пауза между появлениями", "Чтобы мини-игра не повторялась слишком часто.", "1", "50", "1"),
        checkbox("entertainment_generate_with_lm", "Генерировать пакет рубрик через LM", "LM Studio подготовит гороскопы/загадки/игры на сегодня. Если выключено — используется встроенный fallback."),
        checkbox("entertainment_agent_enabled", "Агентный поиск для рубрик", "Агент сам ищет страницы по каждой теме, читает их и передаёт факты выбранной локальной модели. Старые фиксированные источники используются только при сбое."),
        input_text("entertainment_model", "Модель для рубрик и игр", "Независимая модель LM Studio для гороскопов, загадок и викторин. Список берётся из LM Studio."),
        input_num("entertainment_agent_results_per_query", "Результатов поиска на тему", "Сколько ссылок просматривать в выдаче для гороскопов, загадок и вопросов викторины.", "1", "20", "1"),
        input_num("entertainment_agent_max_pages", "Всего страниц для рубрик", "Общий предел прочитанных страниц за один сбор пакета.", "3", "30", "1"),
        input_num("entertainment_agent_pages_per_topic", "Страниц на одну тему", "Не даёт гороскопам занять весь лимит: отдельно резервирует страницы загадкам и викторинам.", "1", "10", "1"),
        input_num("entertainment_agent_min_page_chars", "Минимальный размер страницы", "Слишком короткие страницы и пустые заглушки будут отброшены.", "100", "5000", "50"),
        input_num("entertainment_agent_page_chars", "Символов читать со страницы", "Максимум текста одной страницы, передаваемого в исследование.", "1000", "30000", "500"),
        input_num("entertainment_agent_total_evidence_chars", "Общий контекст источников", "Суммарный объём прочитанных фактов. Для контекста 8192 токена разумно 12000–18000 символов.", "3000", "50000", "1000"),
        input_num("entertainment_agent_page_timeout_sec", "Таймаут одной страницы, сек", "Сколько ждать поиск или открытие отдельной страницы.", "3", "60", "1"),
        input_num("entertainment_agent_max_tokens", "Токены ответа агента", "Пакет с 12 знаками и играми требует больше токенов, чем обычная реплика ведущего.", "600", "8000", "100"),
        input_num("entertainment_agent_temperature", "Temperature агента", "Низкое значение уменьшает выдумки при сборке фактов; юмор для неправильных ответов всё равно разрешён.", "0", "1", "0.05"),
        checkbox("entertainment_agent_factcheck_enabled", "Второй проход фактчека", "Модель ещё раз сверяет загадки и правильные ответы с прочитанными страницами."),
        checkbox("entertainment_agent_no_think", "Быстрый режим /no_think", "Полезно для небольших моделей. Для сильной reasoning-модели можно выключить."),
        checkbox("entertainment_agent_structured_output", "Требовать структурированный JSON", "Использует JSON schema LM Studio и уменьшает число сломанных ответов."),
        input_text("entertainment_history_file", "Журнал использованных рубрик", "Хранит короткие отпечатки уже выбранных загадок, игр и знаков гороскопа. В промпт ведущих весь архив не передаётся."),
        input_num("entertainment_history_max_items", "Размер журнала рубрик", "Сколько последних использованных загадок и игр помнить между перезапусками.", "100", "10000", "100"),
        input_text("entertainment_daily_cache_dir", "Дневной кэш рубрик", "JSON за каждый день с источниками, выдержками, результатами проверки и итоговым пакетом."),
        input_num("entertainment_pack_timeout_sec", "Таймаут генерации рубрик, сек", "Сколько ждать LM Studio при подготовке пакета рубрик.", "10", "300", "5"),
        input_num("entertainment_pack_max_items", "Максимум загадок/игр в пакете", "Ограничивает объём заранее созданного пакета.", "1", "30", "1"),
        input_num("rubric_web_timeout_sec", "Таймаут веб-рубрик, сек", "Сколько ждать сайт с гороскопом/загадкой до fallback.", "3", "60", "1"),
    ])

    voice_settings = "".join([
        select_box("tts_backend", "TTS backend", ["omnivoice", "piper", "sapi", "none"], "Основной сейчас OmniVoice; Piper/SAPI — запасные лёгкие режимы."),
        input_text("omnivoice_python", "OmniVoice Python", "Обычно используется .venv_omnivoice\\Scripts\\python.exe в корне проекта."),
        input_text("omnivoice_device", "OmniVoice device", "cuda:0 для GPU, cpu если нужно без видеокарты."),
        select_box("omnivoice_mode", "OmniVoice mode", ["clone", "design", "auto"], "clone использует references/maxim_ref.wav и irina_ref.wav."),
        checkbox("omnivoice_persistent_worker", "Держать OmniVoice в фоне", "Модель грузится один раз и потом быстрее озвучивает реплики."),
        checkbox("omnivoice_prewarm_on_radio_start", "Заранее грузить OmniVoice при включении радио", "Worker стартует сразу после кнопки включения, до первой реплики, чтобы первая озвучка не ждала загрузку модели."),
        checkbox("omnivoice_normalize_ru", "Normalizer/ударения", "Перед TTS применяет prompts/pronunciation_ru.tsv и исправляет спорные слова."),
        checkbox("omnivoice_nonverbal_tags_enabled", "OmniVoice эмоции в тексте", "Разрешает редкие официальные теги вроде [laughter], [sigh], [surprise-ah]. Неофициальные теги удаляются перед TTS."),
        input_num("omnivoice_nonverbal_tags_chance", "Шанс OmniVoice эмоции", "Вероятность разрешить LM один non-verbal tag в конкретном речевом блоке.", "0", "1", "0.05"),
        input_num("max_host_text_chars", "Лимит текста ведущих", "Аварийный лимит после ответа LM. 4000 достаточно для длинного планового вступления без обрубания.", "600", "12000", "100"),
        input_num("speech_voice_volume", "Громкость голоса", "Если ведущие тише музыки — подними до 1.45–1.8.", "0.2", "3", "0.05"),
        input_num("music_volume", "Громкость музыки", "Если песни давят ведущих, держи 0.70–0.85. Это не трогает громкость речи.", "0.2", "1.5", "0.05"),
        input_num("speech_loudnorm_i", "Целевая громкость речи LUFS", "Чем ближе к -10, тем громче. Безопасно: -13...-12.", "-22", "-10", "0.5"),
        input_num("speech_bed_volume", "Громкость подложки", "Радио-bed под речью. Обычно 0.04–0.10.", "0", "0.5", "0.01"),
        select_box("speech_bed_mode", "Подложка под речь", ["generated", "file", "auto", "off"], "generated — мягкий шум/bed; file — свои файлы из beds; off — без фона."),
        checkbox("fade_enabled", "Плавные входы и выходы", "Включает fade-in/fade-out для музыки и речи."),
        input_num("music_fade_out_sec", "Fade-out музыки, сек", "Когда ведущий входит на хвосте, затухание считается от укороченного конца песни.", "0", "8", "0.05"),
        input_num("transition_silence_sec", "Пауза между элементами, сек", "0 = без искусственной тишины между песней и ведущим.", "0", "5", "0.05"),
        checkbox("speech_takeover_enabled", "Ведущий входит на хвосте трека", "Если после песни должен говорить ведущий, радио забирает последние секунды трека и делает fade-out без неловкой паузы."),
        input_num("speech_takeover_sec", "Сколько хвоста забрать, сек", "Обычно 3–5 секунд: песня мягко заканчивается, и ведущий начинает сразу.", "0", "12", "0.25"),
        input_num("speech_takeover_min_track_sec", "Минимальная длина трека для перехвата", "Короткие треки не укорачиваются.", "10", "180", "1"),
        checkbox("speech_takeover_only_if_prepared", "Перехватывать хвост только если речь готова", "В Live не укорачивает песню, пока следующий блок ведущих ещё не подготовлен."),
        checkbox("speech_radio_processing_enabled", "Радио-обработка речи", "Compressor + EQ + loudnorm + limiter."),
        checkbox("speech_compressor_enabled", "Compressor", "Сжимает динамику, чтобы голос был плотнее как в эфире."),
        checkbox("speech_presence_eq_enabled", "EQ / presence boost", "Поднимает разборчивость голоса в районе presence."),
        checkbox("speech_loudnorm_enabled", "Loudness normalization", "Нормализует громкость речи."),
        checkbox("speech_limiter_enabled", "Limiter", "Ловит пики, чтобы речь не клиппила."),
        checkbox("jingle_enabled", "Jingles/sweeps после речи", "Короткий sweep или файл из jingles после блока ведущих."),
        input_num("jingle_chance_after_speech", "Шанс jingle", "Вероятность короткого sweep после ведущих.", "0", "1", "0.05"),
        checkbox("station_id_enabled", "Station ID между треками", "Короткая фирменная вставка станции, если между песнями нет ведущего."),
        input_text("station_id_dir", "Папка station ID", "Клади сюда свои короткие mp3/wav: Дорожное радиоооо, sweep, джингл станции."),
        input_num("station_id_every_tracks", "Station ID: раз в N треков", "1 — можно каждый трек без ведущего, 2 — раз в два трека, и так далее.", "1", "20"),
        input_num("station_id_chance", "Station ID: шанс", "Вероятность вставки, когда подошёл интервал.", "0", "1", "0.05"),
        input_num("station_id_volume", "Station ID: громкость", "Громкость фирменной вставки.", "0", "2", "0.05"),
        checkbox("station_id_fallback_tts_enabled", "TTS fallback для Station ID", "Если в папке station_ids нет файлов, можно озвучивать короткую фразу через TTS. Обычно лучше выключить и положить свои mp3."),
    ])

    lm_settings = "".join([
        checkbox("lm_enabled", "LM Studio для текстов", "Если выключить, радио берёт fallback-фразы."),
        input_text("lm_model", "Модель ведущих и эфира", "Используется только для реплик ведущих и планового эфира. Список загруженных моделей берётся из LM Studio."),
        input_num("lm_temperature", "Temperature", "0.70–0.85 для живого, но не бредового эфира.", "0", "2", "0.01"),
        input_num("lm_max_tokens", "Max tokens", "Для Thinking и планового эфира лучше 900–1400.", "100", "4000", "50"),
        input_num("lm_timeout_sec", "Timeout LM, сек", "Дай больше времени при Thinking/плановой генерации.", "10", "600", "5"),
        checkbox("lm_append_no_think", "Добавлять /no_think", "Выключи для умной предгенерации. Включай только если нужен быстрый live."),
        checkbox("tts_parse_validation_enabled", "Проверять, что TTS не потерял слова", "Если парсер диалогов потерял часть текста, отдаёт весь текст одному голосу, чтобы не пропали слова."),
        checkbox("host_creative_fact_mode", "Разрешить живые факты и ассоциации", "Ведущие могут добавлять любопытные факты, ассоциации и творческие зарисовки, но не должны выдавать фантазию как проверенную справку."),
        checkbox("host_strict_clock_guard", "Строгое время с компьютера", "Запрещает модели фантазировать про полночь/ночь/утро, если время компьютера другое."),
        input_num("tts_parse_validation_min_ratio", "Минимальная доля распознанного текста", "0.86 значит: если после разбиения на ведущих осталось меньше 86% текста, включается страховка.", "0.5", "1", "0.01"),
    ])

    system_settings = "".join([
        input_text("music_dir", "Папка музыки", "Где лежат mp3/flac/ogg треки."),
        input_text("ffmpeg_path", "FFmpeg path", "Путь к ffmpeg.exe или просто ffmpeg, если он в PATH."),
        input_num("bitrate_kbps", "Битрейт стрима", "Для локального MP3-стрима обычно хватает 128–192.", "64", "320", "16"),
        checkbox("radio_autostart", "Автозапуск радио при запуске run_radio.bat", "Ты просил запуск из панели, поэтому по умолчанию выключено."),
        checkbox("clean_generated_on_start", "Чистить генерации при запуске радио", "Удаляет cache/spoken, cache/tmp, cache/show_plans, но не трогает музыку/референсы/профили."),
        checkbox("clean_generated_on_restart", "Чистить генерации при перезапуске", "То же самое для кнопки 'Перезапустить и очистить'."),
        checkbox("hotkey_enabled", "Глобальный хоткей Ctrl+Alt+N", "Следующий трек, если Windows разрешила зарегистрировать хоткей."),
    ])

    stream_url = esc(snap.get("stream_url", ""))
    ets2_line = esc(snap.get("ets2_line", ""))
    defaults_json = json.dumps(default_config, ensure_ascii=False)
    return f"""<!doctype html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(app_name)} — Control Center</title>
<style>
:root {{ --bg:#090d17; --panel:#111827; --panel2:#172033; --text:#eef3ff; --muted:#9aa7bd; --line:#2b3548; --accent:#7cc7ff; --accent2:#90e0b7; --good:#62d78d; --bad:#ff7575; --warn:#ffd166; --shadow:0 14px 34px rgba(0,0,0,.30); }}
* {{ box-sizing:border-box; }}
html, body {{ height:100%; overflow:hidden; }}
body {{ margin:0; font-family:Segoe UI,Arial,sans-serif; background:linear-gradient(135deg,#111827 0,#090d17 44%,#070a12 100%); color:var(--text); }}
button,input,select,textarea {{ font:inherit; }}
button {{ border:0; border-radius:8px; padding:9px 11px; color:#07101f; background:var(--accent); font-weight:800; cursor:pointer; transition:.12s filter,.12s transform; min-width:0; }}
button:hover {{ filter:brightness(1.07); }} button:active {{ transform:translateY(1px); }} button.secondary {{ background:#26344f; color:var(--text); }} button.danger {{ background:#ff7b7b; }} button.ghost {{ background:transparent; color:var(--text); border:1px solid var(--line); }} button:disabled {{ opacity:.45; cursor:not-allowed; filter:none; }}
.top {{ height:58px; padding:12px 18px; border-bottom:1px solid var(--line); background:rgba(10,16,30,.78); backdrop-filter:blur(14px); }}
.topline {{ max-width:1540px; margin:0 auto; display:flex; gap:14px; align-items:center; justify-content:space-between; }} h1 {{ margin:0; font-size:20px; }} .sub {{ color:var(--muted); font-size:12px; margin-top:2px; }}
.chip {{ display:inline-flex; align-items:center; gap:6px; padding:7px 10px; border-radius:999px; border:1px solid var(--line); color:var(--muted); }} .chip.live {{ color:var(--good); border-color:rgba(98,215,141,.4); }} .chip.stopped {{ color:var(--warn); }}
.layout {{ display:grid; grid-template-columns:300px minmax(0,1fr); gap:12px; padding:12px; max-width:1540px; height:calc(100vh - 58px); margin:0 auto; overflow:hidden; }} @media(max-width:980px){{ html,body{{overflow:auto;height:auto;}} .layout{{grid-template-columns:1fr;height:auto;overflow:visible;}} }}
main {{ min-width:0; overflow:hidden; display:flex; flex-direction:column; }}
.card {{ background:linear-gradient(180deg,rgba(23,32,51,.96),rgba(15,23,42,.96)); border:1px solid var(--line); box-shadow:var(--shadow); border-radius:8px; padding:10px; min-width:0; }}
.side {{ min-width:0; overflow:hidden; display:grid; grid-template-rows:auto auto auto; gap:8px; align-content:start; }} .side .card {{ margin:0; }}
.now {{ font-size:14px; font-weight:900; margin:1px 0 6px; overflow-wrap:anywhere; line-height:1.15; }} .muted {{ color:var(--muted); }} .mini {{ font-size:11px; color:var(--muted); line-height:1.2; }}
.side-hero {{ display:grid; gap:7px; }} .side-title {{ display:flex; justify-content:space-between; gap:8px; align-items:center; }} .status-pills {{ display:grid; grid-template-columns:1fr 1fr 1fr; gap:5px; font-size:11px; }} .pill {{ background:rgba(0,0,0,.18); border:1px solid rgba(255,255,255,.05); border-radius:8px; padding:6px; min-width:0; overflow-wrap:anywhere; }} .pill b {{ color:#fff; }} .pill .ok {{ color:var(--good); }}
.mode-card {{ display:grid; gap:6px; padding:8px; border:1px solid rgba(124,199,255,.22); border-radius:8px; background:rgba(124,199,255,.06); }} .mode-actions {{ display:grid; grid-template-columns:1fr 1fr; gap:6px; }} .mode-actions button {{ min-height:36px; white-space:normal; line-height:1.12; }}
.controls {{ display:grid; grid-template-columns:1fr 1fr; gap:6px; }} .controls .pair {{ display:contents; }} .controls button {{ width:100%; min-height:34px; padding:7px 8px; white-space:normal; line-height:1.08; font-size:13px; }}
.controls .side-check {{ grid-column:1/-1; grid-row:4; }}
.controls #clearGenBtn {{ grid-column:2; grid-row:3; }}
.side-check {{ display:flex; align-items:center; gap:8px; padding:7px 9px; border:1px solid rgba(255,255,255,.06); border-radius:8px; background:rgba(0,0,0,.16); font-size:12px; }} .side-check input {{ width:auto; flex:0 0 auto; }}
.player-card {{ position:fixed; left:50%; bottom:14px; z-index:30; transform:translateX(-50%); width:min(980px,calc(100vw - 34px)); display:grid; grid-template-columns:minmax(155px,190px) minmax(320px,1fr) auto auto; gap:14px; align-items:center; padding:12px 14px; background:rgba(8,13,24,.98); backdrop-filter:blur(18px); border:1px solid rgba(124,199,255,.22); border-radius:10px; box-shadow:0 20px 54px rgba(0,0,0,.48); }}
.player-card.is-collapsed {{ width:min(360px,calc(100vw - 34px)); grid-template-columns:minmax(150px,1fr) auto auto; padding-block:9px; }}
.player-card.is-collapsed .player-meta,.player-card.is-collapsed .player-volume,.player-card.is-collapsed #liveEdgeBtn {{ display:none; }}
.player-brand {{ display:grid; grid-template-columns:auto minmax(0,1fr); grid-template-rows:auto auto; column-gap:10px; align-items:center; min-width:0; }}
.player-dot {{ grid-row:1/3; width:10px; height:10px; border-radius:50%; background:#687388; box-shadow:0 0 0 5px rgba(104,115,136,.14); }}
.player-card.is-live .player-dot {{ background:#f05252; box-shadow:0 0 0 5px rgba(240,82,82,.16),0 0 22px rgba(240,82,82,.5); }}
.player-name {{ font-weight:900; color:#f0f6ff; line-height:1.1; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }}
.player-state {{ color:var(--muted); font-size:11px; line-height:1.15; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }}
.player-meta {{ min-width:0; display:grid; grid-template-columns:minmax(0,1fr) auto; column-gap:12px; row-gap:6px; align-items:center; }}
.player-track {{ color:#e8f1ff; font-size:13px; font-weight:800; line-height:1.2; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }}
.player-sub {{ color:var(--muted); font-size:11px; white-space:nowrap; }}
.player-timeline {{ grid-column:1/-1; display:grid; grid-template-columns:minmax(0,1fr) 48px; gap:9px; align-items:center; }}
.player-timeline input {{ width:100%; height:4px; padding:0; accent-color:#8ed1ff; cursor:pointer; }}
.player-time {{ color:#9fb0ca; font-size:10px; font-variant-numeric:tabular-nums; text-align:right; }}
.player-actions {{ display:flex; align-items:center; gap:8px; justify-content:flex-end; }}
.player-card button {{ min-height:38px; padding:8px 12px; font-size:12px; line-height:1.08; }}
.player-card audio {{ position:absolute; width:1px; height:1px; opacity:0; pointer-events:none; }}
#playBtn {{ width:42px; min-width:42px; padding:0; font-size:18px; background:#354057; color:#eaf2ff; border:1px solid #56627c; }}
#playBtn.is-live {{ background:#d84545; color:#fff; border-color:#ff7b7b; }}
#liveEdgeBtn {{ min-width:78px; background:#202b40; color:#cbd8ee; }}
#liveEdgeBtn.is-behind {{ color:#fff; background:#8e3238; }}
.player-volume {{ display:flex; align-items:center; gap:9px; color:var(--muted); font-size:11px; min-width:185px; }}
.player-volume input {{ width:132px; height:28px; padding:0; margin:0; accent-color:var(--accent); cursor:pointer; }}
.player-volume input::-webkit-slider-runnable-track {{ height:6px; border-radius:999px; background:#314264; }}
.player-volume input::-webkit-slider-thumb {{ margin-top:-5px; width:16px; height:16px; }}
#playerCollapseBtn {{ width:24px; min-height:34px; padding:0; border:0; border-radius:0; background:transparent; color:#91a4bf; display:grid; place-items:center; }}
#playerCollapseBtn:hover {{ color:#fff; filter:none; }}
#playerCollapseBtn:focus {{ outline:none; box-shadow:none; }}
#playerCollapseBtn::before {{ content:''; width:8px; height:8px; border-right:2px solid currentColor; border-bottom:2px solid currentColor; transform:rotate(45deg) translateY(-2px); transition:transform .18s; }}
.player-card.is-collapsed #playerCollapseBtn::before {{ transform:rotate(225deg) translate(-1px,-1px); }}
.model-health {{ grid-column:1/-1; display:flex; align-items:center; gap:8px; color:var(--muted); font-size:12px; }}
.model-health.ok {{ color:var(--good); }} .model-health.bad {{ color:var(--bad); }}
.toast-stack {{ position:fixed; top:72px; right:18px; z-index:60; width:min(360px,calc(100vw - 36px)); display:grid; gap:10px; pointer-events:none; }}
.toast-item {{ pointer-events:auto; display:grid; grid-template-columns:minmax(0,1fr) auto; gap:10px; align-items:start; padding:11px 12px; border-radius:10px; background:rgba(12,20,36,.97); border:1px solid rgba(124,199,255,.24); box-shadow:0 16px 44px rgba(0,0,0,.34); color:#eaf2ff; font-size:12px; line-height:1.3; }}
.toast-item button {{ width:24px; height:24px; min-height:24px; padding:0; border-radius:7px; background:rgba(255,255,255,.06); color:#b8c8e6; }}
.nav-card {{ display:grid; gap:8px; }}
.tabs {{ display:grid; grid-template-columns:1fr 1fr 1fr; gap:5px; overflow:visible; flex:0 0 auto; }}
.tab {{ display:flex; align-items:center; justify-content:flex-start; min-height:32px; padding:7px 8px; background:#101827; color:var(--text); border:1px solid var(--line); white-space:normal; text-align:left; line-height:1.1; font-size:12px; }}
.tab.active {{ background:linear-gradient(90deg,var(--accent),#a9dcff); color:#07101f; border-color:transparent; }}
.tab-panel {{ display:none; position:absolute; inset:0; min-height:0; overflow-y:auto; overflow-x:hidden; padding:0 4px 92px 0; }}
.tab-panel.active {{ display:block; }}
#cfgForm {{ min-height:0; height:100%; flex:1; position:relative; display:block; overflow:hidden; }}
.grid {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(280px,1fr)); gap:10px; align-items:start; }}
.setting,.check {{ background:rgba(6,10,20,.32); border:1px solid rgba(255,255,255,.06); border-radius:8px; padding:10px; min-width:0; }}
.setting-title {{ display:flex; align-items:center; gap:8px; color:#d8e5ff; font-size:13px; font-weight:800; margin-bottom:6px; }} .setting-title span:first-child {{ min-width:0; }} .tip {{ display:inline-flex; align-items:center; justify-content:center; flex:0 0 auto; width:17px; height:17px; border-radius:50%; background:#243650; color:#bfe3ff; font-size:11px; cursor:help; }}
input:not([type="checkbox"]),select,textarea {{ width:100%; border-radius:8px; border:1px solid #314264; background:#08101f; color:var(--text); padding:9px; outline:none; }} input:not([type="checkbox"]):focus,select:focus,textarea:focus {{ border-color:var(--accent); box-shadow:0 0 0 3px rgba(124,199,255,.16); }}
input[type="checkbox"] {{ width:auto; flex:0 0 auto; accent-color:var(--accent); }}
.check {{ display:flex; align-items:center; justify-content:space-between; gap:10px; min-height:56px; }} .check-main {{ display:flex; align-items:center; justify-content:space-between; gap:12px; min-width:0; cursor:pointer; flex:1; }}
.check-main input {{ position:absolute; opacity:0; pointer-events:none; }} .switch-ui {{ order:2; width:42px; height:23px; border-radius:999px; background:#2a344d; border:1px solid #3d4a69; position:relative; flex:0 0 auto; }} .switch-ui::after {{ content:''; position:absolute; top:3px; left:3px; width:15px; height:15px; border-radius:50%; background:#aab8d8; transition:.16s; }} .check-main input:checked ~ .switch-ui {{ background:#256d95; border-color:#77c9ff; }} .check-main input:checked ~ .switch-ui::after {{ left:22px; background:white; }}
.check-copy {{ order:1; display:block; min-width:0; flex:1; }} .check-copy b {{ display:block; color:#e5edff; font-size:13px; line-height:1.22; }} .check-copy small {{ display:block; margin-top:3px; color:var(--muted); line-height:1.25; font-size:11px; }}
.reset-key {{ margin-left:auto; flex:0 0 auto; width:22px; height:22px; padding:0; border-radius:7px; background:#382236; color:#ffb4c8; border:1px solid #6b3348; }} .reset-key.is-hidden {{ display:none; }}
.progress {{ margin:8px 0; }} .bar {{ height:10px; background:#07101f; border:1px solid #26344f; border-radius:999px; overflow:hidden; }} .fill {{ height:100%; width:0%; background:linear-gradient(90deg,#7cc7ff,#62d78d); transition:width .35s; }}
textarea {{ min-height:90px; resize:vertical; }} pre {{ white-space:pre-wrap; overflow-wrap:anywhere; background:#07101f; border:1px solid var(--line); border-radius:8px; padding:9px; }} .ok {{ color:var(--good); }} .bad {{ color:var(--bad); }} .warn {{ color:var(--warn); }} .toast {{ min-height:18px; color:var(--warn); font-size:12px; }} .section-title {{ margin:0; font-size:22px; }} .explain {{ color:var(--muted); margin:0; line-height:1.38; max-width:980px; }} .actions-row {{ display:flex; flex-wrap:wrap; gap:8px; margin:10px 0 12px; }} .actions-row button {{ white-space:normal; }}
.panel-head {{ display:grid; grid-template-columns:minmax(0,1fr) auto; gap:14px; align-items:start; margin-bottom:12px; }}
.panel-head .actions-row {{ margin:0; justify-content:flex-end; }}
.status-grid {{ display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:8px; margin:10px 0 12px; }}
.status-tile {{ min-width:0; border:1px solid rgba(255,255,255,.06); border-radius:8px; padding:9px; background:rgba(0,0,0,.16); }}
.status-tile b {{ display:block; margin-bottom:3px; color:#dce8ff; }}
.wide-text {{ min-height:104px; }}
.plan-preview {{ display:grid; gap:7px; max-height:330px; overflow:auto; padding-right:4px; }} .plan-item {{ display:grid; grid-template-columns:38px 82px minmax(0,1fr) 54px; gap:8px; align-items:start; padding:9px; border-radius:8px; border:1px solid rgba(255,255,255,.07); background:rgba(0,0,0,.16); }} .plan-item.speech {{ border-color:rgba(124,199,255,.28); }} .plan-item.music {{ border-color:rgba(98,215,141,.22); }} .plan-item .title {{ font-weight:700; overflow-wrap:anywhere; }} .plan-item .text {{ color:#cbd8f5; margin-top:4px; font-size:12px; overflow-wrap:anywhere; }}
.floating-save {{ position:fixed; right:18px; bottom:16px; z-index:20; box-shadow:0 8px 26px rgba(0,0,0,.35); }}
.disabled-setting {{ opacity:.38; filter:grayscale(.55); }} .disabled-setting input,.disabled-setting select,.disabled-setting textarea {{ pointer-events:none; }} .disabled-setting .reset-key {{ display:none; }}
.host-editor-note,.warn-box {{ grid-column:1/-1; color:var(--muted); border:1px solid rgba(255,255,255,.08); background:rgba(255,255,255,.035); border-radius:8px; padding:10px; }} .warn-box {{ color:#ffd6a0; border-color:rgba(255,209,102,.28); }}
.favorite-hosts-picker {{ display:flex; flex-wrap:wrap; gap:7px; }}
.favorite-hosts-picker label {{ display:inline-flex; align-items:center; gap:6px; padding:7px 9px; border:1px solid var(--line); border-radius:8px; background:#101827; color:#dbe7ff; cursor:pointer; }}
.favorite-hosts-picker input {{ width:auto; }}
.hosts-editor {{ grid-column:1/-1; display:grid; gap:10px; }} .host-card {{ display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:10px; border:1px solid rgba(124,199,255,.18); background:rgba(124,199,255,.05); border-radius:8px; padding:12px; }} .host-card h3 {{ grid-column:1/-1; margin:0 0 2px; display:flex; align-items:center; justify-content:space-between; gap:8px; }} .host-card .wide {{ grid-column:1/-1; }} .host-card label {{ display:grid; gap:5px; font-size:12px; color:var(--muted); }} .host-card input,.host-card textarea {{ width:100%; }} .host-card textarea {{ min-height:70px; }} .host-remove {{ background:#563044; color:#ffd8e2; }} @media(max-width:760px){{ .host-card{{grid-template-columns:1fr;}} .host-card .wide{{grid-column:auto;}} }}
@media(max-width:980px){{ .nav-card{{order:-1;}} .tabs{{display:flex; overflow-x:auto; padding-bottom:2px;}} .tab{{white-space:nowrap; min-height:36px;}} .panel-head{{grid-template-columns:1fr;}} .panel-head .actions-row{{justify-content:flex-start;}} .status-grid{{grid-template-columns:1fr;}} }}
@media(max-width:760px){{ .plan-item{{grid-template-columns:1fr;}} .floating-save{{position:static;margin-top:10px;}} }}
.host-card-head{{display:flex;align-items:center;justify-content:space-between;gap:12px}}.host-title-switch{{display:flex;align-items:center;gap:12px;min-width:0;cursor:pointer}}.host-title-switch input{{position:absolute;opacity:0;pointer-events:none}}.host-title-switch input:checked ~ .switch-ui{{background:#256d95;border-color:#77c9ff}}.host-title-switch input:checked ~ .switch-ui::after{{left:24px;background:white}}.host-title-switch span:last-child{{overflow-wrap:anywhere}}.host-card-head .switch-ui{{width:46px;height:25px;flex:0 0 auto}}
</style>
</head>
<body>
<header class="top"><div class="topline"><div><h1>AI Truck Radio - Control Center</h1></div><div><span id="runBadge" class="chip {'live' if snap.get('radio_running') else 'stopped'}">{'● В эфире' if snap.get('radio_running') else ('● Запускается' if snap.get('radio_starting') else '● Остановлено')}</span></div></div></header>
<div class="layout">
  <aside class="side">
    <div class="card side-hero">
      <div class="side-title"><span class="mini">Сейчас</span><span id="runMini" class="mini">{('эфир идёт' if snap.get('radio_running') else ('эфир запускается' if snap.get('radio_starting') else 'эфир выключен'))}</span></div>
      <div class="now" id="now">{esc(snap.get('now_playing',''))}</div>
      <div class="status-pills">
        <div class="pill">Режим<br><b id="airMode">{esc(snap.get('air_mode','Live'))}</b></div>
        <div class="pill">Тип<br><b id="kind">{esc(snap.get('current_kind',''))}</b></div>
        <div class="pill">Слушатели<br><b id="clients">{esc(snap.get('active_clients',0))}</b></div>
        <div class="pill">Музыка<br><b id="musicCount">{esc(snap.get('music_count',0))}</b></div>
        <div class="pill">FFmpeg<br><b id="ffmpeg" class="{'ok' if snap.get('ffmpeg_ok') else 'bad'}">{'найден' if snap.get('ffmpeg_ok') else 'НЕ найден'}</b></div>
        <div class="pill">FFprobe<br><b id="ffprobe" class="{'ok' if snap.get('ffprobe_ok') else 'warn'}">{'найден' if snap.get('ffprobe_ok') else 'не найден'}</b></div>
      </div>
      <div class="mode-card">
        <div class="mini">Переключение режима во время эфира</div>
        <div class="mode-actions">
          <button type="button" id="modePlanBtn" class="secondary">Плановый</button>
          <button type="button" id="modeLiveBtn" class="secondary">Live</button>
        </div>
      </div>
    </div>
    <nav class="card nav-card" aria-label="Разделы панели">
      <div class="mini">Разделы</div>
      <div class="tabs" id="tabs"><button class="tab active" data-tab="dash">Пульт</button><button class="tab" data-tab="plan">Плановый эфир</button><button class="tab" data-tab="music">Музыка и факты</button><button class="tab" data-tab="live">Live-эфир</button><button class="tab" data-tab="hosts">Ведущие и гости</button><button class="tab" data-tab="fun">Рубрики и игры</button><button class="tab" data-tab="voice">Голос и эфир</button><button class="tab" data-tab="lm">LM Studio</button><button class="tab" data-tab="system">Система</button></div>
    </nav>
    <div class="card controls">
      <button id="radioStartBtn">▶ Включить радио</button>
      <button id="radioStopBtn" class="secondary">■ Выключить</button>
      <button id="radioRestartBtn" class="danger">↻ Рестарт + очистка</button>
      <div class="pair"><button id="skipBtn" class="secondary">⏭ Следующий</button><button id="rescanBtn" class="secondary">♬ Музыка</button></div>
      <label class="side-check"><input id="cleanOnControl" type="checkbox" checked><span>чистить старые генерации</span></label>
      <button id="clearGenBtn" class="ghost">Очистить cache</button>
    </div>
  </aside>
  <main>
    <form id="cfgForm">
      <input type="hidden" name="_checkbox_keys" value="{esc(hidden_checkbox_keys)}">
      <section class="tab-panel active" data-panel="dash"><div class="card"><div class="panel-head"><div><h2 class="section-title">Пульт эфира</h2><p class="explain">Текущие задачи генерации, готовность плана, модель и последняя реплика ведущих.</p></div><div class="actions-row"><button type="button" id="showPlanGenBtn">Сгенерировать план</button><button type="button" id="trackProfileBtn">Описания треков</button><button type="button" id="showPlanClearBtn" class="secondary">Очистить план</button><button type="submit" class="secondary">Сохранить настройки</button></div></div><div class="status-grid"><div class="status-tile"><b>Заранее готовая речь</b><span id="preparedStatus">{esc(snap.get('prepared_status',''))}</span></div><div class="status-tile"><b>Модель LM</b><span id="usedModel">{esc(snap.get('used_lm_model',''))}</span></div><div class="status-tile"><b>Последняя ошибка</b><span id="lastError">{esc(snap.get('last_error','нет'))}</span></div></div><div class="progress"><b>План:</b> <span id="showPlanStatus">{esc(snap.get('show_plan_status',''))}</span><div class="bar"><div id="showPlanFill" class="fill"></div></div><div class="mini" id="showPlanDetail"></div></div><div class="progress"><b>Описания музыки:</b> <span id="trackProfileStatus">{esc(snap.get('track_profile_status',''))}</span><div class="bar"><div id="trackProfileFill" class="fill"></div></div><div class="mini" id="trackProfileDetail"></div></div><h3>Последняя фраза ведущих</h3><textarea id="hostText" class="wide-text" readonly>{esc(snap.get('last_host_text') or 'пока нет')}</textarea></div></section>
      <section class="tab-panel" data-panel="plan"><div class="card"><h2 class="section-title">Предгенерация эфира</h2><p class="explain">Это отдельный режим: радио заранее подбирает треки, генерирует тексты, озвучивает ведущих, приветствия, новости и переходы. Ближе к концу блока оно готовит следующий блок и может перейти в live, если не успело.</p><div class="progress"><b>Статус плана:</b> <span class="showPlanStatusText">{esc(snap.get('show_plan_status',''))}</span><div class="bar"><div class="fill showPlanFillBar"></div></div><div class="mini showPlanDetailText"></div></div><div class="grid">{plan_settings}</div><div class="actions-row"><button type="button" id="showPlanGenBtn2">Сгенерировать подготовленный эфир</button><button type="button" id="showPlanUseBtn" class="secondary">Переключиться на плановый эфир</button><button type="button" id="liveModeBtn" class="secondary">Переключиться в Live</button><button type="button" id="prepareNextPlanBtn" class="secondary">Сгенерировать следующий план</button><button type="button" id="showPlanClearBtn2" class="secondary">Очистить план</button><button type="submit" class="secondary">Сохранить</button></div><h3>Программа эфира</h3><div id="planPreview" class="plan-preview"></div></div></section>
      <section class="tab-panel" data-panel="music"><div class="card"><h2 class="section-title">Музыка, факты и интернет-описания</h2><p class="explain">Агент LM Studio формулирует поисковые запросы, читает найденные страницы и собирает короткий профиль для ведущих. Второй проход удаляет неподтверждённые факты; ссылки и исходные выдержки сохраняются для проверки.</p><div class="actions-row"><button type="button" id="trackProfileBtn2">🎧 Сгенерировать/обновить описания музыки</button><button type="button" id="rescanBtn2" class="secondary">Пересканировать музыку</button></div><div class="grid">{music_settings}</div><div class="actions-row"><button type="submit" class="secondary">💾 Сохранить настройки музыки</button></div></div></section>
      <section class="tab-panel" data-panel="live"><div class="card"><h2 class="section-title">Live-режим</h2><p class="explain">Live генерирует блоки по ходу эфира. Он быстрее, но менее продуман, чем предгенерация. Если план кончится, радио может перейти сюда.</p><div class="grid">{live_settings}</div><div class="actions-row"><button type="submit" class="secondary">💾 Сохранить настройки Live</button></div></div></section>
      <section class="tab-panel" data-panel="hosts"><div class="card"><h2 class="section-title">Ведущие и гости</h2><p class="explain">Добавляй ведущих, выбирай частых участников эфира и настраивай гостя-звонящего. Гость может звучать через OmniVoice design без собственного reference-файла.</p><div class="grid">{hosts_settings}</div><div class="actions-row"><button type="submit" class="secondary">💾 Сохранить ведущих и гостя</button></div></div></section>
      <section class="tab-panel" data-panel="fun"><div class="card"><h2 class="section-title">Рубрики и игры</h2><p class="explain">Гороскопы, загадки и игра “ответь неправильно” могут работать и в Live, и в плановом эфире. Обычные разговоры ведущих не исчезают: рубрика либо совмещается с музыкальной подводкой, либо аккуратно вклинивается между обычными темами.</p><div class="progress"><b>Статус рубрик:</b> <span id="entertainmentStatus">{esc(snap.get('entertainment_status',''))}</span></div><div class="grid">{entertainment_settings}</div><div class="actions-row"><button type="submit" class="secondary">Сохранить настройки рубрик</button><button type="button" id="clearEntertainmentHistoryBtn" class="ghost">Очистить журнал повторов</button></div></div></section>
      <section class="tab-panel" data-panel="voice"><div class="card"><h2 class="section-title">Голос, подложка и обработка</h2><p class="explain">Здесь регулируется слышимость ведущих относительно музыки. Если голос тихий — подними громкость голоса и/или LUFS. Подложка должна быть тихой: примерно -24…-18 dB.</p><div class="grid">{voice_settings}</div><div class="actions-row"><button type="submit" class="secondary">💾 Сохранить настройки голоса</button></div></div></section>
      <section class="tab-panel" data-panel="lm"><div class="card"><h2 class="section-title">LM Studio</h2><p class="explain">Для подготовленного эфира можно включать Thinking в LM Studio и не добавлять /no_think. Для live можно наоборот ускорить модель.</p><div class="grid">{lm_settings}</div><div class="actions-row"><button type="submit" class="secondary">Сохранить настройки LM</button><button type="button" id="refreshModelsBtn" class="ghost">Обновить список моделей</button></div></div></section>
      <section class="tab-panel" data-panel="system"><div class="card"><h2 class="section-title">Система</h2><p class="explain">Пути, автозапуск, чистка старых файлов и базовые параметры стрима.</p><div class="grid">{system_settings}</div><div class="actions-row"><button type="submit">💾 Сохранить настройки</button></div></div></section>
    </form>
  </main>
</div>
<div class="player-card" id="playerDock">
  <div class="player-brand"><span class="player-dot" aria-hidden="true"></span><span class="player-name">{esc(cfg.get('station_name','Волна FM'))}</span><span class="player-state" id="playerState">не подключено</span></div>
  <div class="player-meta"><div class="player-track" id="playerTrack">{esc(snap.get('now_playing') if snap.get('radio_running') else '')}</div><div class="player-timeline"><input id="playerSeek" type="range" min="0" max="0" step="0.1" value="0" disabled aria-label="Перемотка накопленного эфира"><span class="player-time" id="playerTime">Эфир</span></div></div>
  <div class="player-actions">
    <audio id="player"></audio>
    <button id="playBtn" type="button" title="Воспроизвести эфир" aria-label="Воспроизвести эфир">▶</button>
    <button id="liveEdgeBtn" type="button" title="Перейти к текущему моменту эфира">К эфиру</button>
    <label class="player-volume" title="Громкость плеера">Громкость <input id="playerVolume" type="range" min="0" max="1" step="0.01" value="1"></label>
  </div>
  <button id="playerCollapseBtn" type="button" title="Свернуть/развернуть плеер" aria-label="Свернуть или развернуть плеер"></button>
</div>
<div class="toast-stack" id="toastStack" aria-live="polite"></div>
<script>
const DEFAULTS = {defaults_json};
const player = document.getElementById('player');
const STATION_NAME = {json.dumps(str(cfg.get('station_name','Волна FM')), ensure_ascii=False)};
const MODEL_FIELDS = ['lm_model','track_analyzer_model','entertainment_model'];
function byId(id) {{ return document.getElementById(id); }}
function say(t) {{
  if (!t) return;
  const stack = byId('toastStack'); if (!stack) return;
  const item = document.createElement('div');
  item.className = 'toast-item';
  item.innerHTML = `<span>${{String(t).replace(/[&<>]/g, c=>({{'&':'&amp;','<':'&lt;','>':'&gt;'}}[c]))}}</span><button type="button" title="Закрыть">×</button>`;
  item.querySelector('button').onclick = () => item.remove();
  stack.prepend(item);
  while (stack.children.length > 5) stack.lastElementChild.remove();
  setTimeout(() => item.remove(), 5200);
}}
window.say = say;
function setText(id, value) {{
  const el = byId(id); if (!el) return;
  const next = String(value ?? '');
  if (el instanceof HTMLTextAreaElement || el instanceof HTMLInputElement) {{
    if (el.value !== next) el.value = next;
  }} else if (el.textContent !== next) {{
    el.textContent = next;
  }}
}}
function setProgress(id, p) {{ const el = byId(id); if (el) el.style.width = Math.max(0, Math.min(100, Number(p)||0)) + '%'; }}
async function post(url, data={{}}) {{ const r = await fetch(url, {{method:'POST', body:new URLSearchParams(data)}}); const j = await r.json().catch(() => ({{ok:false,error:'bad json'}})); if (!j.ok) throw new Error(j.error || 'команда не выполнена'); return j; }}
function cleanFlag() {{ return byId('cleanOnControl')?.checked ? '1' : '0'; }}
function goTab(name) {{ const btn = document.querySelector(`.tab[data-tab="${{name}}"]`); const panel = document.querySelector(`[data-panel="${{name}}"]`); if (!btn || !panel) return; document.querySelectorAll('.tab').forEach(b=>b.classList.remove('active')); document.querySelectorAll('.tab-panel').forEach(p=>p.classList.remove('active')); btn.classList.add('active'); panel.classList.add('active'); localStorage.setItem('aiTruckRadio.activeTab', name); }}
document.querySelectorAll('.tab').forEach(btn => btn.onclick = () => goTab(btn.dataset.tab));
goTab(localStorage.getItem('aiTruckRadio.activeTab') || 'dash');
function normalizeForCompare(v) {{ if (v === true || v === false) return v ? '1' : '0'; if (v === null || v === undefined) return ''; return String(v).replace(',', '.').trim(); }}
function currentFieldValue(key) {{ const el = document.querySelector(`[name="${{CSS.escape(key)}}"]`); if (!el) return undefined; if (el.type === 'checkbox') return el.checked ? '1' : '0'; return el.value; }}
function defaultFieldValue(key) {{ const v = DEFAULTS[key]; if (typeof v === 'boolean') return v ? '1' : '0'; return v ?? ''; }}
function refreshResetButtons() {{ document.querySelectorAll('.reset-key').forEach(btn => {{ const key = btn.dataset.key; const cur = normalizeForCompare(currentFieldValue(key)); const def = normalizeForCompare(defaultFieldValue(key)); btn.classList.toggle('is-hidden', cur === def); }}); refreshDependencyStates(); }}
function applyValue(key, value) {{ const el = document.querySelector(`[name="${{CSS.escape(key)}}"]`); if (!el) return; if (el.type === 'checkbox') {{ el.checked = !!value; }} else {{ el.value = value ?? ''; }} el.dispatchEvent(new Event('change', {{bubbles:true}})); }}
const DEPENDENCIES = {{
  entertainment_in_live:['entertainment_enabled'], entertainment_in_planned:['entertainment_enabled'], entertainment_integration_mode:['entertainment_enabled'], entertainment_chance:['entertainment_enabled'], entertainment_min_blocks_between:['entertainment_enabled'], entertainment_generate_with_lm:['entertainment_enabled'], entertainment_agent_enabled:['entertainment_enabled','entertainment_generate_with_lm'], entertainment_model:['entertainment_enabled','entertainment_generate_with_lm','entertainment_agent_enabled'], entertainment_agent_results_per_query:['entertainment_enabled','entertainment_agent_enabled'], entertainment_agent_max_pages:['entertainment_enabled','entertainment_agent_enabled'], entertainment_agent_pages_per_topic:['entertainment_enabled','entertainment_agent_enabled'], entertainment_agent_min_page_chars:['entertainment_enabled','entertainment_agent_enabled'], entertainment_agent_page_chars:['entertainment_enabled','entertainment_agent_enabled'], entertainment_agent_total_evidence_chars:['entertainment_enabled','entertainment_agent_enabled'], entertainment_agent_page_timeout_sec:['entertainment_enabled','entertainment_agent_enabled'], entertainment_agent_max_tokens:['entertainment_enabled','entertainment_agent_enabled'], entertainment_agent_temperature:['entertainment_enabled','entertainment_agent_enabled'], entertainment_agent_factcheck_enabled:['entertainment_enabled','entertainment_agent_enabled'], entertainment_agent_no_think:['entertainment_enabled','entertainment_agent_enabled'], entertainment_agent_structured_output:['entertainment_enabled','entertainment_agent_enabled'], entertainment_pack_timeout_sec:['entertainment_enabled'], entertainment_pack_max_items:['entertainment_enabled'], rubric_web_timeout_sec:['entertainment_enabled'],
  horoscope_enabled:['entertainment_enabled'], horoscope_source_mode:['entertainment_enabled','horoscope_enabled'], horoscope_generate_before_radio:['entertainment_enabled','horoscope_enabled'], horoscope_chunk_min:['entertainment_enabled','horoscope_enabled'], horoscope_chunk_max:['entertainment_enabled','horoscope_enabled'], horoscope_blocks_before_riddle_min:['entertainment_enabled','horoscope_enabled','riddles_enabled'], horoscope_blocks_before_riddle_max:['entertainment_enabled','horoscope_enabled','riddles_enabled'],
  riddles_enabled:['entertainment_enabled'], riddle_source_mode:['entertainment_enabled','riddles_enabled'], riddle_min_blocks_between:['entertainment_enabled','riddles_enabled'], riddle_options_count:['entertainment_enabled','riddles_enabled'],
  wrong_answer_game_enabled:['entertainment_enabled'], wrong_answer_game_chance:['entertainment_enabled','wrong_answer_game_enabled'], wrong_answer_game_min_blocks_between:['entertainment_enabled','wrong_answer_game_enabled'],
  guest_enabled:['entertainment_enabled'], guest_in_live:['entertainment_enabled','guest_enabled'], guest_in_planned:['entertainment_enabled','guest_enabled'], guest_generate_before_radio:['entertainment_enabled','guest_enabled'], guest_name:['entertainment_enabled','guest_enabled'], guest_role:['entertainment_enabled','guest_enabled'], guest_voice_mode:['entertainment_enabled','guest_enabled'], guest_voice_instruct:['entertainment_enabled','guest_enabled'], guest_ref_audio:['entertainment_enabled','guest_enabled'], guest_ref_text:['entertainment_enabled','guest_enabled'], guest_chance:['entertainment_enabled','guest_enabled'], guest_min_blocks_between:['entertainment_enabled','guest_enabled'], guest_story_count:['entertainment_enabled','guest_enabled'],
  station_id_dir:['station_id_enabled'], station_id_every_tracks:['station_id_enabled'], station_id_chance:['station_id_enabled'], station_id_volume:['station_id_enabled'], station_id_fallback_tts_enabled:['station_id_enabled'],
  speech_bed_mode:['speech_bed_enabled'], speech_bed_volume:['speech_bed_enabled'], speech_compressor_enabled:['speech_radio_processing_enabled'], speech_presence_eq_enabled:['speech_radio_processing_enabled'], speech_loudnorm_enabled:['speech_radio_processing_enabled'], speech_limiter_enabled:['speech_radio_processing_enabled'],
  track_profiles_web_lookup_provider:['track_profiles_web_lookup_enabled'], track_profiles_wikipedia_languages:['track_profiles_web_lookup_enabled','track_profiles_wikipedia_enabled'], track_profiles_wikipedia_cooldown_sec:['track_profiles_web_lookup_enabled','track_profiles_wikipedia_enabled'], track_profiles_wikidata_enabled:['track_profiles_web_lookup_enabled'], track_profiles_deezer_enabled:['track_profiles_web_lookup_enabled'], track_profiles_itunes_enabled:['track_profiles_web_lookup_enabled'],
  show_plan_duration_minutes:[], show_plan_block_until_ready:[], show_plan_include_intro:[], show_plan_intro_long_opening:['show_plan_include_intro'], show_plan_continuous_extend:[], show_plan_prepare_next_threshold_items:['show_plan_continuous_extend'], show_plan_prepare_next_threshold_minutes:['show_plan_continuous_extend'], show_plan_prepare_next_fraction:['show_plan_continuous_extend'], show_plan_live_after_exhausted:[], show_plan_unique_greetings:[], show_plan_fill_music_while_generating:['show_plan_enabled']
}};
function fieldEnabled(name) {{ const el=document.querySelector(`[name="${{CSS.escape(name)}}"]`); if (!el) return false; if (el.type==='checkbox') return !!el.checked; return !!el.value; }}
function refreshDependencyStates() {{ Object.entries(DEPENDENCIES).forEach(([key, deps]) => {{ const el=document.querySelector(`[name="${{CSS.escape(key)}}"]`); if (!el) return; const box=el.closest('.setting,.check,.setting-bool') || el.parentElement; const enabled=deps.every(fieldEnabled); if (box) box.classList.toggle('disabled-setting', !enabled); }}); }}
let hostsData = [];
try {{ hostsData = JSON.parse(document.getElementById('hostsJson')?.value || '[]'); }} catch(e) {{ hostsData = []; }}
function escHtml(v) {{ return String(v ?? '').replace(/[&<>\"]/g, c=>({{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}}[c])); }}
function serializeHosts() {{ const hidden=byId('hostsJson'); if (hidden) hidden.value = JSON.stringify(hostsData); }}
function renderHostsEditor() {{
  const box=byId('hostsEditor'); if (!box) return; if (!Array.isArray(hostsData)) hostsData=[];
  box.innerHTML = hostsData.map((h,i)=>`<div class="host-card" data-host-index="${{i}}"><h3 class="host-card-head"><label class="host-title-switch"><input type="checkbox" data-host-field="enabled" ${{h.enabled === false ? '' : 'checked'}}><span class="switch-ui" aria-hidden="true"></span><span>Ведущий ${{i+1}}: ${{escHtml(h.name||'без имени')}}</span></label><button type="button" class="host-remove" data-i="${{i}}">Удалить</button></h3><label>Имя<input data-host-field="name" value="${{escHtml(h.name||'')}}"></label><label>Псевдонимы через запятую<input data-host-field="aliases" value="${{escHtml(Array.isArray(h.aliases)?h.aliases.join(', '):(h.aliases||''))}}"></label><label><span><input type="checkbox" data-host-field="intro_enabled" ${{h.intro_enabled === false ? '' : 'checked'}}> Участвует во вступлении</span></label><label><span><input type="checkbox" data-host-field="regular_enabled" ${{h.regular_enabled === false ? '' : 'checked'}}> Участвует в обычном эфире</span></label><label>Частота появления<input type="number" min="0.01" max="20" step="0.05" data-host-field="air_weight" value="${{escHtml(h.air_weight ?? 1)}}"></label><label class="wide">Персона/стиль<textarea data-host-field="persona">${{escHtml(h.persona||'')}}</textarea></label><label>OmniVoice ref audio<input data-host-field="omnivoice_ref_audio" value="${{escHtml(h.omnivoice_ref_audio||'')}}"></label><label>OmniVoice ref text<input data-host-field="omnivoice_ref_text" value="${{escHtml(h.omnivoice_ref_text||'')}}"></label><label class="wide">OmniVoice instruct<textarea data-host-field="omnivoice_instruct">${{escHtml(h.omnivoice_instruct||'')}}</textarea></label><label>Шаги OmniVoice<input data-host-field="omnivoice_steps" value="${{escHtml(h.omnivoice_steps||'')}}"></label><label>Скорость OmniVoice<input data-host-field="omnivoice_speed" value="${{escHtml(h.omnivoice_speed||'')}}"></label></div>`).join('') || '<div class="mini">Ведущих пока нет. Нажми “Добавить ведущего”.</div>';
  box.querySelectorAll('[data-host-field]').forEach(inp=>{{ const ev = inp.type === 'checkbox' ? 'change' : 'input'; inp.addEventListener(ev,()=>{{ const card=inp.closest('.host-card'); const i=Number(card.dataset.hostIndex); const f=inp.dataset.hostField; if (!hostsData[i]) return; if (f==='aliases') hostsData[i][f]=inp.value.split(',').map(x=>x.trim()).filter(Boolean); else if (inp.type==='checkbox') hostsData[i][f]=!!inp.checked; else if (f==='air_weight') hostsData[i][f]=Number(inp.value) || 1; else hostsData[i][f]=inp.value; serializeHosts(); }}); }});
  box.querySelectorAll('.host-remove').forEach(btn=>btn.onclick=()=>{{ hostsData.splice(Number(btn.dataset.i),1); serializeHosts(); renderHostsEditor(); }});
  serializeHosts();
}}
document.querySelectorAll('input,select,textarea').forEach(el => {{ el.addEventListener('input', refreshResetButtons); el.addEventListener('change', refreshResetButtons); }});
if (byId('addHostBtn')) byId('addHostBtn').onclick = () => {{ hostsData.push({{name:'Новый ведущий', enabled:true, intro_enabled:true, regular_enabled:true, air_weight:1, aliases:[], persona:'живой радиоведущий', omnivoice_ref_audio:'', omnivoice_ref_text:'', omnivoice_instruct:''}}); renderHostsEditor(); }};
if (byId('resetHostsBtn')) byId('resetHostsBtn').onclick = () => {{ hostsData = JSON.parse(JSON.stringify(DEFAULTS.hosts || [])); renderHostsEditor(); }};
renderHostsEditor();
refreshDependencyStates();
async function loadModelChoices() {{
  const health = document.querySelector('.model-health') || document.createElement('div');
  health.className = 'model-health';
  if (!health.isConnected) {{
    const lmPanel = document.querySelector('[data-panel="lm"] .grid');
    if (lmPanel) lmPanel.prepend(health);
  }}
  try {{
    const r = await fetch('/api/models?ts=' + Date.now());
    const data = await r.json();
    const models = Array.isArray(data.models) ? data.models : [];
    MODEL_FIELDS.forEach(name => {{
      const old = document.querySelector(`[name="${{name}}"]`);
      if (!old) return;
      const selected = old.value || 'local-model';
      const select = old.tagName === 'SELECT' ? old : document.createElement('select');
      if (select !== old) [...old.attributes].forEach(attr => select.setAttribute(attr.name, attr.value));
      const values = ['local-model', ...models];
      if (!values.includes(selected)) values.push(selected);
      select.innerHTML = values.map(value => `<option value="${{escHtml(value)}}"${{value === selected ? ' selected' : ''}}>${{escHtml(value)}}${{value === selected && !models.includes(value) && value !== 'local-model' ? ' — не загружена' : ''}}</option>`).join('');
      if (select !== old) old.replaceWith(select);
    }});
    health.textContent = models.length ? `LM Studio: доступно моделей — ${{models.length}}` : 'LM Studio не вернула список моделей';
    health.classList.toggle('ok', models.length > 0);
    health.classList.toggle('bad', models.length === 0);
    refreshDependencyStates();
  }} catch (err) {{
    health.textContent = 'LM Studio недоступна: список моделей не получен';
    health.classList.add('bad');
  }}
}}
loadModelChoices();
if (byId('refreshModelsBtn')) byId('refreshModelsBtn').onclick = async () => {{ await loadModelChoices(); say('Список моделей LM Studio обновлён'); }};
document.querySelectorAll('.reset-key').forEach(btn => btn.onclick = async (e) => {{ e.preventDefault(); e.stopPropagation(); const key = btn.dataset.key; try {{ const j = await post('/api/config/reset_key', {{key}}); applyValue(key, j.value); refreshResetButtons(); await refresh(); say('Параметр сброшен: ' + key); }} catch(err) {{ say('Ошибка сброса: ' + err.message); }} }});
function refreshPlayerState() {{
  const live = !!player && !player.paused && !player.ended && !!player.currentSrc;
  const dock = byId('playerDock');
  if (dock) dock.classList.toggle('is-live', live);
  const btn = byId('playBtn');
  if (btn) {{
    btn.classList.toggle('is-live', live);
    btn.textContent = live ? 'Ⅱ' : '▶';
    btn.setAttribute('aria-label', live ? 'Поставить эфир на паузу' : 'Воспроизвести эфир');
    btn.title = live ? 'Поставить локальный плеер на паузу' : 'Подключиться к локальному потоку';
  }}
  if (!live) setText('playerState', player && player.currentSrc ? 'пауза' : 'не подключено');
  updatePlayerTimeline();
}}
function playerRange() {{
  if (!player) return null;
  for (const ranges of [player.seekable, player.buffered]) {{
    if (!ranges || !ranges.length) continue;
    for (let index = ranges.length - 1; index >= 0; index--) {{
      const start = ranges.start(index), end = ranges.end(index);
      if (Number.isFinite(start) && Number.isFinite(end) && end > start) return {{start,end}};
    }}
  }}
  return null;
}}
function formatBehind(seconds) {{
  const value = Math.max(0, Math.round(seconds || 0));
  const mins = Math.floor(value / 60);
  const secs = String(value % 60).padStart(2,'0');
  return mins ? `-${{mins}}:${{secs}}` : `-0:${{secs}}`;
}}
function updatePlayerTimeline() {{
  const seek = byId('playerSeek'), label = byId('playerTime'), liveBtn = byId('liveEdgeBtn');
  if (!seek || !label || !player) return;
  const range = playerRange();
  if (!range || !Number.isFinite(range.start) || !Number.isFinite(range.end) || range.end <= range.start) {{
    seek.disabled = true; seek.min = 0; seek.max = 0; seek.value = 0; label.textContent = 'Эфир';
    if (liveBtn) liveBtn.classList.remove('is-behind');
    return;
  }}
  const current = Math.min(range.end, Math.max(range.start, Number(player.currentTime) || range.end));
  const behind = Math.max(0, range.end - current);
  seek.disabled = false; seek.min = String(range.start); seek.max = String(range.end); seek.value = String(current);
  label.textContent = behind > 8 ? formatBehind(behind) : 'Эфир';
  if (liveBtn) liveBtn.classList.toggle('is-behind', behind > 8);
  if (!player.paused) setText('playerState', behind > 8 ? `в буфере ${{formatBehind(behind)}}` : 'в эфире');
}}
if (player) {{
  ['play','pause','ended','emptied','error','loadeddata','progress','durationchange','timeupdate'].forEach(ev => player.addEventListener(ev, refreshPlayerState));
}}
if (byId('playBtn')) byId('playBtn').onclick = () => {{
  if (!player.src) player.src = '/stream.mp3?client=panel&t=' + Date.now();
  if (!player.paused && !player.ended) player.pause(); else player.play().finally(refreshPlayerState);
  refreshPlayerState();
}};
const volumeControl = byId('playerVolume');
if (volumeControl) {{
  const savedVolume = Number(localStorage.getItem('aiTruckRadio.playerVolume'));
  const initialVolume = Number.isFinite(savedVolume) ? Math.max(0, Math.min(1, savedVolume)) : 1;
  volumeControl.value = String(initialVolume);
  if (player) player.volume = initialVolume;
  volumeControl.oninput = (e) => {{
    const value = Math.max(0, Math.min(1, Number(e.target.value)));
    if (player) player.volume = value;
    localStorage.setItem('aiTruckRadio.playerVolume', String(value));
  }};
}}
if (byId('playerSeek')) byId('playerSeek').oninput = (e) => {{ if (player && !e.target.disabled) {{ player.currentTime = Number(e.target.value); updatePlayerTimeline(); }} }};
if (byId('liveEdgeBtn')) byId('liveEdgeBtn').onclick = () => {{ const range = playerRange(); if (player && range) {{ player.currentTime = Math.max(range.start, range.end - 0.15); player.play().finally(refreshPlayerState); }} }};
if (byId('playerCollapseBtn')) byId('playerCollapseBtn').onclick = () => {{
  const dock = byId('playerDock'); if (!dock) return;
  dock.classList.toggle('is-collapsed');
}};
if (byId('radioStartBtn')) byId('radioStartBtn').onclick = async () => {{ say('Запускаю радио...'); await post('/api/radio/start', {{clean: cleanFlag()}}); await refresh(); say('Радио включено'); }};
if (byId('radioStopBtn')) byId('radioStopBtn').onclick = async () => {{ say('Останавливаю радио...'); await post('/api/radio/stop'); player.pause(); player.removeAttribute('src'); player.load(); refreshPlayerState(); await refresh(); say('Радио выключено'); }};
if (byId('radioRestartBtn')) byId('radioRestartBtn').onclick = async () => {{ say('Перезапускаю радио...'); await post('/api/radio/restart', {{clean: cleanFlag()}}); player.pause(); player.removeAttribute('src'); player.load(); refreshPlayerState(); await refresh(); say('Радио перезапущено'); }};
if (byId('clearGenBtn')) byId('clearGenBtn').onclick = async () => {{ const j = await post('/api/clear_generated'); await refresh(); say(`Очищено: ${{j.files ?? 0}} файлов, ${{j.dirs ?? 0}} папок`); }};
if (byId('clearEntertainmentHistoryBtn')) byId('clearEntertainmentHistoryBtn').onclick = async () => {{ const j = await post('/api/entertainment/history/clear'); await refresh(); say(`Журнал рубрик очищен: ${{j.removed ?? 0}} записей`); }};
if (byId('skipBtn')) byId('skipBtn').onclick = async () => {{ await post('/api/skip'); say('Запрошен следующий трек'); }};
async function rescan() {{ const j = await post('/api/rescan'); await refresh(); say(`Музыка пересканирована: ${{j.music_count ?? ''}} файлов`); }}
if (byId('rescanBtn')) byId('rescanBtn').onclick = rescan; if (byId('rescanBtn2')) byId('rescanBtn2').onclick = rescan;
async function generateShowPlan() {{ const mins = document.querySelector('[name="show_plan_duration_minutes"]')?.value || '15'; say('Запускаю подготовку эфира на ' + mins + ' мин...'); const j = await post('/api/show_plan/generate', {{minutes: mins}}); goTab('plan'); await refresh(); say(j.started ? 'План начал готовиться' : 'План уже готовится'); }}
async function clearShowPlan() {{ await post('/api/show_plan/clear'); await refresh(); say('План очищен'); }}
async function useShowPlan() {{ await post('/api/show_plan/enable'); applyValue('show_plan_enabled', true); await refresh(); say('Плановый режим включён. Если эфир идёт, переключение будет после текущего элемента или по skip.'); }}
async function liveMode() {{ await post('/api/show_plan/disable'); applyValue('show_plan_enabled', false); await refresh(); say('Live-режим включён. Текущий элемент будет завершён или пропущен.'); }}
async function buildTrackProfiles() {{ const force = document.querySelector('[name="track_profiles_force_rebuild_existing"]')?.checked ? '1' : '0'; say(force === '1' ? 'Запускаю полную пересборку описаний треков...' : 'Генерирую описания только для новых треков...'); const j = await post('/api/track_profiles/build', {{force_existing: force}}); goTab('music'); await refresh(); say(j.started ? (force === '1' ? 'Полная пересборка описаний запущена' : 'Достройка описаний новых треков запущена') : 'Описания уже строятся'); }}
['showPlanGenBtn','showPlanGenBtn2'].forEach(id => {{ const el = byId(id); if (el) el.onclick = generateShowPlan; }});
['showPlanClearBtn','showPlanClearBtn2'].forEach(id => {{ const el = byId(id); if (el) el.onclick = clearShowPlan; }});
['showPlanUseBtn','modePlanBtn'].forEach(id => {{ const el = byId(id); if (el) el.onclick = useShowPlan; }});
['liveModeBtn','modeLiveBtn'].forEach(id => {{ const el = byId(id); if (el) el.onclick = liveMode; }});
['trackProfileBtn','trackProfileBtn2'].forEach(id => {{ const el = byId(id); if (el) el.onclick = buildTrackProfiles; }});
if (byId('cfgForm')) byId('cfgForm').onsubmit = async (e) => {{ e.preventDefault(); serializeHosts(); say('Сохраняю настройки...'); const fd = new FormData(e.target); const r = await fetch('/api/save_config', {{method:'POST', body:new URLSearchParams(fd)}}); const j = await r.json().catch(()=>({{ok:false}})); refreshResetButtons(); await refresh(); say(j.ok === false ? 'Не удалось сохранить настройки' : 'Настройки сохранены'); }};
function renderPlanPreview(items) {{
  const box = byId('planPreview'); if (!box) return;
  const html = (!items || !items.length) ? '<div class="mini">План ещё не сгенерирован. Нажми “Сгенерировать подготовленный эфир”.</div>' : items.map(it => {{
    const kind = it.kind === 'speech' ? '🎙 речь' : '🎵 музыка';
    const dur = it.duration_sec ? Math.round(it.duration_sec) + 'с' : '';
    const escHtml = (v) => String(v||'').replace(/[&<>]/g, c=>({{'&':'&amp;','<':'&lt;','>':'&gt;'}}[c]));
    const txt = it.text ? '<div class="text">' + escHtml(it.text).slice(0,220) + '</div>' : '';
    const title = escHtml(it.title||'');
    return `<div class="plan-item ${{it.kind}}"><div>#${{it.idx}}</div><div>${{kind}}</div><div><div class="title">${{title}}</div>${{txt}}</div><div class="mini">${{dur}}</div></div>`;
  }}).join('');
  if (box.dataset.renderedHtml !== html) {{ box.innerHTML = html; box.dataset.renderedHtml = html; }}
}}
async function refresh() {{
  const r = await fetch('/status.json?ts=' + Date.now()); const s = await r.json();
  window.__lastRadioStatus = s;
  setText('now', s.now_playing || ''); setText('kind', s.current_kind || ''); setText('clients', s.active_clients); setText('musicCount', s.music_count); setText('timeText', s.time_text || ''); setText('airMode', s.air_mode || (s.show_plan_enabled ? 'Плановый' : 'Live'));
  setText('playerTrack', s.radio_running ? (s.now_playing || '') : '');
  setText('usedModel', s.used_lm_model || ''); setText('preparedStatus', s.prepared_status || ''); setText('showPlanStatus', s.show_plan_status || ''); document.querySelectorAll('.showPlanStatusText').forEach(el=>el.textContent=s.show_plan_status||''); setText('trackProfileStatus', s.track_profile_status || ''); setText('entertainmentStatus', s.entertainment_status || ''); setText('lastError', s.last_error || 'нет'); setText('hostText', s.last_host_text || 'пока нет');
  const pp = s.show_plan_progress || {{}}; const tp = s.track_profile_progress || {{}}; setProgress('showPlanFill', pp.percent || (s.show_plan_generating ? 18 : 0)); document.querySelectorAll('.showPlanFillBar').forEach(el=>el.style.width=Math.max(0,Math.min(100,Number(pp.percent || (s.show_plan_generating ? 18 : 0))||0))+'%'); setProgress('trackProfileFill', tp.percent || (s.track_profile_building ? 12 : 0)); setText('showPlanDetail', pp.detail || (s.show_plan_generating ? 'идёт подготовка...' : '')); document.querySelectorAll('.showPlanDetailText').forEach(el=>el.textContent=pp.detail || (s.show_plan_generating ? 'идёт подготовка...' : '')); setText('trackProfileDetail', tp.detail || (s.track_profile_building ? 'идёт анализ...' : '')); renderPlanPreview(s.show_plan_preview || []);
  const ff = byId('ffmpeg'); if (ff) {{ ff.textContent = s.ffmpeg_ok ? 'найден' : 'НЕ найден'; ff.className = s.ffmpeg_ok ? 'ok' : 'bad'; }} const fp = byId('ffprobe'); if (fp) {{ fp.textContent = s.ffprobe_ok ? 'найден' : 'не найден'; fp.className = s.ffprobe_ok ? 'ok' : 'warn'; }}
  const badge = byId('runBadge'); if (badge) {{ badge.textContent = s.radio_running ? '● В эфире' : (s.radio_starting ? '● Запускается' : '● Остановлено'); badge.className = 'chip ' + (s.radio_running ? 'live' : 'stopped'); }}
  if (byId('radioStartBtn')) byId('radioStartBtn').disabled = !!(s.radio_running || s.radio_starting); if (byId('radioStopBtn')) byId('radioStopBtn').disabled = !(s.radio_running || s.radio_starting);
  const planBtn = byId('modePlanBtn'); const liveBtn = byId('modeLiveBtn'); if (planBtn && liveBtn) {{ planBtn.classList.toggle('secondary', !s.show_plan_enabled); liveBtn.classList.toggle('secondary', !!s.show_plan_enabled); }}
}}

const oldRefreshCompact = refresh;
refresh = async function() {{
  await oldRefreshCompact();
  try {{
    const s = window.__lastRadioStatus || {{}};
    setText('runMini', s.radio_running ? 'эфир идёт' : (s.radio_starting ? 'эфир запускается' : 'эфир выключен'));
    const planBtn=byId('modePlanBtn'), liveBtn=byId('modeLiveBtn');
    if (planBtn && liveBtn) {{
      planBtn.classList.toggle('secondary', !s.show_plan_enabled);
      liveBtn.classList.toggle('secondary', !!s.show_plan_enabled);
      planBtn.textContent = s.show_plan_enabled ? 'План активен' : 'Плановый';
      liveBtn.textContent = s.show_plan_enabled ? 'Live' : 'Live активен';
    }}
  }} catch(e) {{}}
  refreshResetButtons();
}};
setInterval(refresh, 1500); refresh(); refreshResetButtons();
</script>
</body></html>"""

