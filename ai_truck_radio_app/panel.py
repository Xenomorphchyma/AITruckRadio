# -*- coding: utf-8 -*-
from __future__ import annotations

import html
import json
from typing import Any, Dict, List

from ai_truck_radio_app.panel_v2 import render_panel_v2


def render_panel(engine: Any, cfg: Dict[str, Any], snap: Dict[str, Any], default_config: Dict[str, Any], app_name: str, app_version: str) -> str:
    option_labels = {
        "auto": "Автоматически",
        "short": "Короткие выходы",
        "medium": "Средние выходы",
        "long": "Длинные выходы",
        "mixed": "Чередовать длину",
        "music": "Музыка",
        "news": "Новости",
        "weather": "Погода",
        "listener_story": "Истории слушателей",
        "web_agent": "Веб-исследование",
        "legacy_apis": "Каталоги и API",
        "web_then_lm": "Интернет, затем LM",
        "safe_lm_only": "Только осторожный LM",
        "open-meteo": "Open-Meteo",
        "wttr": "wttr.in",
        "auto_mix": "Автоматически смешивать",
        "separate": "Отдельной рубрикой",
        "combine": "В обычном разговоре",
        "lm_by_date": "LM с учётом даты",
        "web_only": "Только интернет",
        "omnivoice": "OmniVoice",
        "faster-whisper": "Whisper",
        "gigaam": "GigaAM",
        "fast": "Быстро",
        "balanced": "Баланс",
        "maximum": "Максимальная точность",
        "piper": "Piper",
        "sapi": "Windows SAPI",
        "none": "Выключено",
        "clone": "Клонировать reference-голос",
        "design": "Создать голос по описанию",
        "reference": "Только reference-голос",
        "generated": "Сгенерированная подложка",
        "file": "Подложка из файла",
        "off": "Без подложки",
    }

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
        is_changed = changed(key)
        hidden = "" if is_changed else " is-hidden"
        inactive = "" if is_changed else ' hidden disabled aria-hidden="true" tabindex="-1"'
        return (
            f'<button type="button" class="reset-key{hidden}" data-key="{esc(key)}" '
            f'aria-label="Сбросить «{esc(key)}» к значению по умолчанию" '
            f'data-tooltip="По умолчанию" title="Вернуть значение по умолчанию"{inactive}>'
            '<i class="bi bi-arrow-counterclockwise" aria-hidden="true"></i></button>'
        )

    def label_for(key: str, label: str, tip: str = "") -> str:
        help_html = f'<small class="setting-help">{esc(tip)}</small>' if tip else ""
        return f'<div class="setting-copy"><span class="setting-title">{esc(label)}</span>{help_html}</div>'

    def input_text(key: str, label: str, tip: str = "", placeholder: str = "") -> str:
        return f'<div class="setting" data-setting-key="{esc(key)}">{label_for(key,label,tip)}<input aria-label="{esc(label)}" name="{esc(key)}" value="{esc(cfg.get(key, default_config.get(key, "")))}" placeholder="{esc(placeholder)}">{reset_button(key)}</div>'

    def input_num(key: str, label: str, tip: str = "", minv: str = "", maxv: str = "", step: str = "1") -> str:
        # type=number в русской Windows/Chrome не даёт нормально сохранять 0,24.
        # Поэтому это текстовое поле с inputmode=decimal; сервер принимает и точку, и запятую.
        attrs = ['inputmode="decimal"', 'data-number="1"']
        if minv != "":
            attrs.append(f'data-min="{esc(minv)}"')
        if maxv != "":
            attrs.append(f'data-max="{esc(maxv)}"')
        if step != "":
            attrs.append(f'data-step="{esc(step)}"')
        return f'<div class="setting" data-setting-key="{esc(key)}">{label_for(key,label,tip)}<input aria-label="{esc(label)}" name="{esc(key)}" type="text" {" ".join(attrs)} value="{esc(cfg.get(key, default_config.get(key, "")))}">{reset_button(key)}</div>'

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
        opts = "".join(f'<option value="{esc(o)}"{selected_attr(cfg.get(key), o)}>{esc(option_labels.get(str(o), str(o)))}</option>' for o in options)
        return f'<div class="setting" data-setting-key="{esc(key)}">{label_for(key,label,tip)}<select aria-label="{esc(label)}" name="{esc(key)}">{opts}</select>{reset_button(key)}</div>'

    checkbox_keys = [
        "weather_enabled", "news_enabled", "news_agent_enabled", "news_agent_generate_before_radio", "news_agent_factcheck_enabled", "news_agent_structured_output", "news_agent_no_think", "two_hosts_enabled", "tts_speak_host_names", "fade_enabled", "speech_bed_enabled", "speech_takeover_enabled", "speech_takeover_only_if_prepared", "speech_takeover_crossfade_enabled",
        "track_profiles_enabled", "track_profiles_web_lookup_enabled", "track_profiles_force_rebuild_existing", "track_profiles_wikipedia_enabled", "track_profiles_wikidata_enabled", "track_profiles_deezer_enabled", "track_profiles_itunes_enabled", "track_profiles_enrich_missing_web_only", "track_profiles_enrich_only_if_no_sources", "night_mode_enabled", "hotkey_enabled", "lm_enabled", "lm_append_no_think",
        "intro_before_first_track", "startup_intro_blocking", "async_prepare_dj", "show_experimental_tts_backends", "omnivoice_persistent_worker", "omnivoice_prewarm_on_radio_start", "omnivoice_normalize_ru", "omnivoice_nonverbal_tags_enabled",
        "speech_radio_processing_enabled", "speech_compressor_enabled", "speech_presence_eq_enabled", "speech_loudnorm_enabled", "speech_limiter_enabled", "jingle_enabled", "auto_generate_sweep_jingle",
        "show_plan_enabled", "show_plan_block_until_ready", "show_plan_include_intro", "show_plan_rebuild_on_start", "show_plan_restore_on_start", "show_plan_continuous_extend", "show_plan_live_after_exhausted",
        "show_plan_intro_long_opening", "show_plan_unique_greetings", "show_plan_fill_music_while_generating", "show_plan_auto_enable_after_generation", "exact_hour_time_announce_enabled", "listener_greetings_enabled", "tts_parse_validation_enabled", "radio_autostart",
        "clean_generated_on_start", "clean_generated_on_restart", "station_id_enabled", "station_id_fallback_tts_enabled", "live_blocking_dj_when_due", "live_prepare_at_track_start_when_due", "startup_intro_reserve_first_track", "host_should_use_stress_marks", "host_duo_intro_in_mostly_solo", "strict_duo_intro_require_both", "avoid_road_cliche_prompt", "season_reality_guard_enabled", "host_creative_fact_mode", "host_strict_clock_guard", "live_expected_speech_time_enabled", "omnivoice_prewarm_on_radio_start", "reference_asr_enabled", "reference_asr_review_enabled", "reference_asr_keep_model_loaded", "lm_compact_host_prompt", "entertainment_enabled", "entertainment_in_live", "entertainment_in_planned", "horoscope_enabled", "horoscope_generate_before_radio", "riddles_enabled", "wrong_answer_game_enabled", "entertainment_generate_with_lm", "entertainment_agent_enabled", "entertainment_agent_factcheck_enabled", "entertainment_agent_no_think", "entertainment_agent_structured_output", "entertainment_status_in_panel", "guest_enabled", "guest_in_live", "guest_in_planned", "guest_generate_before_radio", "guest_allow_unverified_lm", "guest_voice_warning_in_panel",
    ]
    checkbox_keys = list(dict.fromkeys(checkbox_keys))

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
        '<div class="actions-row"><button type="button" id="addHostBtn" class="button secondary"><i class="bi bi-plus-lg" aria-hidden="true"></i>Добавить ведущего</button><button type="button" id="resetHostsBtn" class="button secondary">Вернуть стандартных</button></div>',
        '<details class="voice-upload-card">'
        '<summary><span class="voice-upload-icon"><i class="bi bi-file-earmark-music" aria-hidden="true"></i></span><span><b>Reference-голос из файла</b><small>Загрузить пример речи и назначить его ведущему или гостю</small></span><i class="bi bi-chevron-down voice-upload-chevron" aria-hidden="true"></i></summary>'
        '<div class="voice-upload-content"><p class="mini">Загрузи короткий чистый фрагмент речи. Панель сохранит аудио, при необходимости расшифрует текст и сразу привяжет голос.</p>'
        '<div class="voice-upload-grid">'
        '<label>Кому назначить<select id="referenceTargetType"><option value="host">Ведущему</option><option value="guest">Гостю</option></select></label>'
        '<label id="referenceHostWrap">Ведущий<select id="referenceHostIndex"></select></label>'
        '<label>Аудиофайл<input id="referenceAudioFile" type="file" accept="audio/*"></label>'
        '<label>Движок распознавания<select id="referenceAsrBackend"><option value="faster-whisper" selected>Whisper — универсальный</option><option value="gigaam">GigaAM — для русской речи</option><option value="manual">Без распознавания — мой текст</option></select></label>'
        '<label id="referenceAsrLevelWrap">Уровень качества<select id="referenceAsrLevel"><option value="fast">Быстро</option><option value="balanced" selected>Баланс</option><option value="maximum">Максимальная точность</option></select><small class="field-hint" id="referenceAsrHint">Whisper large-v3-turbo: точнее small, но заметно быстрее полной large-v3.</small></label>'
        '<label class="wide">Точная фраза из аудио<textarea id="referenceManualText" placeholder="Необязательно для автоматических режимов. Если заполнить, ASR сверит текст с записью."></textarea></label>'
        '</div><div class="actions-row"><button type="button" id="referenceUploadBtn" class="button secondary">Загрузить и назначить голос</button><span id="referenceUploadStatus" class="mini"></span></div></div></details>',
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
        checkbox("show_plan_restore_on_start", "Восстанавливать незавершённый план", "После перезапуска продолжает сохранённый план с первого ещё не вышедшего элемента; небезопасные и отсутствующие файлы отклоняются."),
        input_num("show_plan_restore_max_age_hours", "Срок хранения плана, часов", "Старый план не будет восстановлен после этого срока.", "1", "720", "1"),
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
        input_num("track_profiles_web_delay_sec", "Пауза между веб-запросами, сек", "Помогает не ловить 429 Too Many Requests. Для Wikipedia/MusicBrainz лучше 1–2 секунды.", "0", "10", "0.1"),
        input_num("track_profiles_wikipedia_cooldown_sec", "Пауза после 429 Wikipedia, сек", "Если Wikipedia отвечает Too Many Requests, скрипт временно перестаёт её мучить и продолжает без неё.", "10", "600", "10"),
        input_text("weather_city", "Город погоды", "Город для прогноза Open-Meteo/wttr."),
        select_box("weather_provider", "Провайдер погоды", ["open-meteo", "wttr", "auto"], "auto сначала пробует Open-Meteo, потом wttr."),
        checkbox("weather_enabled", "Включить погоду", "Погода будет попадать в live/plan блоки, но не в каждую фразу."),
        checkbox("news_enabled", "Включить новости", "Проверенные материалы могут попадать в live и подготовленный эфир с заданной вероятностью."),
        checkbox("news_agent_enabled", "Собирать новости из интернета", "Агент читает источники, отдельно проверяет черновик и не выпускает сомнительный материал без решения редактора."),
        checkbox("news_agent_generate_before_radio", "Обновлять новости до старта", "Эфир стартует уже с подготовленной лентой; при сбое остаётся редакционный файл."),
        input_text("news_agent_queries", "Темы новостного поиска", "Запросы через запятую. Лучше 2–4 короткие темы, чтобы не перегружать слабую модель."),
        input_text("news_agent_official_domains", "Официальные домены", "Домены через запятую. Один официальный источник либо два независимых домена нужны для автоподтверждения."),
        input_text("news_agent_model", "Модель редактора новостей", "local-model использует выбранную модель LM Studio; можно указать отдельную небольшую модель."),
        checkbox("news_agent_factcheck_enabled", "Второй проход фактчека", "Второй запрос не переписывает новость, а только проверяет её по исходным страницам."),
        input_num("news_agent_min_independent_domains", "Независимых источников", "Минимум независимых доменов, если официального источника нет.", "2", "5", "1"),
        input_num("news_agent_max_items", "Материалов в ленте", "Ограничивает объём ленты и контекст небольшой модели.", "1", "20", "1"),
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
        select_box("tts_backend", "Движок озвучки", ["omnivoice", "piper", "sapi", "none"], "Основной сейчас OmniVoice; Piper/SAPI — запасные лёгкие режимы."),
        input_text("omnivoice_python", "Интерпретатор OmniVoice", "Обычно используется .venv_omnivoice\\Scripts\\python.exe в корне проекта."),
        input_text("omnivoice_device", "Устройство OmniVoice", "cuda:0 для GPU, cpu если нужно без видеокарты."),
        select_box("omnivoice_mode", "Режим OmniVoice", ["clone", "design", "auto"], "Клонирование использует references/maxim_ref.wav и irina_ref.wav."),
        checkbox("omnivoice_persistent_worker", "Держать OmniVoice в фоне", "Модель грузится один раз и потом быстрее озвучивает реплики."),
        checkbox("omnivoice_prewarm_on_radio_start", "Заранее грузить OmniVoice при включении радио", "Worker стартует сразу после кнопки включения, до первой реплики, чтобы первая озвучка не ждала загрузку модели."),
        checkbox("omnivoice_normalize_ru", "Нормализация и ударения", "Перед озвучкой применяет prompts/pronunciation_ru.tsv и исправляет спорные слова."),
        checkbox("omnivoice_nonverbal_tags_enabled", "OmniVoice эмоции в тексте", "Разрешает редкие официальные теги вроде [laughter], [sigh], [surprise-ah]. Неофициальные теги удаляются перед TTS."),
        input_num("omnivoice_nonverbal_tags_chance", "Шанс OmniVoice эмоции", "Вероятность разрешить LM один non-verbal tag в конкретном речевом блоке.", "0", "1", "0.05"),
        checkbox("reference_asr_enabled", "Распознавать референс-аудио", "Если включено, панель пробует сама получить точный текст из загруженного референса."),
        select_box("reference_asr_backend", "Основной распознаватель", ["faster-whisper", "gigaam"], "Whisper универсальнее; GigaAM лучше ориентирован на короткую русскую речь."),
        select_box("reference_asr_level", "Уровень распознавания", ["fast", "balanced", "maximum"], "Быстро — лёгкая модель; Баланс — основной режим; Максимум — самая точная модель или двойная проверка."),
        input_text("reference_asr_model", "Модель распознавания", "По умолчанию faster-whisper-small: достаточно точна для короткого референса и не занимает VRAM."),
        input_text("reference_asr_device", "Устройство распознавания", "cpu не отнимает видеопамять у OmniVoice; cuda можно выбрать вручную."),
        input_text("reference_asr_compute_type", "Точность вычислений", "int8 — экономный режим CPU. Для GPU обычно float16."),
        input_text("reference_asr_cache_dir", "Кэш моделей ASR", "Модели загружаются один раз в .hf_cache/asr, но после проверки выгружаются из памяти."),
        input_text("reference_asr_language", "Язык распознавания", "ru для русской речи; пусто — автоопределение."),
        input_num("reference_asr_beam_size", "Точность поиска фразы", "5 обычно точнее для коротких референс-фраз, 1 быстрее.", "1", "10", "1"),
        checkbox("reference_asr_review_enabled", "Усиленная проверка спорного текста", "Если быстрый результат расходится с ручным текстом или ручного текста нет, запускает более точную large-v3-turbo."),
        input_text("reference_asr_review_model", "Модель усиленной проверки", "large-v3-turbo заметно точнее small, но запускается только по необходимости."),
        input_text("reference_asr_review_device", "Устройство усиленной проверки", "cpu не конкурирует за VRAM с LM Studio и OmniVoice; cuda быстрее, но временно занимает видеопамять."),
        input_text("reference_asr_review_compute_type", "Вычисления усиленной проверки", "int8 — экономный режим CPU; для CUDA подходит int8_float16."),
        checkbox("reference_asr_keep_model_loaded", "Не выгружать ASR после проверки", "Обычно выключено: модель освобождает память сразу после расшифровки."),
        input_num("max_host_text_chars", "Лимит текста ведущих", "Аварийный лимит после ответа LM. 4000 достаточно для длинного планового вступления без обрубания.", "600", "12000", "100"),
        input_num("speech_voice_volume", "Громкость голоса", "Если ведущие тише музыки — подними до 1.45–1.8.", "0.2", "3", "0.05"),
        input_num("music_volume", "Громкость музыки", "Если песни давят ведущих, держи 0.70–0.85. Это не трогает громкость речи.", "0.2", "1.5", "0.05"),
        input_num("speech_loudnorm_i", "Целевая громкость речи LUFS", "Чем ближе к -10, тем громче. Безопасно: -13...-12.", "-22", "-10", "0.5"),
        input_num("speech_bed_volume", "Громкость подложки", "Радио-bed под речью. Обычно 0.04–0.10.", "0", "0.5", "0.01"),
        select_box("speech_bed_mode", "Подложка под речь", ["generated", "file", "auto", "off"], "generated — мягкий шум/bed; file — свои файлы из beds; off — без фона."),
        checkbox("fade_enabled", "Плавные входы и выходы", "Включает fade-in/fade-out для музыки и речи."),
        input_num("music_fade_out_sec", "Затухание музыки, сек", "Когда ведущий входит на хвосте, затухание считается от укороченного конца песни.", "0", "8", "0.05"),
        input_num("transition_silence_sec", "Пауза между элементами, сек", "0 = без искусственной тишины между песней и ведущим.", "0", "5", "0.05"),
        checkbox("speech_takeover_enabled", "Ведущий входит на хвосте трека", "Если после песни должен говорить ведущий, радио забирает последние секунды трека и делает fade-out без неловкой паузы."),
        input_num("speech_takeover_sec", "Сколько хвоста забрать, сек", "Обычно 3–5 секунд: песня мягко заканчивается, и ведущий начинает сразу.", "0", "12", "0.25"),
        input_num("speech_takeover_min_track_sec", "Минимальная длина трека для перехвата", "Короткие треки не укорачиваются.", "10", "180", "1"),
        checkbox("speech_takeover_only_if_prepared", "Перехватывать хвост только если речь готова", "В Live не укорачивает песню, пока следующий блок ведущих ещё не подготовлен."),
        checkbox("speech_takeover_crossfade_enabled", "Смешивать музыку с началом речи", "Настоящий crossfade: хвост песни затухает одновременно с входом ведущего, без вырезанной паузы."),
        checkbox("speech_radio_processing_enabled", "Радио-обработка речи", "Compressor + EQ + loudnorm + limiter."),
        checkbox("speech_compressor_enabled", "Компрессор", "Сжимает динамику, чтобы голос был плотнее как в эфире."),
        checkbox("speech_presence_eq_enabled", "Эквалайзер разборчивости", "Поднимает разборчивость голоса в речевом диапазоне."),
        checkbox("speech_loudnorm_enabled", "Нормализация громкости", "Выравнивает громкость речи."),
        checkbox("speech_limiter_enabled", "Ограничитель пиков", "Ловит пики, чтобы речь не клиппила."),
        checkbox("jingle_enabled", "Джинглы после речи", "Короткий переход или файл из jingles после блока ведущих."),
        input_num("jingle_chance_after_speech", "Шанс джингла", "Вероятность короткого перехода после ведущих.", "0", "1", "0.05"),
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
        input_num("lm_temperature", "Творчество модели", "0.70–0.85 для живого, но не бредового эфира.", "0", "2", "0.01"),
        input_num("lm_max_tokens", "Лимит ответа, токенов", "Для reasoning-моделей и планового эфира лучше 900–1400.", "100", "4000", "50"),
        input_num("lm_timeout_sec", "Ожидание модели, сек", "Дайте больше времени reasoning-модели и плановой генерации.", "10", "600", "5"),
        select_box("lm_reasoning_effort", "Рассуждение модели", ["auto", "none", "low", "medium", "high"], "Для Bonsai выбери «Выключено»: скрытое рассуждение иначе съедает лимит ответа до готовой реплики."),
        checkbox("lm_append_no_think", "Добавлять /no_think", "Выключи для умной предгенерации. Включай только если нужен быстрый live."),
        checkbox("lm_compact_host_prompt", "Компактный промпт для ведущих", "Сначала даёт слабой модели обязательные факты и схему, затем только ограниченный дополнительный контекст."),
        input_num("lm_host_prompt_max_chars", "Контекст ведущих, символов", "4800 обычно помещается в небольшую локальную модель без потери треков, времени, погоды и новости.", "2600", "12000", "100"),
        checkbox("tts_parse_validation_enabled", "Проверять, что TTS не потерял слова", "Если парсер диалогов потерял часть текста, отдаёт весь текст одному голосу, чтобы не пропали слова."),
        checkbox("host_creative_fact_mode", "Разрешить живые факты и ассоциации", "Ведущие могут добавлять любопытные факты, ассоциации и творческие зарисовки, но не должны выдавать фантазию как проверенную справку."),
        checkbox("host_strict_clock_guard", "Строгое время с компьютера", "Запрещает модели фантазировать про полночь/ночь/утро, если время компьютера другое."),
        input_num("tts_parse_validation_min_ratio", "Минимальная доля распознанного текста", "0.86 значит: если после разбиения на ведущих осталось меньше 86% текста, включается страховка.", "0.5", "1", "0.01"),
    ])

    system_settings = "".join([
        input_text("music_dir", "Папка музыки", "Где лежат mp3/flac/ogg треки."),
        input_text("ffmpeg_path", "Путь к FFmpeg", "Путь к ffmpeg.exe или просто ffmpeg, если он в PATH."),
        input_num("bitrate_kbps", "Битрейт стрима", "Для локального MP3-стрима обычно хватает 128–192.", "64", "320", "16"),
        checkbox("radio_autostart", "Автозапуск радио при запуске run_radio.bat", "Ты просил запуск из панели, поэтому по умолчанию выключено."),
        checkbox("clean_generated_on_start", "Чистить генерации при запуске радио", "Удаляет cache/spoken, cache/tmp, cache/show_plans, но не трогает музыку/референсы/профили."),
        checkbox("clean_generated_on_restart", "Чистить генерации при перезапуске", "То же самое для кнопки 'Перезапустить и очистить'."),
        checkbox("hotkey_enabled", "Глобальный хоткей Ctrl+Alt+N", "Следующий трек, если Windows разрешила зарегистрировать хоткей."),
    ])

    return render_panel_v2(
        cfg=cfg,
        snap=snap,
        default_config=default_config,
        app_name=app_name,
        app_version=app_version,
        settings={
            "hosts": hosts_settings,
            "live": live_settings,
            "plan": plan_settings,
            "music": music_settings,
            "fun": entertainment_settings,
            "voice": voice_settings,
            "lm": lm_settings,
            "system": system_settings,
        },
        checkbox_keys=checkbox_keys,
    )
