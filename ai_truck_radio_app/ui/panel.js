(() => {
  'use strict';

  const bootstrapNode = document.getElementById('radioBootstrap');
  const BOOT = JSON.parse(bootstrapNode?.textContent || '{}');
  const cfg = BOOT.config || {};
  const defaults = BOOT.defaults || {};
  let status = BOOT.status || {};
  let selectedPlanIdx = null;
  let selectedPlanItem = null;
  let selectedScriptLoadedIdx = null;
  let selectedScriptDirty = false;
  let selectedScriptDraft = '';
  let timelineRenderKey = '';
  let hostsData = Array.isArray(cfg.hosts) ? structuredClone(cfg.hosts) : [];
  let refreshPending = false;
  let toastTimer = null;
  let confirmResolver = null;
  let readinessWasRunning = Boolean(status.radio_running);
  let settingsProfiles = [];
  let newsRefreshPending = false;
  let newsUiError = '';
  let newsFeedRenderKey = '';
  const newsPendingDrafts = new Set();
  let speechOperationPending = false;
  let speechOperationItemIdx = null;
  let draggedPlanIdx = null;
  let dragPlaceholder = null;
  let dragGhost = null;
  let dragSourceRow = null;
  let dragTargetIdx = null;
  let dragTargetPosition = null;
  let planMovePending = false;
  let pointerDragCandidate = null;
  let pointerDragActive = false;
  let dragPointerOffsetX = 0;
  let dragPointerOffsetY = 0;
  let lmRuntime = {reachable: null, models: []};
  let omnivoiceServicePending = false;

  const $ = (selector, root = document) => root.querySelector(selector);
  const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];
  const byId = (id) => document.getElementById(id);
  const escapeHtml = (value) => String(value ?? '').replace(/[&<>'"]/g, (char) => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;'
  })[char]);
  const normalizeText = (value) => String(value ?? '').trim().replace(/\s+/g, ' ');
  const boolValue = (value) => ['1', 'true', 'yes', 'on'].includes(String(value).toLowerCase());
  const clamp = (value, min, max) => Math.max(min, Math.min(max, value));
  const iconForKind = (kind) => kind === 'speech' ? 'mic' : (kind === 'jingle' ? 'volume-up' : 'music-note-beamed');
  const labelForKind = (kind) => kind === 'speech' ? 'Ведущий' : (kind === 'jingle' ? 'Джингл' : 'Музыка');

  const GROUPS = {
    live: [
      {title: 'Ритм эфира', icon: 'broadcast', open: true, keys: ['station_style','dj_every_n_tracks_min','dj_every_n_tracks_max','dj_talk_profile','dj_topic_mode']},
      {title: 'Старт эфира', icon: 'play-circle', keys: ['intro_before_first_track','startup_intro_blocking','startup_intro_time_lead_sec']},
      {title: 'Подготовка реплик', icon: 'clock-history', keys: ['live_blocking_dj_when_due','live_prepare_at_track_start_when_due','live_expected_speech_time_enabled','live_prepare_trigger_fraction','host_should_use_stress_marks']},
      {title: 'Приветы и время', icon: 'chat-heart', keys: ['listener_greetings_enabled','exact_hour_time_announce_enabled','listener_greetings_chance','listener_greetings_every_tracks_min','listener_greetings_every_tracks_max']},
    ],
    plan: [
      {title: 'Основное', icon: 'calendar-check', open: true, keys: ['show_plan_duration_minutes','show_plan_block_until_ready','show_plan_include_intro','show_plan_intro_long_opening']},
      {title: 'Ритм программы', icon: 'music-note-list', keys: ['show_plan_min_tracks_between_speech','show_plan_max_tracks_between_speech','show_plan_long_block_chance','show_plan_unique_greetings']},
      {title: 'Продолжение эфира', icon: 'arrow-repeat', keys: ['show_plan_continuous_extend','show_plan_prepare_next_threshold_items','show_plan_prepare_next_threshold_minutes','show_plan_prepare_next_fraction','show_plan_fill_music_while_generating','show_plan_live_after_exhausted']},
      {title: 'Восстановление', icon: 'clock-history', keys: ['show_plan_restore_on_start','show_plan_restore_max_age_hours']},
    ],
    music: [
      {title: 'Профили треков', icon: 'music-note-beamed', open: true, keys: ['track_profiles_enabled','track_profiles_file','track_profiles_force_rebuild_existing','track_analyzer_model','track_profiles_fact_mode']},
      {title: 'Веб-исследование', icon: 'globe2', keys: ['track_profiles_web_lookup_enabled','track_profiles_research_mode','track_profiles_agent_max_queries','track_profiles_agent_search_results_per_query','track_profiles_agent_max_pages','track_profiles_agent_min_page_chars','track_profiles_agent_page_chars','track_profiles_agent_total_evidence_chars','track_profiles_agent_page_timeout_sec','track_profiles_agent_max_tokens','track_profiles_agent_temperature','track_profiles_agent_factcheck_enabled','track_profiles_agent_append_no_think','track_profiles_agent_structured_output','track_profiles_web_delay_sec']},
      {title: 'Каталоги и API', icon: 'database', keys: ['track_profiles_wikipedia_enabled','track_profiles_wikipedia_languages','track_profiles_wikidata_enabled','track_profiles_deezer_enabled','track_profiles_itunes_enabled','track_profiles_enrich_missing_web_only','track_profiles_enrich_only_if_no_sources','track_profiles_wikipedia_cooldown_sec']},
      {title: 'Контекст эфира', icon: 'cloud-sun', keys: ['weather_enabled','weather_city','weather_provider','listener_greetings_file']},
      {title: 'Новости и проверка', icon: 'newspaper', keys: ['news_enabled','news_agent_enabled','news_agent_generate_before_radio','news_agent_queries','news_agent_official_domains','news_agent_model','news_agent_factcheck_enabled','news_agent_min_independent_domains','news_agent_max_items']},
    ],
    fun: [
      {title: 'Частота рубрик', icon: 'grid', open: true, keys: ['entertainment_enabled','entertainment_in_live','entertainment_in_planned','entertainment_integration_mode','entertainment_chance','entertainment_min_blocks_between','entertainment_generate_with_lm']},
      {title: 'Гороскоп', icon: 'stars', keys: ['horoscope_enabled','horoscope_generate_before_radio','horoscope_source_mode','horoscope_chunk_min','horoscope_chunk_max','horoscope_blocks_before_riddle_min','horoscope_blocks_before_riddle_max']},
      {title: 'Загадки', icon: 'question-circle', keys: ['riddles_enabled','riddle_source_mode','riddle_min_blocks_between','riddle_options_count']},
      {title: 'Ответь неправильно', icon: 'emoji-laughing', keys: ['wrong_answer_game_enabled','wrong_answer_game_chance','wrong_answer_game_min_blocks_between']},
      {title: 'Агент и источники', icon: 'search', keys: ['entertainment_model','entertainment_agent_enabled','entertainment_agent_results_per_query','entertainment_agent_max_pages','entertainment_agent_pages_per_topic','entertainment_agent_min_page_chars','entertainment_agent_page_chars','entertainment_agent_total_evidence_chars','entertainment_agent_page_timeout_sec','entertainment_agent_max_tokens','entertainment_agent_temperature','entertainment_agent_factcheck_enabled','entertainment_agent_no_think','entertainment_agent_structured_output','rubric_web_timeout_sec']},
      {title: 'Память и кэш', icon: 'archive', keys: ['entertainment_history_file','entertainment_history_max_items','entertainment_daily_cache_dir','entertainment_pack_timeout_sec','entertainment_pack_max_items']},
    ],
    voice: [
      {title: 'OmniVoice', icon: 'soundwave', open: true, keys: ['tts_backend','omnivoice_python','omnivoice_device','omnivoice_mode','omnivoice_persistent_worker','omnivoice_prewarm_on_radio_start','omnivoice_normalize_ru','omnivoice_nonverbal_tags_enabled','omnivoice_nonverbal_tags_chance']},
      {title: 'Баланс и подложка', icon: 'volume-up', open: true, keys: ['speech_voice_volume','music_volume','speech_loudnorm_i','speech_bed_volume','speech_bed_mode']},
      {title: 'Переходы', icon: 'arrow-left-right', keys: ['fade_enabled','music_fade_out_sec','transition_silence_sec','speech_takeover_enabled','speech_takeover_sec','speech_takeover_min_track_sec','speech_takeover_only_if_prepared','speech_takeover_crossfade_enabled']},
      {title: 'Радио-обработка', icon: 'sliders', keys: ['speech_radio_processing_enabled','speech_compressor_enabled','speech_presence_eq_enabled','speech_loudnorm_enabled','speech_limiter_enabled']},
      {title: 'Джинглы и Station ID', icon: 'broadcast-pin', keys: ['jingle_enabled','jingle_chance_after_speech','station_id_enabled','station_id_dir','station_id_every_tracks','station_id_chance','station_id_volume','station_id_fallback_tts_enabled']},
      {title: 'Reference ASR', icon: 'file-earmark-music', keys: ['reference_asr_enabled','reference_asr_backend','reference_asr_level','reference_asr_model','reference_asr_device','reference_asr_compute_type','reference_asr_cache_dir','reference_asr_language','reference_asr_beam_size','reference_asr_review_enabled','reference_asr_review_model','reference_asr_review_device','reference_asr_review_compute_type','reference_asr_keep_model_loaded']},
      {title: 'Безопасность текста', icon: 'shield-check', keys: ['max_host_text_chars','tts_parse_validation_enabled','tts_parse_validation_min_ratio','host_should_use_stress_marks']},
    ],
    lm: [
      {title: 'Генерация текста', icon: 'cpu', open: true, keys: ['lm_enabled','lm_model','lm_temperature','lm_max_tokens','lm_timeout_sec','lm_append_no_think','lm_compact_host_prompt','lm_host_prompt_max_chars']},
      {title: 'Ограничения ведущих', icon: 'shield-check', keys: ['host_creative_fact_mode','host_strict_clock_guard','tts_parse_validation_enabled','tts_parse_validation_min_ratio']},
    ],
    system: [
      {title: 'Пути и поток', icon: 'folder2-open', open: true, keys: ['music_dir','ffmpeg_path','bitrate_kbps']},
      {title: 'Автоматизация', icon: 'power', keys: ['radio_autostart','clean_generated_on_start','clean_generated_on_restart','hotkey_enabled']},
    ],
    hosts: [
      {title: 'Состав эфира', icon: 'people', open: true, keys: ['host_intro_count','host_regular_count_min','host_regular_count_max','host_regular_multi_chance','strict_duo_intro_require_both']},
      {title: 'Гость', icon: 'telephone', keys: ['guest_enabled','guest_in_live','guest_in_planned','guest_generate_before_radio','guest_name','guest_role','guest_voice_mode','guest_voice_instruct','guest_ref_audio','guest_ref_text','guest_chance','guest_min_blocks_between','guest_story_count']},
    ],
  };

  function setText(id, value) {
    const node = byId(id);
    if (node) node.textContent = value ?? '';
  }

  function say(message, type = 'info') {
    const toast = byId('toast');
    const screen = byId('screenStatus');
    if (!toast) return;
    toast.textContent = message;
    toast.classList.toggle('error', type === 'error');
    toast.classList.add('visible');
    if (screen) screen.textContent = message;
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => toast.classList.remove('visible'), type === 'error' ? 5200 : 3200);
  }

  async function requestJson(url, options = {}) {
    const response = await fetch(url, {credentials: 'same-origin', cache: 'no-store', ...options});
    const payload = await response.json().catch(() => ({ok: false, error: `HTTP ${response.status}`}));
    if (!response.ok || payload.ok === false) throw new Error(payload.error || `Ошибка HTTP ${response.status}`);
    return payload;
  }

  async function postForm(url, values = {}) {
    const body = new URLSearchParams();
    Object.entries(values).forEach(([key, value]) => {
      if (value !== undefined && value !== null) body.set(key, typeof value === 'boolean' ? String(value) : String(value));
    });
    return requestJson(url, {method: 'POST', headers: {'Content-Type': 'application/x-www-form-urlencoded;charset=UTF-8'}, body});
  }

  function settingKey(node) {
    return node?.dataset?.settingKey || node?.querySelector?.('[name]')?.name || null;
  }

  function makeSettingsSection(definition) {
    const details = document.createElement('details');
    details.className = 'settings-section';
    details.open = Boolean(definition.open);
    details.dataset.groupTitle = definition.title.toLowerCase();
    details.innerHTML = `<summary><span><i class="bi bi-${escapeHtml(definition.icon)}" aria-hidden="true"></i>${escapeHtml(definition.title)}</span><span class="summary-hint"></span></summary><div class="settings-section-body"></div>`;
    return details;
  }

  function settingsCountLabel(count) {
    const mod10 = count % 10, mod100 = count % 100;
    const word = mod10 === 1 && mod100 !== 11 ? 'настройка' : (mod10 >= 2 && mod10 <= 4 && (mod100 < 12 || mod100 > 14) ? 'настройки' : 'настроек');
    return `${count} ${word}`;
  }

  function addSettingsSearch(form) {
    if (!form || form.querySelector('.settings-search')) return;
    const sections = $$('.settings-section', form);
    if (sections.length < 3) return;
    const wrap = document.createElement('label');
    wrap.className = 'settings-search';
    wrap.innerHTML = '<i class="bi bi-search" aria-hidden="true"></i><span class="sr-only">Поиск настройки</span><input type="search" placeholder="Найти настройку" autocomplete="off">';
    form.prepend(wrap);
    const input = $('input', wrap);
    input.addEventListener('input', () => {
      const query = normalizeText(input.value).toLowerCase();
      sections.forEach((section) => {
        let visibleCount = 0;
        $$('.setting, .setting-bool', section).forEach((field) => {
          const match = !query || normalizeText(field.textContent).toLowerCase().includes(query) || (settingKey(field) || '').toLowerCase().includes(query);
          field.hidden = !match;
          if (match) visibleCount += 1;
        });
        section.hidden = query && visibleCount === 0;
        if (query && visibleCount) section.open = true;
      });
    });
  }

  function groupSettings(sourceName) {
    const source = document.querySelector(`[data-settings-source="${sourceName}"]`);
    if (!source) return;
    const definitions = GROUPS[sourceName] || [];
    const directFields = [...source.children].filter((node) => node.matches('.setting, .setting-bool'));
    const fieldByKey = new Map(directFields.map((node) => [settingKey(node), node]));
    const fragment = document.createDocumentFragment();
    definitions.forEach((definition) => {
      const section = makeSettingsSection(definition);
      const body = $('.settings-section-body', section);
      definition.keys.forEach((key) => {
        const field = fieldByKey.get(key);
        if (!field) return;
        body.append(field);
        fieldByKey.delete(key);
      });
      if (body.children.length) {
        $('.summary-hint', section).textContent = settingsCountLabel(body.children.length);
        fragment.append(section);
      }
    });
    if (fieldByKey.size) {
      const extra = makeSettingsSection({title: 'Дополнительно', icon: 'three-dots'});
      const body = $('.settings-section-body', extra);
      fieldByKey.forEach((field) => body.append(field));
      $('.summary-hint', extra).textContent = settingsCountLabel(body.children.length);
      fragment.append(extra);
    }
    source.append(fragment);
    const form = source.closest('form');
    addSettingsSearch(form);
  }

  function injectSettings() {
    const html = BOOT.settingsHtml || {};
    $$('[data-settings-source]').forEach((source) => {
      const name = source.dataset.settingsSource;
      source.innerHTML = html[name] || '';
    });
    ['live','plan','music','fun','voice','lm','system','hosts'].forEach(groupSettings);
    $$('.tip').forEach((tip) => {
      tip.tabIndex = 0;
      tip.setAttribute('role', 'note');
      tip.setAttribute('aria-label', tip.title || 'Подсказка');
    });
    $$('input[data-number="1"]').forEach((input) => {
      input.setAttribute('aria-describedby', `${input.name}-number-hint`);
    });
  }

  function fieldValue(field) {
    if (field.type === 'checkbox') return Boolean(field.checked);
    return field.value;
  }

  function setFieldValue(key, value) {
    const fields = $$(`[name="${CSS.escape(key)}"]`);
    fields.forEach((field) => {
      if (field.type === 'checkbox') field.checked = Boolean(value);
      else field.value = value ?? '';
      field.dispatchEvent(new Event('change', {bubbles: true}));
    });
  }

  function validateForm(form) {
    let firstInvalid = null;
    $$('[data-number="1"]', form).forEach((input) => {
      input.closest('.setting')?.classList.remove('invalid');
      input.closest('.setting')?.querySelector('.field-error')?.remove();
      const raw = String(input.value).trim().replace(',', '.');
      const value = Number(raw);
      const min = input.dataset.min === undefined ? -Infinity : Number(input.dataset.min);
      const max = input.dataset.max === undefined ? Infinity : Number(input.dataset.max);
      if (!Number.isFinite(value) || value < min || value > max) {
        const setting = input.closest('.setting');
        setting?.classList.add('invalid');
        const error = document.createElement('span');
        error.className = 'field-error';
        error.textContent = Number.isFinite(value) ? `Допустимо: ${min}…${max}` : 'Введите число';
        setting?.append(error);
        firstInvalid ||= input;
      } else {
        input.value = raw;
      }
    });
    firstInvalid?.focus();
    return !firstInvalid;
  }

  function collectFormValues(form) {
    const values = {};
    $$('[name]', form).forEach((field) => {
      if (field.disabled || !field.name) return;
      if (field.type === 'file') return;
      values[field.name] = fieldValue(field);
    });
    return values;
  }

  function serializeHosts() {
    const hidden = byId('hostsJson');
    if (hidden) hidden.value = JSON.stringify(hostsData);
  }

  async function saveSettings(form) {
    if (!validateForm(form)) {
      say('Проверьте выделенные значения.', 'error');
      return false;
    }
    if (form.dataset.settingsForm === 'hosts') serializeHosts();
    const values = collectFormValues(form);
    try {
      const result = await postForm('/api/save_config', values);
      Object.assign(cfg, result.updates || values);
      updateResetButtons();
      updateFormDirtyState(form);
      say('Настройки сохранены');
      await refreshStatus();
      return true;
    } catch (error) {
      say(`Не удалось сохранить: ${error.message}`, 'error');
      return false;
    }
  }

  function settingValuesEqual(current, standard) {
    if (typeof standard === 'boolean') return Boolean(current) === standard;
    if (typeof standard === 'number') {
      const normalized = Number(String(current).trim().replace(',', '.'));
      return Number.isFinite(normalized) && normalized === standard;
    }
    if (typeof standard === 'string') return String(current ?? '') === standard;
    return JSON.stringify(current) === JSON.stringify(standard);
  }

  function updateResetButtons() {
    $$('.reset-key').forEach((button) => {
      const key = button.dataset.key;
      const field = button.closest('.setting, .setting-bool')?.querySelector(`[name="${CSS.escape(key)}"]`)
        || document.querySelector(`[name="${CSS.escape(key)}"]`);
      const current = field ? fieldValue(field) : cfg[key];
      const changed = Object.hasOwn(defaults, key) && !settingValuesEqual(current, defaults[key]);
      button.classList.toggle('is-hidden', !changed);
      button.hidden = !changed;
      button.disabled = !changed;
      button.setAttribute('aria-hidden', String(!changed));
      button.tabIndex = changed ? 0 : -1;
      button.setAttribute('aria-label', `Сбросить «${key}»`);
      button.title = 'Вернуть стандартное значение';
    });
  }

  function updateFormDirtyState(form) {
    if (!form) return;
    let dirty = $$('[name]', form).some((field) => {
      if (!field.name || !Object.hasOwn(cfg, field.name) || field.type === 'file') return false;
      return !settingValuesEqual(fieldValue(field), cfg[field.name]);
    });
    if (form.dataset.settingsForm === 'hosts') {
      dirty ||= JSON.stringify(hostsData) !== JSON.stringify(cfg.hosts || []);
    }
    form.dataset.dirty = String(dirty);
    form.classList.toggle('is-dirty', dirty);
  }

  function updateAllFormDirtyStates() {
    $$('.settings-form').forEach(updateFormDirtyState);
  }

  function selectedSettingsProfile() {
    const profileId = byId('settingsProfileSelect')?.value || 'default';
    return settingsProfiles.find((profile) => profile.id === profileId) || null;
  }

  function setSettingsProfileStatus(message, type = 'info') {
    const node = byId('settingsProfileStatus');
    if (!node) return;
    node.textContent = message || '';
    node.classList.toggle('error', type === 'error');
  }

  function renderSettingsProfiles(selectedId = null) {
    const select = byId('settingsProfileSelect');
    if (!select) return;
    const preferred = selectedId || select.value || 'default';
    select.innerHTML = settingsProfiles.map((profile) => `<option value="${escapeHtml(profile.id)}">${escapeHtml(profile.name)}${profile.builtin ? ' · встроенный' : ''}</option>`).join('');
    select.value = settingsProfiles.some((profile) => profile.id === preferred) ? preferred : 'default';
    const selected = selectedSettingsProfile();
    const builtin = !selected || Boolean(selected.builtin);
    byId('renameSettingsProfileBtn').disabled = builtin;
    byId('deleteSettingsProfileBtn').disabled = builtin;
    const name = byId('settingsProfileName');
    if (name) name.value = builtin ? '' : selected.name;
    setText('settingsProfileHint', builtin
      ? 'Встроенный профиль можно только применить; изменить или удалить его нельзя.'
      : 'Применение заменит сохранённые параметры безопасным набором из профиля.');
  }

  async function loadSettingsProfiles(selectedId = null) {
    try {
      const result = await requestJson('/api/settings_profiles');
      settingsProfiles = Array.isArray(result.profiles) ? result.profiles : [];
      renderSettingsProfiles(selectedId);
      return true;
    } catch (error) {
      setSettingsProfileStatus(`Не удалось загрузить профили: ${error.message}`, 'error');
      return false;
    }
  }

  async function openSettingsProfiles() {
    const dialog = byId('settingsProfilesDialog');
    if (!dialog) return;
    setSettingsProfileStatus('');
    await loadSettingsProfiles();
    dialog.showModal?.();
  }

  async function createSettingsProfile() {
    const name = byId('settingsProfileName')?.value.trim() || '';
    if (!name) {
      setSettingsProfileStatus('Введите название нового профиля.', 'error');
      byId('settingsProfileName')?.focus();
      return;
    }
    const activeForm = $('.view.active .settings-form');
    if (activeForm && !(await saveSettings(activeForm))) return;
    try {
      const result = await postForm('/api/settings_profiles/create', {name});
      settingsProfiles = result.profiles || [];
      renderSettingsProfiles(result.profile?.id);
      setSettingsProfileStatus(`Профиль «${result.profile?.name || name}» сохранён.`);
    } catch (error) {
      setSettingsProfileStatus(error.message, 'error');
    }
  }

  async function renameSettingsProfile() {
    const selected = selectedSettingsProfile();
    if (!selected || selected.builtin) return;
    const name = byId('settingsProfileName')?.value.trim() || '';
    if (!name) {
      setSettingsProfileStatus('Введите новое название профиля.', 'error');
      return;
    }
    try {
      const result = await postForm('/api/settings_profiles/rename', {id: selected.id, name});
      settingsProfiles = result.profiles || [];
      renderSettingsProfiles(selected.id);
      setSettingsProfileStatus(`Профиль переименован в «${result.profile?.name || name}».`);
    } catch (error) {
      setSettingsProfileStatus(error.message, 'error');
    }
  }

  async function deleteSettingsProfile() {
    const selected = selectedSettingsProfile();
    if (!selected || selected.builtin) return;
    if (!(await confirmAction('Удалить профиль?', `Профиль «${selected.name}» будет удалён без возможности восстановления.`))) return;
    try {
      const result = await postForm('/api/settings_profiles/delete', {id: selected.id});
      settingsProfiles = result.profiles || [];
      renderSettingsProfiles('default');
      setSettingsProfileStatus(`Профиль «${selected.name}» удалён.`);
    } catch (error) {
      setSettingsProfileStatus(error.message, 'error');
    }
  }

  async function applySettingsProfile() {
    const selected = selectedSettingsProfile();
    if (!selected) return;
    if (!(await confirmAction('Применить профиль?', `Сохранённые настройки будут заменены профилем «${selected.name}». Локальные пути и reference-голоса останутся без изменений.`))) return;
    try {
      const result = await postForm('/api/settings_profiles/apply', {id: selected.id});
      Object.assign(cfg, result.updates || {});
      Object.entries(result.updates || {}).forEach(([key, value]) => setFieldValue(key, value));
      updateDependencies();
      updateResetButtons();
      updateAllFormDirtyStates();
      setSettingsProfileStatus(`Профиль «${selected.name}» применён.`);
      say(`Применён профиль «${selected.name}»`);
    } catch (error) {
      setSettingsProfileStatus(error.message, 'error');
    }
  }

  function updateDependencies() {
    const enabled = (key) => Boolean(document.querySelector(`[name="${CSS.escape(key)}"]`)?.checked);
    const value = (key) => document.querySelector(`[name="${CSS.escape(key)}"]`)?.value;
    const toggle = (keys, active) => keys.forEach((key) => {
      const field = document.querySelector(`[name="${CSS.escape(key)}"]`);
      if (!field) return;
      field.disabled = !active;
      field.closest('.setting, .setting-bool')?.classList.toggle('disabled', !active);
      field.closest('.setting, .setting-bool')?.setAttribute('aria-disabled', String(!active));
    });
    toggle(['show_plan_prepare_next_threshold_items','show_plan_prepare_next_threshold_minutes','show_plan_prepare_next_fraction','show_plan_fill_music_while_generating','show_plan_live_after_exhausted'], enabled('show_plan_continuous_extend'));
    toggle(['track_profiles_research_mode','track_profiles_agent_max_queries','track_profiles_agent_search_results_per_query','track_profiles_agent_max_pages','track_profiles_agent_min_page_chars','track_profiles_agent_page_chars','track_profiles_agent_total_evidence_chars','track_profiles_agent_page_timeout_sec','track_profiles_agent_max_tokens','track_profiles_agent_temperature','track_profiles_agent_factcheck_enabled','track_profiles_agent_append_no_think','track_profiles_agent_structured_output','track_profiles_web_delay_sec'], enabled('track_profiles_web_lookup_enabled'));
    toggle(['speech_bed_volume'], value('speech_bed_mode') !== 'off');
    toggle(['speech_takeover_sec','speech_takeover_min_track_sec','speech_takeover_only_if_prepared','speech_takeover_crossfade_enabled'], enabled('speech_takeover_enabled'));
    toggle(['reference_asr_backend','reference_asr_level','reference_asr_model','reference_asr_device','reference_asr_compute_type','reference_asr_cache_dir','reference_asr_language','reference_asr_beam_size','reference_asr_review_enabled','reference_asr_review_model','reference_asr_review_device','reference_asr_review_compute_type','reference_asr_keep_model_loaded'], enabled('reference_asr_enabled'));
    toggle(['reference_asr_review_model','reference_asr_review_device','reference_asr_review_compute_type'], enabled('reference_asr_enabled') && enabled('reference_asr_review_enabled'));
    toggle(['news_agent_generate_before_radio','news_agent_queries','news_agent_official_domains','news_agent_model','news_agent_factcheck_enabled','news_agent_min_independent_domains','news_agent_max_items'], enabled('news_enabled') && enabled('news_agent_enabled'));
    toggle(['show_plan_restore_max_age_hours'], enabled('show_plan_restore_on_start'));
    toggle(['lm_host_prompt_max_chars'], enabled('lm_compact_host_prompt'));
    toggle(['station_id_dir','station_id_every_tracks','station_id_chance','station_id_volume','station_id_fallback_tts_enabled'], enabled('station_id_enabled'));
    toggle(['jingle_chance_after_speech'], enabled('jingle_enabled'));
    toggle(['guest_in_live','guest_in_planned','guest_generate_before_radio','guest_name','guest_role','guest_voice_mode','guest_voice_instruct','guest_ref_audio','guest_ref_text','guest_chance','guest_min_blocks_between','guest_story_count'], enabled('guest_enabled'));
    toggle(['horoscope_source_mode','horoscope_generate_before_radio','horoscope_chunk_min','horoscope_chunk_max','horoscope_blocks_before_riddle_min','horoscope_blocks_before_riddle_max'], enabled('horoscope_enabled'));
    toggle(['riddle_source_mode','riddle_min_blocks_between','riddle_options_count'], enabled('riddles_enabled'));
    toggle(['wrong_answer_game_chance','wrong_answer_game_min_blocks_between'], enabled('wrong_answer_game_enabled'));
  }

  function renderHosts() {
    const container = byId('hostsEditor');
    if (!container) return;
    container.innerHTML = hostsData.map((host, index) => `
      <section class="host-card" data-host-index="${index}">
        <header class="host-card-head">
          <div class="host-identity"><span class="host-avatar"><i class="bi bi-mic" aria-hidden="true"></i></span><div><b class="host-card-title">${escapeHtml(host.name || `Ведущий ${index + 1}`)}</b><small>Ведущий ${index + 1}</small></div></div>
          <div class="host-card-actions"><label class="host-enable"><span>В эфире</span><input type="checkbox" data-host-field="enabled" aria-label="Ведущий участвует в эфире" ${host.enabled !== false ? 'checked' : ''}></label><button class="remove-host" type="button" data-remove-host="${index}"><i class="bi bi-trash" aria-hidden="true"></i><span>Удалить</span></button></div>
        </header>
        <div class="host-card-body">
          <div class="host-main-grid">
            <label class="host-field"><span>Имя в эфире</span><input data-host-field="name" value="${escapeHtml(host.name || '')}"></label>
            <label class="host-field"><span>Псевдонимы</span><input data-host-field="aliases" value="${escapeHtml(Array.isArray(host.aliases) ? host.aliases.join(', ') : (host.aliases || ''))}"></label>
            <label class="host-field"><span>Частота появления</span><input data-host-field="air_weight" inputmode="decimal" value="${escapeHtml(host.air_weight ?? 1)}"><small>1 — основной; 0,2 — редкий выход</small></label>
          </div>
          <div class="host-options">
            <label class="host-option"><span><b>Вступление</b><small>Может открывать эфир</small></span><input type="checkbox" data-host-field="intro_enabled" ${host.intro_enabled !== false ? 'checked' : ''}></label>
            <label class="host-option"><span><b>Обычный эфир</b><small>Участвует в разговорных блоках</small></span><input type="checkbox" data-host-field="regular_enabled" ${host.regular_enabled !== false ? 'checked' : ''}></label>
          </div>
          <details class="host-advanced">
            <summary><span><i class="bi bi-soundwave" aria-hidden="true"></i>Голос и характер</span><small>6 настроек</small></summary>
            <div class="host-grid">
              <label class="wide">Персона и стиль<textarea data-host-field="persona">${escapeHtml(host.persona || '')}</textarea></label>
              <label>Reference-аудио<input data-host-field="omnivoice_ref_audio" value="${escapeHtml(host.omnivoice_ref_audio || '')}"></label>
              <label>Reference-текст<input data-host-field="omnivoice_ref_text" value="${escapeHtml(host.omnivoice_ref_text || '')}"></label>
              <label class="wide">Описание голоса OmniVoice<textarea data-host-field="omnivoice_instruct">${escapeHtml(host.omnivoice_instruct || '')}</textarea></label>
              <label>Шаги OmniVoice<input data-host-field="omnivoice_steps" inputmode="numeric" value="${escapeHtml(host.omnivoice_steps ?? '')}"></label>
              <label>Скорость OmniVoice<input data-host-field="omnivoice_speed" inputmode="decimal" value="${escapeHtml(host.omnivoice_speed ?? '')}"></label>
            </div>
          </details>
        </div>
      </section>`).join('');
    const hostSelect = byId('referenceHostIndex');
    if (hostSelect) hostSelect.innerHTML = hostsData.map((host, index) => `<option value="${index}">${escapeHtml(host.name || `Ведущий ${index + 1}`)}</option>`).join('');
    serializeHosts();
  }

  function updateHostField(event) {
    const field = event.target.closest('[data-host-field]');
    if (!field) return;
    const card = field.closest('[data-host-index]');
    const index = Number(card?.dataset.hostIndex);
    if (!Number.isInteger(index) || !hostsData[index]) return;
    const key = field.dataset.hostField;
    let value = field.type === 'checkbox' ? field.checked : field.value;
    if (key === 'aliases') value = String(value).split(',').map((item) => item.trim()).filter(Boolean);
    if (key === 'air_weight' || key === 'omnivoice_speed') {
      const numeric = Number(String(value).replace(',', '.'));
      value = Number.isFinite(numeric) ? numeric : value;
    }
    if (key === 'omnivoice_steps') {
      const numeric = Number.parseInt(value, 10);
      value = Number.isFinite(numeric) ? numeric : value;
    }
    hostsData[index][key] = value;
    if (key === 'name') $('.host-card-title', card).textContent = value || `Ведущий ${index + 1}`;
    serializeHosts();
  }

  function addHost() {
    const base = structuredClone((defaults.hosts || [])[0] || {});
    hostsData.push({...base, name: `Ведущий ${hostsData.length + 1}`, aliases: [], enabled: true});
    renderHosts();
  }

  function removeHost(index) {
    if (hostsData.length <= 1) { say('В эфире должен остаться хотя бы один ведущий.', 'error'); return; }
    hostsData.splice(index, 1);
    renderHosts();
  }

  function formatDuration(seconds) {
    const total = Math.max(0, Math.round(Number(seconds) || 0));
    const minutes = Math.floor(total / 60);
    return `${String(minutes).padStart(2, '0')}:${String(total % 60).padStart(2, '0')}`;
  }

  function startClockMinutes() {
    const match = String(status.time_text || '').match(/(\d{1,2}):(\d{2})/);
    if (match) return Number(match[1]) * 60 + Number(match[2]);
    const now = new Date();
    return now.getHours() * 60 + now.getMinutes();
  }

  function formatClock(totalMinutes) {
    const value = ((Math.round(totalMinutes) % 1440) + 1440) % 1440;
    return `${String(Math.floor(value / 60)).padStart(2, '0')}:${String(value % 60).padStart(2, '0')}`;
  }

  function planItems() { return Array.isArray(status.show_plan_preview) ? status.show_plan_preview : []; }

  function planItemPhase(item) {
    const itemIdx = Number(item?.idx || 0);
    const currentIdx = Number(status.show_plan_index || 0);
    const nextIdx = Number(status.show_plan_next_index || 0);
    if ((currentIdx > 0 && itemIdx === currentIdx) || item?.active) return 'current';
    if (nextIdx > 0) return itemIdx < nextIdx ? 'played' : 'future';
    return planItems().length ? 'played' : 'future';
  }

  function isSelectedSpeechEditable() {
    return selectedPlanItem?.kind === 'speech' && planItemPhase(selectedPlanItem) === 'future';
  }

  function resetSelectedScriptState(item = null) {
    selectedScriptLoadedIdx = item ? Number(item.idx) : null;
    selectedScriptDraft = item?.text || '';
    selectedScriptDirty = false;
  }

  function captureSelectedScriptDraft() {
    const textarea = byId('selectedScript');
    if (!textarea || selectedScriptLoadedIdx === null) return;
    selectedScriptDraft = textarea.value;
    const serverText = selectedPlanItem && Number(selectedPlanItem.idx) === selectedScriptLoadedIdx
      ? String(selectedPlanItem.text || '')
      : '';
    selectedScriptDirty = selectedScriptDraft !== serverText;
  }

  function inferHostNames(item) {
    const text = String(item?.text || '');
    const provided = Array.isArray(item?.hosts) ? item.hosts.map((name) => String(name || '').trim()).filter(Boolean) : [];
    if (provided.length) return [...new Set(provided)];
    const matches = [];
    hostsData.forEach((host) => {
      const canonical = String(host?.name || '').trim();
      if (!canonical) return;
      [canonical, ...(Array.isArray(host.aliases) ? host.aliases : [])].forEach((variant) => {
        const clean = String(variant || '').trim();
        if (!clean) return;
        const escaped = clean.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
        const match = new RegExp(`(^|[^А-Яа-яЁёA-Za-z-])${escaped}\\s*[:：]`, 'iu').exec(text);
        if (match) matches.push({name: canonical, index: match.index});
      });
    });
    const ordered = matches.sort((left, right) => left.index - right.index).map((match) => match.name);
    return ordered.length ? [...new Set(ordered)] : [hostsData[0]?.name || 'Ведущий'];
  }

  function formatHostNames(names, conjunction = false) {
    if (!conjunction || names.length < 2) return names.join(', ');
    if (names.length === 2) return `${names[0]} и ${names[1]}`;
    return `${names.slice(0, -1).join(', ')} и ${names.at(-1)}`;
  }

  function planItemKindLabel(item) {
    return item?.kind === 'speech' && inferHostNames(item).length > 1 ? 'Ведущие' : labelForKind(item?.kind);
  }

  function planItemTitle(item) {
    if (item?.kind !== 'speech') return item?.title || labelForKind(item?.kind);
    return `${formatHostNames(inferHostNames(item), true)} в эфире`;
  }

  function renderTimeline() {
    const timeline = byId('planTimeline');
    const empty = byId('planEmpty');
    const items = planItems();
    if (!timeline || !empty) return;
    timeline.hidden = items.length === 0;
    empty.hidden = items.length !== 0;
    if (!items.length) {
      timelineRenderKey = '';
      selectedPlanIdx = null;
      selectedPlanItem = null;
      resetSelectedScriptState();
      renderInspector();
      renderAirNext();
      updatePlayerCopy();
      return;
    }
    if (!items.some((item) => item.idx === selectedPlanIdx)) {
      const nextIdx = Number(status.show_plan_next_index || 0);
      selectedPlanIdx = items.find((item) => item.active)?.idx
        ?? items.find((item) => Number(item.idx) === nextIdx)?.idx
        ?? items[0].idx;
    }
    const nextRenderKey = JSON.stringify({items, selectedPlanIdx, current: status.show_plan_index, next: status.show_plan_next_index, running: status.radio_running});
    if (nextRenderKey !== timelineRenderKey) {
      timelineRenderKey = nextRenderKey;
      let minute = startClockMinutes();
      timeline.innerHTML = '<div class="timeline-group-label">Программа</div>' + items.map((item, position) => {
      const duration = Math.max(0, Number(item.duration_sec) || 0);
      const clock = formatClock(minute);
      minute += duration / 60;
      const selected = item.idx === selectedPlanIdx;
      const needsAudio = item.kind === 'speech' && item.audio_ready === false;
      const phase = planItemPhase(item);
      const mutable = phase === 'future';
      const state = phase === 'current' ? 'В эфире' : (phase === 'played' ? 'Сыграно' : (needsAudio ? 'Нужна озвучка' : 'Готово'));
      const subtitle = item.kind === 'speech' ? formatHostNames(inferHostNames(item)) : (item.kind === 'jingle' ? 'Волна FM' : 'Музыкальный трек');
      const itemIdx = Number(item.idx);
      const itemTitle = escapeHtml(planItemTitle(item));
      const itemKindLabel = escapeHtml(planItemKindLabel(item));
      return `<div class="timeline-row ${escapeHtml(item.kind)} ${phase}${selected ? ' selected' : ''}${needsAudio && phase === 'future' ? ' needs-audio' : ''}" data-plan-row-idx="${itemIdx}">
        <button class="drag-handle" type="button" data-plan-drag-handle ${mutable ? '' : 'disabled'} aria-label="Переместить «${itemTitle}». Используйте стрелки вверх и вниз"><i class="bi bi-grip-vertical" aria-hidden="true"></i></button>
        <button class="timeline-main" type="button" data-plan-idx="${itemIdx}" aria-pressed="${selected}">
          <span class="timeline-icon"><i class="bi bi-${iconForKind(item.kind)}" aria-hidden="true"></i></span>
          <span class="timeline-time"><b>${clock}</b><small>${formatDuration(duration)}</small></span>
          <span class="timeline-copy"><span class="timeline-kind">${itemKindLabel}</span><span class="timeline-title">${itemTitle}</span><span class="timeline-subtitle">${escapeHtml(subtitle)}</span></span>
          <span class="timeline-state-cell"><span class="timeline-state">${escapeHtml(state)}</span></span>
        </button>
        <span class="timeline-more-wrap"><button class="timeline-more" type="button" data-plan-row-menu="${itemIdx}" aria-label="Действия с «${itemTitle}»" aria-expanded="false"><i class="bi bi-three-dots" aria-hidden="true"></i></button>
          <span class="timeline-row-menu" role="menu" aria-hidden="true" hidden>
            <button type="button" role="menuitem" data-plan-item-action="duplicate" data-plan-item-index="${itemIdx}" ${mutable ? '' : 'disabled'}><i class="bi bi-copy" aria-hidden="true"></i>Дублировать</button>
            <button type="button" role="menuitem" data-plan-item-action="insert_after" data-plan-item-index="${itemIdx}" ${mutable ? '' : 'disabled'}><i class="bi bi-node-plus" aria-hidden="true"></i>Вставить после</button>
            <button type="button" role="menuitem" class="danger-text" data-plan-item-action="delete" data-plan-item-index="${itemIdx}" ${mutable ? '' : 'disabled'}><i class="bi bi-trash" aria-hidden="true"></i>Удалить</button>
          </span>
        </span>
      </div>`;
      }).join('');
    }
    selectedPlanItem = items.find((item) => item.idx === selectedPlanIdx) || items[0];
    renderInspector();
    renderAirNext();
    updatePlayerCopy();
  }

  function renderInspector() {
    const empty = byId('inspectorEmpty');
    const content = byId('inspectorContent');
    if (!selectedPlanItem) {
      if (empty) empty.hidden = false;
      if (content) content.hidden = true;
      resetSelectedScriptState();
      return;
    }
    if (empty) empty.hidden = true;
    if (content) content.hidden = false;
    const needsAudio = selectedPlanItem.kind === 'speech' && selectedPlanItem.audio_ready === false;
    const phase = planItemPhase(selectedPlanItem);
    const mutable = phase === 'future';
    const editable = selectedPlanItem.kind === 'speech' && mutable;
    setText('selectedState', phase === 'current' ? 'В эфире' : (phase === 'played' ? 'Сыграно' : (needsAudio ? 'Требуется озвучка' : 'Готово')));
    byId('selectedState')?.classList.toggle('warning', needsAudio);
    setText('selectedTitle', planItemTitle(selectedPlanItem));
    setText('selectedType', planItemKindLabel(selectedPlanItem));
    setText('selectedDuration', formatDuration(selectedPlanItem.duration_sec));
    const isSpeech = selectedPlanItem.kind === 'speech';
    byId('selectedHostRow').hidden = !isSpeech;
    byId('scriptField').hidden = !isSpeech;
    byId('speechActions').hidden = !isSpeech;
    byId('speechOperationStatus').hidden = !isSpeech || speechOperationItemIdx !== Number(selectedPlanItem.idx);
    if (isSpeech) {
      const hostNames = inferHostNames(selectedPlanItem);
      const pluralHosts = hostNames.length > 1;
      setText('selectedHost', formatHostNames(hostNames));
      setText('selectedHostLabel', pluralHosts ? 'Ведущие' : 'Ведущий');
      setText('selectedScriptLabel', pluralHosts ? 'Текст ведущих' : 'Текст ведущего');
      const itemIdx = Number(selectedPlanItem.idx);
      if (selectedScriptLoadedIdx !== itemIdx) resetSelectedScriptState(selectedPlanItem);
      if (!selectedScriptDirty) selectedScriptDraft = selectedPlanItem.text || '';
      const textarea = byId('selectedScript');
      if (textarea.value !== selectedScriptDraft) textarea.value = selectedScriptDraft;
      textarea.readOnly = !editable;
      textarea.setAttribute('aria-readonly', String(!editable));
      byId('previewSpeechBtn').disabled = needsAudio || speechOperationPending;
      byId('saveSpeechBtn').disabled = !editable || speechOperationPending;
      byId('rerenderSpeechBtn').disabled = !editable || speechOperationPending;
    }
    ['duplicatePlanItemBtn','insertAfterPlanItemBtn','deletePlanItemBtn'].forEach((id) => {
      byId(id).disabled = !mutable;
    });
  }

  function renderAirNext() {
    const list = byId('airNextList');
    if (!list) return;
    const nextIdx = Number(status.show_plan_next_index || 0);
    const items = nextIdx > 0
      ? planItems().filter((item) => Number(item.idx) >= nextIdx).slice(0, 3)
      : [];
    list.innerHTML = items.length ? items.map((item) => `<div class="compact-row ${escapeHtml(item.kind)}"><span class="kind-icon"><i class="bi bi-${iconForKind(item.kind)}" aria-hidden="true"></i></span><div><b>${escapeHtml(planItemTitle(item))}</b><small>${escapeHtml(planItemKindLabel(item))}</small></div><time>${formatDuration(item.duration_sec)}</time></div>`).join('') : '<p class="empty-copy">Следующих элементов пока нет.</p>';
  }

  function updatePlayerCopy() {
    const items = planItems();
    const currentIdx = Number(status.show_plan_index || 0);
    const nextIdx = Number(status.show_plan_next_index || 0);
    const current = items.find((item) => Number(item.idx) === currentIdx) || items.find((item) => item.active) || null;
    const next = items.find((item) => Number(item.idx) === nextIdx) || null;
    const stopped = !status.radio_running && !status.radio_starting;
    byId('playerCurrentBlock')?.classList.toggle('stopped', stopped);
    setText('playerCurrent', status.radio_running ? (status.now_playing || current?.title || 'Эфир') : (status.radio_starting ? 'Радио запускается' : 'Радио остановлено'));
    setText('playerCurrentMeta', status.radio_running ? labelForKind(status.current_kind || current?.kind) : (status.radio_starting ? 'Подготовка первого элемента' : 'Эфир не запущен'));
    setText('playerNext', next ? planItemTitle(next) : 'План не подготовлен');
    setText('playerNextMeta', next ? `${planItemKindLabel(next)} · ${formatDuration(next.duration_sec)}` : '');
  }

  function friendlyReadinessError(value) {
    const raw = String(value || '').trim();
    if (!raw) return '';
    if (/LM Studio/i.test(raw) && /(недоступ|не ответ|urlopen|connection|WinError)/i.test(raw)) {
      return 'LM Studio не запущена или недоступна. Запустите сервер в LM Studio и повторите проверку.';
    }
    if (/OmniVoice/i.test(raw) && /(недоступ|не запущ|connection|WinError)/i.test(raw)) {
      return 'OmniVoice не запущен или недоступен. Запустите сервис либо повторите действие — приложение попробует загрузить его автоматически.';
    }
    return raw;
  }

  function updateReadiness() {
    const running = Boolean(status.radio_running || status.radio_starting);
    const app = byId('appShell');
    app?.classList.toggle('radio-running', running);
    readinessWasRunning = running;
    setText('readyMusic', `${Number(status.music_count || 0)} треков`);
    const ffmpegReady = Boolean(status.ffmpeg_ok);
    const ffprobeReady = Boolean(status.ffprobe_ok);
    setText('readyFfmpeg', ffmpegReady && ffprobeReady ? 'готовы' : (!ffmpegReady && !ffprobeReady ? 'оба не найдены' : (!ffmpegReady ? 'FFmpeg не найден' : 'FFprobe не найден')));
    const backend = String(status.tts_backend || cfg.tts_backend || 'none');
    const voiceState = String(status.tts_status || '');
    const voiceLabel = backend === 'none'
      ? 'выключен'
      : (status.tts_ready ? 'готов' : ({not_initialized: 'загрузится при старте', on_demand: 'по запросу', unavailable: 'недоступен'}[voiceState] || 'проверка'));
    setText('readyVoice', voiceLabel);
    setText('readyPlan', planItems().length ? 'готов' : (status.show_plan_enabled ? 'не готов' : 'Live'));
    const error = byId('readinessError');
    if (error) {
      const friendlyError = friendlyReadinessError(status.last_error);
      error.hidden = !friendlyError;
      error.textContent = friendlyError;
    }
    $$('.readiness-list li').forEach((row) => {
      const value = $('b', row)?.textContent || '';
      const ok = !/не |недоступен|выключен|0 трек/.test(value);
      const icon = $('.bi', row);
      icon?.classList.toggle('bi-check-circle-fill', ok);
      icon?.classList.toggle('bi-exclamation-circle-fill', !ok);
      row.classList.toggle('not-ready', !ok);
    });
    updateOmnivoiceServiceCard();
  }

  function updateOmnivoiceServiceCard() {
    const card = byId('omnivoiceServiceCard');
    if (!card) return;
    const backend = String(status.tts_backend || cfg.tts_backend || 'none').toLowerCase();
    const state = String(status.tts_status || 'not_initialized');
    const isOmni = backend.includes('omni');
    const ready = isOmni && Boolean(status.tts_ready);
    const busy = omnivoiceServicePending || ['starting', 'stopping'].includes(state);
    const labels = {
      ready: 'Готов к озвучке', starting: 'Загружается…', stopping: 'Останавливается…',
      stopped: 'Остановлен', error: 'Ошибка запуска', unavailable: 'Недоступен',
      not_initialized: 'Остановлен', on_demand: 'Запускается по запросу', disabled: 'Выключен',
    };
    setText('omnivoiceServiceState', !isOmni ? 'Не выбран' : (labels[ready ? 'ready' : state] || 'Остановлен'));
    const detail = !isOmni
      ? 'Выберите OmniVoice в настройках ниже и сохраните изменения.'
      : (state === 'error' && status.tts_error
        ? friendlyReadinessError(status.tts_error)
        : (ready ? 'Модель находится в памяти и готова озвучивать реплики без долгого первого запуска.'
          : (state === 'starting' ? 'Первая загрузка модели может занять несколько минут.'
            : 'Можно загрузить голосовой движок заранее, не включая эфир.')));
    setText('omnivoiceServiceDetail', detail);
    card.dataset.state = ready ? 'ready' : state;
    const start = byId('startOmnivoiceBtn');
    const stop = byId('stopOmnivoiceBtn');
    if (start) {
      start.hidden = ready || state === 'starting' || state === 'stopping';
      start.disabled = !isOmni || busy;
    }
    if (stop) {
      stop.hidden = !(ready || state === 'starting' || state === 'error');
      stop.disabled = state === 'stopping';
      const label = $('span', stop);
      if (label) label.textContent = state === 'starting' ? 'Отменить запуск' : 'Остановить';
    }
  }

  async function controlOmnivoice(action) {
    if (omnivoiceServicePending || !['start', 'stop'].includes(action)) return;
    omnivoiceServicePending = true;
    updateOmnivoiceServiceCard();
    try {
      const result = await postForm(`/api/omnivoice/${action}`);
      if (result.message) say(result.message);
      await refreshStatus();
    } catch (error) {
      say(`Не удалось ${action === 'start' ? 'запустить' : 'остановить'} OmniVoice: ${error.message}`, 'error');
    } finally {
      omnivoiceServicePending = false;
      updateOmnivoiceServiceCard();
    }
  }

  function newsPack() {
    return status.news_pack && typeof status.news_pack === 'object' ? status.news_pack : {};
  }

  function newsItems() {
    const items = newsPack().items;
    return Array.isArray(items) ? items.filter((item) => item && typeof item === 'object') : [];
  }

  function newsStatusText() {
    const raw = status.news_status;
    if (raw && typeof raw === 'object') return String(raw.detail || raw.message || raw.status || raw.state || '');
    return String(raw || '');
  }

  function newsRelativeTime(value) {
    const timestamp = Date.parse(String(value || ''));
    if (!Number.isFinite(timestamp)) return 'время не указано';
    const seconds = Math.round((Date.now() - timestamp) / 1000);
    if (seconds < 45) return 'только что';
    if (seconds < 3600) return `${Math.max(1, Math.floor(seconds / 60))} мин назад`;
    if (seconds < 86400) return `${Math.floor(seconds / 3600)} ч назад`;
    if (seconds < 172800) return 'вчера';
    return new Intl.DateTimeFormat('ru-RU', {day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit'}).format(new Date(timestamp));
  }

  function newsExpiryLabel(value) {
    const timestamp = Date.parse(String(value || ''));
    if (!Number.isFinite(timestamp)) return '';
    if (timestamp <= Date.now()) return 'срок истёк';
    return `до ${new Intl.DateTimeFormat('ru-RU', {hour: '2-digit', minute: '2-digit'}).format(new Date(timestamp))}`;
  }

  function newsStatusMeta(value) {
    const key = String(value || '').toLowerCase();
    if (key === 'verified') return {key, label: 'Подтверждено', icon: 'check-circle-fill'};
    if (key === 'rejected') return {key, label: 'Отклонено', icon: 'x-circle-fill'};
    if (key === 'review') return {key, label: 'Требует проверки', icon: 'eye-fill'};
    return {key: 'unknown', label: 'Статус не указан', icon: 'question-circle'};
  }

  function newsSourceLinks(urls) {
    const safe = [];
    (Array.isArray(urls) ? urls : []).forEach((raw) => {
      if (safe.length >= 3) return;
      try {
        const url = new URL(String(raw));
        if (!['http:', 'https:'].includes(url.protocol)) return;
        safe.push({href: url.href, label: url.hostname.replace(/^www\./, '')});
      } catch (_) { /* Ignore malformed and non-web sources. */ }
    });
    if (!safe.length) return '<li>Источник не указан</li>';
    return '<li>Источники</li>' + safe.map((source) => `<li><a class="news-source-link" href="${escapeHtml(source.href)}" target="_blank" rel="noopener noreferrer"><i class="bi bi-box-arrow-up-right" aria-hidden="true"></i>${escapeHtml(source.label)}</a></li>`).join('');
  }

  function renderNewsCard(item) {
    const meta = newsStatusMeta(item.status);
    const draftId = String(item.draft_id || '');
    const pending = newsPendingDrafts.has(draftId);
    const expiry = newsExpiryLabel(item.expires_at);
    const published = newsRelativeTime(item.published_at);
    const actions = meta.key === 'review' && draftId
      ? `<div class="news-actions" aria-label="Проверка материала"><button class="button secondary danger-subtle" type="button" data-news-status="rejected" data-news-draft-id="${escapeHtml(draftId)}" ${pending ? 'disabled' : ''}><i class="bi bi-x-lg" aria-hidden="true"></i>Отклонить</button><button class="button primary" type="button" data-news-status="verified" data-news-draft-id="${escapeHtml(draftId)}" ${pending ? 'disabled' : ''}><i class="bi bi-check2" aria-hidden="true"></i>${pending ? 'Сохраняю…' : 'Подтвердить'}</button></div>`
      : '';
    return `<article class="news-card ${meta.key}">
      <div class="news-card-head"><span class="news-status-badge ${meta.key}"><i class="bi bi-${meta.icon}" aria-hidden="true"></i>${meta.label}</span><time class="news-published" datetime="${escapeHtml(item.published_at || '')}">${escapeHtml(published)}${expiry ? ` · ${escapeHtml(expiry)}` : ''}</time></div>
      <h2>${escapeHtml(item.title || 'Без заголовка')}</h2>
      <p class="news-card-summary">${escapeHtml(item.summary || 'Краткое содержание не подготовлено.')}</p>
      ${item.status_reason ? `<p class="news-status-reason">${escapeHtml(item.status_reason)}</p>` : ''}
      <div class="news-card-footer"><ul class="news-sources">${newsSourceLinks(item.source_urls)}</ul>${actions}</div>
    </article>`;
  }

  function newsStateMarkup(kind, title, detail) {
    const icon = kind === 'loading' ? 'arrow-repeat news-spinner' : (kind === 'error' ? 'exclamation-triangle' : 'newspaper');
    return `<div class="news-state ${kind}"><div><i class="bi bi-${icon}" aria-hidden="true"></i><h2>${escapeHtml(title)}</h2><p>${escapeHtml(detail)}</p></div></div>`;
  }

  function renderNewsFeed() {
    const feed = byId('newsFeed');
    const refreshButton = byId('newsRefreshBtn');
    if (!feed || !refreshButton) return;
    const items = newsItems();
    const pack = newsPack();
    const statusText = newsStatusText();
    const loweredStatus = statusText.toLowerCase();
    const loading = newsRefreshPending || ['обнов', 'загруз', 'подготов', 'refresh', 'loading', 'running', 'in_progress'].some((prefix) => loweredStatus.startsWith(prefix));
    const backendError = /ошиб|error|fail|недоступ/.test(loweredStatus) ? statusText : '';
    const error = newsUiError || backendError;
    refreshButton.disabled = newsRefreshPending;
    const refreshIcon = $('.bi', refreshButton);
    refreshIcon?.classList.toggle('news-spinner', newsRefreshPending);
    feed.setAttribute('aria-busy', String(loading));
    setText('newsPackBadge', `${items.length} ${items.length === 1 ? 'материал' : (items.length >= 2 && items.length <= 4 ? 'материала' : 'материалов')}`);
    const freshness = pack.created_at ? `Обновлено ${newsRelativeTime(pack.created_at)}${newsExpiryLabel(pack.expires_at) ? ` · актуально ${newsExpiryLabel(pack.expires_at)}` : ''}` : 'Лента ещё не загружена';
    setText('newsFreshness', loading ? 'Обновляю ленту…' : (error && items.length ? `Последняя лента · ${error}` : freshness));
    const fallback = byId('newsFallback');
    if (fallback) fallback.hidden = !pack.fallback_used;
    const errorBanner = byId('newsErrorBanner');
    if (errorBanner) errorBanner.hidden = !error || !items.length;
    setText('newsErrorText', error && items.length ? `Не удалось обновить ленту: ${error}` : '');
    let feedMarkup = '';
    let feedState = 'items';
    if (loading && !items.length) {
      feedState = 'loading';
      feedMarkup = newsStateMarkup('loading', 'Собираю свежие новости', 'Проверяю источники и готовлю короткие материалы для эфира.');
    } else if (error && !items.length) {
      feedState = 'error';
      feedMarkup = newsStateMarkup('error', 'Не удалось обновить ленту', error);
    } else if (!items.length) {
      feedState = 'empty';
      feedMarkup = newsStateMarkup('empty', 'Новостей пока нет', 'Обновите ленту, чтобы получить материалы для редакторской проверки.');
    } else {
      feedMarkup = items.map(renderNewsCard).join('');
    }
    const renderKey = JSON.stringify({feedState, items, error: feedState === 'error' ? error : '', pending: [...newsPendingDrafts].sort()});
    if (renderKey !== newsFeedRenderKey) {
      newsFeedRenderKey = renderKey;
      feed.innerHTML = feedMarkup;
    }
  }

  async function refreshNewsFeed() {
    if (newsRefreshPending) return;
    newsRefreshPending = true;
    newsUiError = '';
    renderNewsFeed();
    setText('newsFeedStatus', 'Обновляю новостную ленту.');
    try {
      await postForm('/api/news/refresh');
      await refreshStatus();
      say('Обновление новостей запущено');
    } catch (error) {
      newsUiError = error.message;
      setText('newsFeedStatus', `Ошибка обновления: ${error.message}`);
    } finally {
      newsRefreshPending = false;
      renderNewsFeed();
    }
  }

  async function setNewsItemStatus(draftId, nextStatus) {
    if (!draftId || !['verified', 'rejected'].includes(nextStatus) || newsPendingDrafts.has(draftId)) return;
    const item = newsItems().find((candidate) => String(candidate.draft_id || '') === draftId);
    if (!item || String(item.status || '').toLowerCase() !== 'review') return;
    if (nextStatus === 'rejected' && !(await confirmAction('Отклонить новость?', 'Материал останется в ленте с пометкой «Отклонено» и не должен использоваться в эфире.'))) return;
    newsPendingDrafts.add(draftId);
    renderNewsFeed();
    try {
      await postForm('/api/news/item/status', {draft_id: draftId, status: nextStatus});
      item.status = nextStatus;
      setText('newsFeedStatus', nextStatus === 'verified' ? 'Материал подтверждён.' : 'Материал отклонён.');
      renderNewsFeed();
      await refreshStatus();
    } catch (error) {
      say(`Не удалось обновить новость: ${error.message}`, 'error');
      setText('newsFeedStatus', `Ошибка: ${error.message}`);
    } finally {
      newsPendingDrafts.delete(draftId);
      renderNewsFeed();
    }
  }

  function runtimeDependencyMessage({voice = false, lm = false} = {}) {
    const problems = [];
    const backend = String(status.tts_backend || cfg.tts_backend || 'none').toLowerCase();
    if (voice && backend === 'none') {
      problems.push('озвучка выключена в настройках');
    } else if (voice && backend.includes('omni') && !status.tts_ready) {
      const state = String(status.tts_status || '');
      problems.push(state === 'unavailable'
        ? 'OmniVoice недоступен: проверьте окружение и путь к Python'
        : 'OmniVoice ещё не запущен; его загрузка может занять время');
    }
    if (lm && cfg.lm_enabled !== false) {
      if (lmRuntime.reachable === false) problems.push('LM Studio не запущена или недоступна');
      else if (lmRuntime.reachable === true && !lmRuntime.models.length) problems.push('в LM Studio не загружена ни одна модель');
    }
    return problems.join('; ');
  }

  function setRuntimeWarning(button, message) {
    if (!button) return;
    button.classList.toggle('has-runtime-warning', Boolean(message));
    if (message) button.title = `Внимание: ${message}.`;
    else if (button.title?.startsWith('Внимание:')) button.removeAttribute('title');
    let icon = $('.runtime-warning-icon', button);
    if (message && !icon) {
      icon = document.createElement('i');
      icon.className = 'bi bi-exclamation-triangle-fill runtime-warning-icon';
      icon.setAttribute('aria-hidden', 'true');
      button.append(icon);
    } else if (!message) {
      icon?.remove();
    }
  }

  function updateRuntimeWarnings() {
    const voiceOnly = runtimeDependencyMessage({voice: true});
    const planDependencies = runtimeDependencyMessage({voice: true, lm: true});
    ['radioToggleBtn','airPrimaryBtn','rerenderSpeechBtn'].forEach((id) => setRuntimeWarning(byId(id), voiceOnly));
    ['generatePlanTopBtn','generatePlanEmptyBtn','prepareNextPlanBtn'].forEach((id) => setRuntimeWarning(byId(id), planDependencies));
  }

  async function confirmRuntimeDependencies(action, dependencies) {
    const warning = runtimeDependencyMessage(dependencies);
    if (!warning) return true;
    return confirmAction(`Не всё готово для ${action}`, `Внимание: ${warning}. Можно продолжить, но операция может завершиться ошибкой или занять больше времени.`);
  }

  function updateStatusUi() {
    const running = Boolean(status.radio_running);
    const starting = Boolean(status.radio_starting);
    setText('stationName', cfg.station_name || 'Волна FM');
    setText('musicCount', Number(status.music_count || 0));
    setText('ffmpegTop', status.ffmpeg_ok ? 'готов' : 'не найден');
    const backend = String(status.tts_backend || cfg.tts_backend || 'none');
    const voiceState = String(status.tts_status || '');
    setText('voiceTop', backend === 'none' ? 'выключен' : (status.tts_ready ? 'готов' : (voiceState === 'not_initialized' ? 'ожидает старта' : (voiceState === 'on_demand' ? 'по запросу' : 'не готов'))));
    setText('runBadgeText', running ? 'Радио в эфире' : (starting ? 'Радио запускается' : 'Радио остановлено'));
    setText('appVersion', `${BOOT.app?.name || ''} ${status.app_version || BOOT.app?.version || ''}`.trim());
    setText('airNowTitle', running ? (status.now_playing || 'Эфир идёт') : 'Эфир остановлен');
    setText('airNowMeta', running ? `${labelForKind(status.current_kind)} · ${Number(status.active_clients || 0)} слушателей` : 'Включите радио, когда система будет готова.');
    setText('airElapsed', running ? elapsedLabel(status.current_started_ts) : '00:00');
    const toggleButtons = [byId('radioToggleBtn'), byId('airPrimaryBtn')];
    toggleButtons.forEach((button) => {
      if (!button) return;
      button.disabled = starting;
      const label = $('span', button);
      if (label) label.textContent = running ? 'Выключить эфир' : (starting ? 'Запускается' : 'Включить эфир');
      const icon = $('.bi', button);
      if (icon) icon.className = `bi ${running ? 'bi-stop-fill' : 'bi-play-fill'}`;
      button.classList.toggle('danger-subtle', running);
      button.classList.toggle('primary', !running);
    });
    ['modePlanAirBtn','modePlanBtn'].forEach((id) => byId(id)?.classList.toggle('active', Boolean(status.show_plan_enabled)));
    ['modeLiveAirBtn','modeLiveBtn'].forEach((id) => byId(id)?.classList.toggle('active', !status.show_plan_enabled));
    updateProgressUi();
    updateReadiness();
    updateRuntimeWarnings();
    renderTimeline();
    updatePlayerCopy();
    renderNewsFeed();
  }

  function elapsedLabel(startedTs) {
    const seconds = startedTs ? Math.max(0, Date.now() / 1000 - Number(startedTs)) : 0;
    return formatDuration(seconds);
  }

  function updateProgressUi() {
    const plan = status.show_plan_progress || {};
    const planPercent = clamp(Number(plan.percent || 0), 0, 100);
    const planVisible = Boolean(status.show_plan_generating || (planPercent > 0 && planPercent < 100));
    byId('planProgress').hidden = !planVisible;
    setText('planProgressStatus', status.show_plan_status || 'Подготовка плана');
    setText('planProgressPercent', `${Math.round(planPercent)}%`);
    byId('planProgressFill').style.width = `${planPercent}%`;
    setText('planProgressDetail', plan.detail || '');
    const cancelling = Boolean(status.show_plan_cancel_requested);
    const cancelButton = byId('cancelPlanBtn');
    if (cancelButton) {
      cancelButton.hidden = !status.show_plan_generating;
      cancelButton.disabled = cancelling;
      const label = $('span', cancelButton);
      if (label) label.textContent = cancelling ? 'Останавливаю…' : 'Отменить';
      const icon = $('.bi', cancelButton);
      if (icon) icon.className = `bi ${cancelling ? 'bi-arrow-repeat speech-spinner' : 'bi-x-circle'}`;
    }
    const generateButton = byId('generatePlanTopBtn');
    if (generateButton) {
      const generating = Boolean(status.show_plan_generating);
      generateButton.disabled = cancelling;
      generateButton.classList.toggle('danger-subtle', generating);
      const label = $('span', generateButton);
      if (label) label.textContent = generating ? (cancelling ? 'Останавливаю…' : 'Отменить подготовку') : 'Сгенерировать план';
      const icon = $('.bi', generateButton);
      if (icon) icon.className = `bi ${generating ? 'bi-x-circle' : 'bi-stars'}`;
    }
    const track = status.track_profile_progress || {};
    const trackPercent = clamp(Number(track.percent || 0), 0, 100);
    setText('trackProfileStatus', status.track_profile_status || 'ожидание');
    byId('trackProfileFill').style.width = `${trackPercent}%`;
    setText('trackProfileDetail', track.detail || '');
    setText('entertainmentStatus', status.entertainment_status || 'ожидание');
  }

  async function refreshStatus() {
    if (refreshPending) return;
    refreshPending = true;
    try {
      status = await requestJson(`/api/status?ts=${Date.now()}`);
      updateStatusUi();
    } catch (error) {
      setText('runBadgeText', 'Панель не подключена');
    } finally {
      refreshPending = false;
    }
  }

  function currentView() { return $('.view.active')?.dataset.view || 'plan'; }

  function setSidebarOpen(open) {
    byId('sidebar')?.classList.toggle('open', Boolean(open));
    byId('mobileMenuBtn')?.setAttribute('aria-expanded', String(Boolean(open)));
  }

  function setPlanSettingsOpen(open) {
    const drawer = byId('planSettingsDrawer');
    drawer?.classList.toggle('open', Boolean(open));
    drawer?.setAttribute('aria-hidden', String(!open));
    byId('planSettingsBtn')?.setAttribute('aria-expanded', String(Boolean(open)));
  }

  function setPlanMoreOpen(open, {focus = false} = {}) {
    const menu = byId('planMoreMenu');
    if (!menu) return;
    menu.hidden = !open;
    menu.setAttribute('aria-hidden', String(!open));
    byId('planMoreBtn')?.setAttribute('aria-expanded', String(Boolean(open)));
    if (open && focus) $('button', menu)?.focus();
  }

  function navigate(view, {replace = false} = {}) {
    if (!document.querySelector(`[data-view="${CSS.escape(view)}"]`)) view = 'plan';
    $$('.view').forEach((panel) => {
      const active = panel.dataset.view === view;
      panel.classList.toggle('active', active);
      panel.hidden = !active;
    });
    $$('.nav-item').forEach((button) => {
      const active = button.dataset.viewTarget === view;
      button.classList.toggle('active', active);
      if (active) button.setAttribute('aria-current', 'page'); else button.removeAttribute('aria-current');
    });
    setSidebarOpen(false);
    const hash = `#${view}`;
    if (location.hash !== hash) history[replace ? 'replaceState' : 'pushState'](null, '', hash);
    localStorage.setItem('aiTruckRadio.activeView', view);
  }

  async function confirmAction(title, text) {
    const dialog = byId('confirmDialog');
    if (!dialog?.showModal) return window.confirm(`${title}\n\n${text}`);
    setText('confirmTitle', title);
    setText('confirmText', text);
    dialog.showModal();
    return new Promise((resolve) => {
      confirmResolver = resolve;
      dialog.addEventListener('close', () => {
        const accepted = dialog.returnValue === 'confirm';
        confirmResolver?.(accepted);
        confirmResolver = null;
      }, {once: true});
    });
  }

  async function startRadio() {
    if (!(await confirmRuntimeDependencies('запуска эфира', {voice: true}))) return;
    const clean = Boolean(cfg.clean_generated_on_start);
    if (clean && !(await confirmAction('Включить радио с очисткой?', 'Будут удалены только старые сгенерированные реплики и планы. Музыка и reference-голоса останутся.'))) return;
    say('Запускаю радио…');
    try { await postForm('/api/radio/start', {clean}); await refreshStatus(); say('Радио запускается'); }
    catch (error) { say(`Не удалось запустить: ${error.message}`, 'error'); }
  }

  async function stopRadio() {
    say('Останавливаю радио…');
    try {
      await postForm('/api/radio/stop');
      const player = byId('radioPlayer');
      player?.pause();
      await refreshStatus();
      say('Радио остановлено');
    } catch (error) { say(`Не удалось остановить: ${error.message}`, 'error'); }
  }

  async function toggleRadio() { return status.radio_running ? stopRadio() : startRadio(); }

  async function restartRadio() {
    const clean = Boolean(cfg.clean_generated_on_restart);
    if (!(await confirmAction('Перезапустить радио?', clean ? 'Текущий эфир прервётся, временные генерации будут очищены.' : 'Текущий эфир прервётся и запустится заново.'))) return;
    say('Перезапускаю радио…');
    try { await postForm('/api/radio/restart', {clean}); await refreshStatus(); say('Перезапуск начался'); }
    catch (error) { say(`Не удалось перезапустить: ${error.message}`, 'error'); }
  }

  async function skipCurrent() {
    try { await postForm('/api/skip'); say('Перехожу к следующему элементу'); }
    catch (error) { say(`Не удалось перейти: ${error.message}`, 'error'); }
  }

  async function generatePlan() {
    if (status.show_plan_generating) {
      await cancelPlanGeneration();
      return;
    }
    if (!(await confirmRuntimeDependencies('подготовки плана', {voice: true, lm: true}))) return;
    const minutes = document.querySelector('[name="show_plan_duration_minutes"]')?.value || cfg.show_plan_duration_minutes || 15;
    say(`Готовлю план на ${minutes} мин…`);
    try { const result = await postForm('/api/show_plan/generate', {minutes}); navigate('plan'); say(result.started ? 'Подготовка плана запущена' : 'План уже готовится'); await refreshStatus(); }
    catch (error) { say(`Не удалось подготовить план: ${error.message}`, 'error'); }
  }

  async function cancelPlanGeneration() {
    if (!status.show_plan_generating || status.show_plan_cancel_requested) return;
    try {
      const result = await postForm('/api/show_plan/cancel');
      if (result.cancelled) say('Отменяю подготовку плана…');
      else say('Активной подготовки уже нет');
      await refreshStatus();
    } catch (error) {
      say(`Не удалось отменить подготовку: ${error.message}`, 'error');
    }
  }

  async function prepareNextPlan() {
    if (!(await confirmRuntimeDependencies('подготовки следующего блока', {voice: true, lm: true}))) return;
    try { await postForm('/api/show_plan/prepare_next'); say('Следующий блок готовится'); await refreshStatus(); }
    catch (error) { say(`Не удалось подготовить следующий блок: ${error.message}`, 'error'); }
  }

  async function setAirMode(planned) {
    setPlanMoreOpen(false);
    try { await postForm(planned ? '/api/show_plan/enable' : '/api/show_plan/disable'); await refreshStatus(); say(planned ? 'Плановый режим включён' : 'Live-режим включён'); }
    catch (error) { say(`Не удалось переключить режим: ${error.message}`, 'error'); }
  }

  async function clearPlan() {
    setPlanMoreOpen(false);
    if (!(await confirmAction('Очистить план?', 'Подготовленная программа будет удалена. Музыка и настройки не изменятся.'))) return;
    try { await postForm('/api/show_plan/clear'); selectedPlanIdx = null; await refreshStatus(); say('План очищен'); }
    catch (error) { say(`Не удалось очистить план: ${error.message}`, 'error'); }
  }

  async function buildProfiles() {
    const force = Boolean(document.querySelector('[name="track_profiles_force_rebuild_existing"]')?.checked);
    try { const result = await postForm('/api/track_profiles/build', {force_existing: force}); say(result.started ? 'Обновление описаний запущено' : 'Описания уже обновляются'); await refreshStatus(); }
    catch (error) { say(`Не удалось обновить описания: ${error.message}`, 'error'); }
  }

  async function rescanMusic() {
    try { const result = await postForm('/api/rescan'); setText('musicCount', result.music_count); say(`Найдено треков: ${result.music_count}`); await refreshStatus(); }
    catch (error) { say(`Не удалось пересканировать: ${error.message}`, 'error'); }
  }

  async function clearGenerated() {
    if (!(await confirmAction('Очистить кэш?', 'Будут удалены временные реплики, промежуточные файлы и подготовленные планы.'))) return;
    try { const result = await postForm('/api/clear_generated'); say(`Удалено файлов: ${result.files || 0}`); await refreshStatus(); }
    catch (error) { say(`Не удалось очистить кэш: ${error.message}`, 'error'); }
  }

  async function clearEntertainmentHistory() {
    if (!(await confirmAction('Очистить журнал повторов?', 'Рубрики смогут повториться уже в следующих эфирах.'))) return;
    try { const result = await postForm('/api/entertainment/history/clear'); say(`Удалено записей: ${result.removed || 0}`); }
    catch (error) { say(`Не удалось очистить журнал: ${error.message}`, 'error'); }
  }

  async function saveSelectedSpeech(rerender = false) {
    if (!selectedPlanItem || selectedPlanItem.kind !== 'speech') return;
    if (!isSelectedSpeechEditable()) {
      say('Идущую или завершённую реплику нельзя изменить.', 'error');
      return;
    }
    const text = byId('selectedScript').value.trim();
    if (!text) { say('Текст ведущего не может быть пустым.', 'error'); return; }
    setSpeechOperationState('loading', rerender ? 'Создаю новую озвучку…' : 'Сохраняю текст…');
    try {
      const result = await postForm('/api/show_plan/item/text', {index: selectedPlanItem.idx, text, rerender});
      selectedPlanItem.text = result.text || text;
      selectedPlanItem.audio_ready = Boolean(result.audio_ready);
      resetSelectedScriptState(selectedPlanItem);
      byId('selectedScript').value = selectedScriptDraft;
      renderInspector();
      setSpeechOperationState('success', rerender ? 'Озвучка готова и привязана к реплике.' : 'Текст сохранён. Для выхода в эфир нужна озвучка.');
      say(rerender ? 'Текст и озвучка обновлены' : 'Текст сохранён. Переозвучьте реплику, чтобы вернуть её в эфир.');
      await refreshStatus();
    } catch (error) {
      setSpeechOperationState('error', rerender ? `Не удалось переозвучить: ${error.message}` : `Не удалось сохранить: ${error.message}`);
      say(`Не удалось сохранить текст: ${error.message}`, 'error');
    }
  }

  function setSpeechOperationState(state, message) {
    speechOperationPending = state === 'loading';
    speechOperationItemIdx = selectedPlanItem ? Number(selectedPlanItem.idx) : null;
    const node = byId('speechOperationStatus');
    if (node) {
      node.className = `speech-operation-status ${state || ''}`.trim();
      node.textContent = message || '';
    }
    renderInspector();
    const button = byId('rerenderSpeechBtn');
    if (button) button.innerHTML = speechOperationPending
      ? '<i class="bi bi-arrow-repeat speech-spinner" aria-hidden="true"></i>Озвучиваю…'
      : '<i class="bi bi-arrow-clockwise" aria-hidden="true"></i>Переозвучить';
    updateRuntimeWarnings();
  }

  async function rerenderSelectedSpeech() {
    if (!isSelectedSpeechEditable()) return;
    const warning = runtimeDependencyMessage({voice: true});
    const detail = 'До успешного завершения прежняя озвучка останется доступной. После создания новая версия заменит её.' + (warning ? ` Внимание: ${warning}.` : '');
    if (!(await confirmAction('Переозвучить реплику?', detail))) return;
    await saveSelectedSpeech(true);
  }

  function closeTimelineRowMenus(except = null) {
    $$('.timeline-row-menu').forEach((menu) => {
      if (menu === except) return;
      menu.hidden = true;
      menu.setAttribute('aria-hidden', 'true');
      menu.closest('.timeline-more-wrap')?.querySelector('.timeline-more')?.setAttribute('aria-expanded', 'false');
    });
  }

  function toggleTimelineRowMenu(button) {
    const menu = button?.closest('.timeline-more-wrap')?.querySelector('.timeline-row-menu');
    if (!menu) return;
    const open = menu.hidden;
    closeTimelineRowMenus(open ? menu : null);
    menu.hidden = !open;
    menu.setAttribute('aria-hidden', String(!open));
    button.setAttribute('aria-expanded', String(open));
    if (open) $('button:not(:disabled)', menu)?.focus();
  }

  async function mutatePlanItem(action, index) {
    const item = planItems().find((candidate) => Number(candidate.idx) === Number(index));
    if (!item || planItemPhase(item) !== 'future') {
      say('Идущий или завершённый элемент нельзя изменить.', 'error');
      return;
    }
    if (action === 'delete' && !(await confirmAction('Удалить элемент плана?', `«${planItemTitle(item)}» будет удалён из программы.`))) return;
    if (!['duplicate', 'insert_after', 'delete'].includes(action)) return;
    closeTimelineRowMenus();
    try {
      const result = await postForm('/api/show_plan/item/action', {index, action});
      selectedPlanIdx = Number(result.selected_index || 0) || null;
      await refreshStatus();
      say(action === 'delete' ? 'Элемент удалён' : (action === 'duplicate' ? 'Элемент продублирован' : 'Новый элемент вставлен'));
    } catch (error) {
      say(`Не удалось изменить план: ${error.message}`, 'error');
    }
  }

  async function movePlanItem(index, targetIndex, position) {
    if (index === targetIndex || planMovePending) return false;
    const movingForward = index < targetIndex;
    const rawTarget = position === 'after'
      ? targetIndex + (movingForward ? 0 : 1)
      : targetIndex - (movingForward ? 1 : 0);
    const finalTarget = clamp(rawTarget, 1, planItems().length);
    if (finalTarget === index) return false;
    planMovePending = true;
    const timeline = byId('planTimeline');
    timeline?.classList.add('plan-reorder-pending');
    timeline?.setAttribute('aria-busy', 'true');
    say('Сохраняю новый порядок…');
    try {
      const result = await postForm('/api/show_plan/item/action', {index, action: 'move', target_index: finalTarget});
      selectedPlanIdx = Number(result.selected_index || 0) || null;
      await refreshStatus();
      say('Порядок плана обновлён');
      return true;
    } catch (error) {
      say(`Не удалось переместить элемент: ${error.message}`, 'error');
      return false;
    } finally {
      cleanupPlanDrag();
      planMovePending = false;
      timeline?.classList.remove('plan-reorder-pending');
      timeline?.removeAttribute('aria-busy');
    }
  }

  function cleanupPlanDrag() {
    dragSourceRow?.classList.remove('dragging', 'dragging-collapsed');
    draggedPlanIdx = null;
    dragSourceRow = null;
    dragTargetIdx = null;
    dragTargetPosition = null;
    dragPlaceholder?.remove();
    dragGhost?.remove();
    dragPlaceholder = null;
    dragGhost = null;
    pointerDragActive = false;
    $$('.timeline-row').forEach((node) => node.classList.remove('dragging', 'dragging-collapsed', 'drop-before', 'drop-after'));
  }

  function placePlanDropPlaceholder(row, position) {
    if (!dragPlaceholder || !row?.parentNode) return;
    const anchor = position === 'after' ? row.nextSibling : row;
    row.parentNode.insertBefore(dragPlaceholder, anchor);
    dragTargetIdx = Number(row.dataset.planRowIdx);
    dragTargetPosition = position;
  }

  function beginPointerPlanDrag(event) {
    const candidate = pointerDragCandidate;
    if (!candidate || planMovePending) return;
    const {row, handle, pointerId, startX, startY} = candidate;
    const rect = row.getBoundingClientRect();
    cleanupPlanDrag();
    pointerDragCandidate = candidate;
    draggedPlanIdx = Number(row.dataset.planRowIdx);
    dragSourceRow = row;
    dragPointerOffsetX = clamp(startX - rect.left, 20, Math.max(20, rect.width - 20));
    dragPointerOffsetY = clamp(startY - rect.top, 12, Math.max(12, rect.height - 12));

    dragGhost = row.cloneNode(true);
    dragGhost.classList.remove('selected');
    dragGhost.classList.add('timeline-drag-ghost');
    dragGhost.style.setProperty('--drag-ghost-width', `${rect.width}px`);
    dragGhost.setAttribute('aria-hidden', 'true');
    document.body.append(dragGhost);

    dragPlaceholder = document.createElement('div');
    dragPlaceholder.className = 'timeline-drop-placeholder';
    dragPlaceholder.style.height = `${rect.height}px`;
    dragPlaceholder.setAttribute('aria-hidden', 'true');
    row.parentNode.insertBefore(dragPlaceholder, row);
    row.classList.add('dragging', 'dragging-collapsed');
    pointerDragActive = true;
    try { handle.setPointerCapture(pointerId); } catch (_) { /* capture is best effort */ }
    updatePointerPlanDrag(event);
  }

  function updatePointerPlanDrag(event) {
    if (!pointerDragActive || !dragGhost) return;
    event.preventDefault();
    dragGhost.style.left = `${event.clientX - dragPointerOffsetX}px`;
    dragGhost.style.top = `${event.clientY - dragPointerOffsetY}px`;
    const row = document.elementFromPoint(event.clientX, event.clientY)?.closest?.('[data-plan-row-idx]');
    if (!row || row === dragSourceRow) return;
    const rect = row.getBoundingClientRect();
    placePlanDropPlaceholder(row, event.clientY >= rect.top + rect.height / 2 ? 'after' : 'before');
  }

  async function finishPointerPlanDrag(event, commit) {
    const candidate = pointerDragCandidate;
    if (!candidate || event.pointerId !== candidate.pointerId) return;
    const sourceIndex = draggedPlanIdx;
    const targetIndex = dragTargetIdx;
    const position = dragTargetPosition;
    try { candidate.handle.releasePointerCapture(candidate.pointerId); } catch (_) { /* already released */ }
    pointerDragCandidate = null;
    cleanupPlanDrag();
    if (commit && sourceIndex !== null && targetIndex !== null && position) {
      await movePlanItem(sourceIndex, targetIndex, position);
    }
  }

  async function previewSelectedSpeech() {
    if (!selectedPlanItem || selectedPlanItem.kind !== 'speech') return;
    const player = new Audio(`/api/show_plan/item/audio?index=${encodeURIComponent(selectedPlanItem.idx)}&ts=${Date.now()}`);
    try { await player.play(); say('Воспроизвожу реплику'); }
    catch (error) { say('Готовая озвучка ещё недоступна.', 'error'); }
  }

  async function uploadReference() {
    const file = byId('referenceAudioFile')?.files?.[0];
    if (!file) { say('Выберите аудиофайл.', 'error'); return; }
    const form = new FormData();
    form.set('target_type', byId('referenceTargetType')?.value || 'host');
    form.set('host_index', byId('referenceHostIndex')?.value || '0');
    form.set('name', hostsData[Number(byId('referenceHostIndex')?.value || 0)]?.name || 'host');
    const asrBackend = byId('referenceAsrBackend')?.value || 'faster-whisper';
    const asrLevel = byId('referenceAsrLevel')?.value || 'balanced';
    form.set('asr_backend', asrBackend);
    form.set('asr_level', asrLevel);
    form.set('auto_transcribe', String(asrBackend !== 'manual'));
    form.set('manual_text', byId('referenceManualText')?.value || '');
    form.set('audio', file, file.name);
    const statusNode = byId('referenceUploadStatus');
    if (statusNode) statusNode.textContent = 'Загрузка и обработка…';
    try {
      const result = await requestJson('/api/reference_voice/upload', {method: 'POST', body: form});
      if (result.target_type === 'host' && hostsData[result.host_index]) {
        hostsData[result.host_index].omnivoice_mode = 'clone';
        hostsData[result.host_index].omnivoice_ref_audio = result.ref_audio || '';
        hostsData[result.host_index].omnivoice_ref_text = result.ref_text || '';
        renderHosts();
      } else if (result.target_type === 'guest') {
        setFieldValue('guest_voice_mode', 'reference');
        setFieldValue('guest_ref_audio', result.ref_audio || '');
        setFieldValue('guest_ref_text', result.ref_text || '');
      }
      if (result.ref_text) byId('referenceManualText').value = result.ref_text;
      const warning = String(result.asr_warning || '');
      const message = result.asr_ok
        ? (warning ? `Голос назначен; текст сохранён, но нужен контроль на слух: ${warning}` : 'Голос назначен, текст проверен распознаванием')
        : `Голос назначен${result.asr_error ? `; ASR: ${result.asr_error}` : ''}`;
      if (statusNode) statusNode.textContent = message;
      say(message, result.asr_ok ? 'info' : (result.asr_error ? 'error' : 'info'));
    } catch (error) {
      if (statusNode) statusNode.textContent = error.message;
      say(`Не удалось загрузить reference: ${error.message}`, 'error');
    }
  }

  function updateReferenceAsrHint() {
    const backend = byId('referenceAsrBackend')?.value || 'faster-whisper';
    const level = byId('referenceAsrLevel')?.value || 'balanced';
    const hints = {
      'faster-whisper': {
        fast: 'Whisper small: быстрее всего и экономно для памяти.',
        balanced: 'Whisper large-v3-turbo: точнее small, но заметно быстрее полной large-v3.',
        maximum: 'Полная Whisper large-v3: максимальная точность Whisper, больше времени и памяти.',
      },
      gigaam: {
        fast: 'GigaAM-v3 e2e CTC: быстрый русский распознаватель с пунктуацией.',
        balanced: 'GigaAM-v3 e2e RNNT: основной точный режим для русской речи.',
        maximum: 'Двойная GigaAM-проверка: RNNT и CTC сравнивают две расшифровки.',
      },
      manual: {
        fast: 'Распознавание не запускается. Точно впишите произнесённую фразу в поле ниже.',
        balanced: 'Распознавание не запускается. Точно впишите произнесённую фразу в поле ниже.',
        maximum: 'Распознавание не запускается. Точно впишите произнесённую фразу в поле ниже.',
      },
    };
    setText('referenceAsrHint', hints[backend]?.[level] || hints['faster-whisper'].balanced);
    const manual = backend === 'manual';
    if (byId('referenceAsrLevelWrap')) byId('referenceAsrLevelWrap').hidden = manual;
    if (byId('referenceManualText')) byId('referenceManualText').required = manual;
  }

  async function loadModels() {
    const health = byId('modelHealth');
    try {
      const result = await requestJson(`/api/models?ts=${Date.now()}`);
      const models = Array.isArray(result.models) ? result.models : [];
      const reachable = result.reachable !== false;
      lmRuntime = {reachable, models};
      ['lm_model','track_analyzer_model','entertainment_model'].forEach((key) => {
        const field = document.querySelector(`[name="${key}"]`);
        if (!field) return;
        const current = field.value || cfg[key] || 'local-model';
        const select = document.createElement('select');
        [...field.attributes].forEach((attribute) => select.setAttribute(attribute.name, attribute.value));
        [...new Set(['local-model', ...models, current])].forEach((model) => {
          const option = document.createElement('option');
          option.value = model;
          option.textContent = model + (!models.includes(model) && model !== 'local-model' ? ' — не загружена' : '');
          option.selected = model === current;
          select.append(option);
        });
        field.replaceWith(select);
      });
      health.textContent = !reachable
        ? 'LM Studio не запущена или недоступна. Запустите сервер в LM Studio и повторите проверку.'
        : (models.length ? `LM Studio готова. Загружено моделей: ${models.length}.` : 'LM Studio запущена, но ни одна модель не загружена.');
      health.className = `model-health ${reachable && models.length ? 'ok' : 'bad'}`;
      updateRuntimeWarnings();
    } catch (error) {
      lmRuntime = {reachable: false, models: []};
      health.textContent = `LM Studio недоступна: ${error.message}`;
      health.className = 'model-health bad';
      updateRuntimeWarnings();
    }
  }

  function playerRange(player) {
    for (const ranges of [player.seekable, player.buffered]) {
      if (!ranges?.length) continue;
      const index = ranges.length - 1;
      const start = ranges.start(index), end = ranges.end(index);
      if (Number.isFinite(start) && Number.isFinite(end) && end > start) return {start, end};
    }
    return null;
  }

  function refreshPlayer() {
    const player = byId('radioPlayer');
    const button = byId('playBtn');
    if (!player || !button) return;
    const playing = !player.paused && !player.ended && Boolean(player.currentSrc);
    $('.bi', button).className = `bi ${playing ? 'bi-pause-fill' : 'bi-play-fill'}`;
    button.setAttribute('aria-label', playing ? 'Поставить эфир на паузу' : 'Воспроизвести эфир');
    setText('playerState', !status.radio_running && !status.radio_starting ? 'Сейчас' : (playing ? 'В эфире' : (player.currentSrc ? 'Пауза' : 'Локальный плеер')));
    const range = playerRange(player);
    const behind = range ? Math.max(0, range.end - (Number(player.currentTime) || range.end)) : 0;
    setText('playerTime', behind > 8 ? `−${formatDuration(behind)}` : '');
    byId('liveEdgeBtn')?.classList.toggle('is-behind', behind > 8);
    if (byId('playerBackBtn')) byId('playerBackBtn').disabled = !range;
  }

  function playerBack() {
    const player = byId('radioPlayer');
    const range = player && playerRange(player);
    if (!player || !range) return;
    player.currentTime = Math.max(range.start, (Number(player.currentTime) || range.end) - 15);
    refreshPlayer();
  }

  function togglePlayer() {
    const player = byId('radioPlayer');
    if (!player) return;
    if (!player.src) player.src = `/stream.mp3?client=panel&t=${Date.now()}`;
    if (player.paused || player.ended) player.play().catch(() => say('Поток пока недоступен.', 'error')).finally(refreshPlayer);
    else player.pause();
  }

  function goLiveEdge() {
    const player = byId('radioPlayer');
    const range = player && playerRange(player);
    if (!player || !range) return;
    player.currentTime = Math.max(range.start, range.end - 0.1);
    player.play().catch(() => {}).finally(refreshPlayer);
  }

  function initSystemTabs() {
    const tabs = $$('[data-system-tab]');
    const activate = (name) => {
      tabs.forEach((tab) => {
        const active = tab.dataset.systemTab === name;
        tab.classList.toggle('active', active);
        tab.setAttribute('aria-selected', String(active));
      });
      $$('[data-system-panel]').forEach((panel) => {
        const active = panel.dataset.systemPanel === name;
        panel.classList.toggle('active', active);
        panel.hidden = !active;
      });
      if (name === 'lm') loadModels();
    };
    tabs.forEach((tab, index) => {
      tab.addEventListener('click', () => activate(tab.dataset.systemTab));
      tab.addEventListener('keydown', (event) => {
        if (!['ArrowLeft','ArrowRight'].includes(event.key)) return;
        event.preventDefault();
        const next = (index + (event.key === 'ArrowRight' ? 1 : -1) + tabs.length) % tabs.length;
        tabs[next].focus();
        activate(tabs[next].dataset.systemTab);
      });
    });
  }

  function bindEvents() {
    $$('.nav-item').forEach((button) => button.addEventListener('click', () => navigate(button.dataset.viewTarget)));
    $$('[data-nav-target]').forEach((button) => button.addEventListener('click', (event) => { event.preventDefault(); navigate(button.dataset.navTarget); }));
    byId('mobileMenuBtn')?.addEventListener('click', () => setSidebarOpen(!byId('sidebar')?.classList.contains('open')));
    byId('sidebarScrim')?.addEventListener('click', () => setSidebarOpen(false));
    $$('.settings-form').forEach((form) => form.addEventListener('submit', (event) => { event.preventDefault(); saveSettings(form); }));
    document.addEventListener('change', (event) => {
      if (event.target.matches('[name]')) { updateDependencies(); updateResetButtons(); }
      updateHostField(event);
      updateFormDirtyState(event.target.closest('.settings-form'));
      if (event.target.id === 'referenceTargetType') byId('referenceHostWrap').hidden = event.target.value !== 'host';
    });
    document.addEventListener('input', (event) => {
      updateHostField(event);
      if (event.target.matches('[name]')) updateResetButtons();
      updateFormDirtyState(event.target.closest('.settings-form'));
      if (event.target.id === 'selectedScript') captureSelectedScriptDraft();
    });
    document.addEventListener('click', async (event) => {
      if (!event.target.closest('.timeline-more-wrap')) closeTimelineRowMenus();
      if (!event.target.closest('#planMoreMenu, #planMoreBtn')) setPlanMoreOpen(false);
      const reset = event.target.closest('.reset-key');
      if (reset) {
        event.preventDefault();
        try { const result = await postForm('/api/config/reset_key', {key: reset.dataset.key}); cfg[result.key] = result.value; setFieldValue(result.key, result.value); updateResetButtons(); updateAllFormDirtyStates(); say('Стандартное значение восстановлено'); }
        catch (error) { say(`Не удалось сбросить: ${error.message}`, 'error'); }
      }
      const remove = event.target.closest('[data-remove-host]');
      if (remove) removeHost(Number(remove.dataset.removeHost));
      const row = event.target.closest('[data-plan-idx]');
      if (row) {
        captureSelectedScriptDraft();
        selectedPlanIdx = Number(row.dataset.planIdx);
        selectedPlanItem = planItems().find((item) => item.idx === selectedPlanIdx);
        renderTimeline();
      }
      const rowMenuButton = event.target.closest('[data-plan-row-menu]');
      if (rowMenuButton) toggleTimelineRowMenu(rowMenuButton);
      const planItemAction = event.target.closest('[data-plan-item-action][data-plan-item-index]');
      if (planItemAction) await mutatePlanItem(String(planItemAction.dataset.planItemAction || ''), Number(planItemAction.dataset.planItemIndex));
      const newsAction = event.target.closest('[data-news-status][data-news-draft-id]');
      if (newsAction) await setNewsItemStatus(String(newsAction.dataset.newsDraftId || ''), String(newsAction.dataset.newsStatus || ''));
    });
    document.addEventListener('pointerdown', (event) => {
      const handle = event.target.closest('[data-plan-drag-handle]:not(:disabled)');
      const row = handle?.closest('[data-plan-row-idx]');
      if (!handle || !row || planMovePending || event.button !== 0) return;
      event.preventDefault();
      pointerDragCandidate = {
        pointerId: event.pointerId,
        handle,
        row,
        startX: event.clientX,
        startY: event.clientY,
      };
    });
    document.addEventListener('pointermove', (event) => {
      const candidate = pointerDragCandidate;
      if (!candidate || event.pointerId !== candidate.pointerId || planMovePending) return;
      if (!pointerDragActive) {
        if (Math.hypot(event.clientX - candidate.startX, event.clientY - candidate.startY) < 6) return;
        beginPointerPlanDrag(event);
      } else {
        updatePointerPlanDrag(event);
      }
    }, {passive: false});
    document.addEventListener('pointerup', (event) => finishPointerPlanDrag(event, true));
    document.addEventListener('pointercancel', (event) => finishPointerPlanDrag(event, false));
    byId('addHostBtn')?.addEventListener('click', addHost);
    byId('resetHostsBtn')?.addEventListener('click', () => { hostsData = structuredClone(defaults.hosts || []); renderHosts(); say('Стандартный состав восстановлен в форме'); });
    byId('referenceUploadBtn')?.addEventListener('click', uploadReference);
    byId('referenceAsrBackend')?.addEventListener('change', updateReferenceAsrHint);
    byId('referenceAsrLevel')?.addEventListener('change', updateReferenceAsrHint);
    if (byId('referenceAsrBackend') && ['faster-whisper','gigaam'].includes(String(cfg.reference_asr_backend || ''))) byId('referenceAsrBackend').value = cfg.reference_asr_backend;
    if (byId('referenceAsrLevel') && ['fast','balanced','maximum'].includes(String(cfg.reference_asr_level || ''))) byId('referenceAsrLevel').value = cfg.reference_asr_level;
    updateReferenceAsrHint();
    byId('startOmnivoiceBtn')?.addEventListener('click', () => controlOmnivoice('start'));
    byId('stopOmnivoiceBtn')?.addEventListener('click', () => controlOmnivoice('stop'));
    [byId('radioToggleBtn'), byId('airPrimaryBtn')].filter(Boolean).forEach((button) => button.addEventListener('click', toggleRadio));
    [byId('skipAirBtn'), byId('skipPlayerBtn')].filter(Boolean).forEach((button) => button.addEventListener('click', skipCurrent));
    [byId('restartAirBtn'), byId('restartSystemBtn')].filter(Boolean).forEach((button) => button.addEventListener('click', restartRadio));
    [byId('generatePlanTopBtn'), byId('generatePlanEmptyBtn')].filter(Boolean).forEach((button) => button.addEventListener('click', generatePlan));
    byId('cancelPlanBtn')?.addEventListener('click', cancelPlanGeneration);
    byId('prepareNextPlanBtn')?.addEventListener('click', prepareNextPlan);
    [byId('modePlanAirBtn'), byId('modePlanBtn')].filter(Boolean).forEach((button) => button.addEventListener('click', () => setAirMode(true)));
    [byId('modeLiveAirBtn'), byId('modeLiveBtn')].filter(Boolean).forEach((button) => button.addEventListener('click', () => setAirMode(false)));
    byId('clearPlanBtn')?.addEventListener('click', clearPlan);
    byId('planSettingsBtn')?.addEventListener('click', () => setPlanSettingsOpen(true));
    byId('closePlanSettingsBtn')?.addEventListener('click', () => setPlanSettingsOpen(false));
    byId('planMoreBtn')?.addEventListener('click', () => setPlanMoreOpen(byId('planMoreMenu')?.hidden !== false));
    byId('buildProfilesBtn')?.addEventListener('click', buildProfiles);
    byId('rescanMusicBtn')?.addEventListener('click', rescanMusic);
    byId('clearGeneratedBtn')?.addEventListener('click', clearGenerated);
    byId('clearEntertainmentHistoryBtn')?.addEventListener('click', clearEntertainmentHistory);
    byId('refreshModelsBtn')?.addEventListener('click', loadModels);
    byId('newsRefreshBtn')?.addEventListener('click', refreshNewsFeed);
    $$('[data-open-settings-profiles]').forEach((button) => button.addEventListener('click', openSettingsProfiles));
    byId('closeSettingsProfilesBtn')?.addEventListener('click', () => byId('settingsProfilesDialog')?.close());
    byId('settingsProfileSelect')?.addEventListener('change', () => { renderSettingsProfiles(); setSettingsProfileStatus(''); });
    byId('createSettingsProfileBtn')?.addEventListener('click', createSettingsProfile);
    byId('renameSettingsProfileBtn')?.addEventListener('click', renameSettingsProfile);
    byId('deleteSettingsProfileBtn')?.addEventListener('click', deleteSettingsProfile);
    byId('applySettingsProfileBtn')?.addEventListener('click', applySettingsProfile);
    byId('previewSpeechBtn')?.addEventListener('click', previewSelectedSpeech);
    byId('saveSpeechBtn')?.addEventListener('click', () => saveSelectedSpeech(false));
    byId('rerenderSpeechBtn')?.addEventListener('click', rerenderSelectedSpeech);
    byId('duplicatePlanItemBtn')?.addEventListener('click', () => selectedPlanItem && mutatePlanItem('duplicate', Number(selectedPlanItem.idx)));
    byId('insertAfterPlanItemBtn')?.addEventListener('click', () => selectedPlanItem && mutatePlanItem('insert_after', Number(selectedPlanItem.idx)));
    byId('deletePlanItemBtn')?.addEventListener('click', () => selectedPlanItem && mutatePlanItem('delete', Number(selectedPlanItem.idx)));
    byId('keyboardHelpBtn')?.addEventListener('click', () => byId('keyboardDialog')?.showModal());
    byId('playBtn')?.addEventListener('click', togglePlayer);
    byId('playerBackBtn')?.addEventListener('click', playerBack);
    byId('liveEdgeBtn')?.addEventListener('click', goLiveEdge);
    byId('playerCollapseBtn')?.addEventListener('click', () => {
      const dock = byId('playerDock');
      dock?.classList.toggle('is-collapsed');
      const collapsed = dock?.classList.contains('is-collapsed');
      byId('appShell')?.classList.toggle('player-collapsed', Boolean(collapsed));
      byId('playerCollapseBtn')?.setAttribute('aria-expanded', String(!collapsed));
      byId('playerCollapseBtn')?.setAttribute('aria-label', collapsed ? 'Развернуть плеер' : 'Свернуть плеер');
      const icon = $('#playerCollapseBtn .bi');
      if (icon) icon.className = `bi ${collapsed ? 'bi-chevron-up' : 'bi-chevron-down'}`;
    });
    const volume = byId('playerVolume');
    const player = byId('radioPlayer');
    if (volume && player) {
      const saved = Number(localStorage.getItem('aiTruckRadio.playerVolume'));
      player.volume = Number.isFinite(saved) ? clamp(saved, 0, 1) : Number(volume.value);
      volume.value = String(player.volume);
      volume.addEventListener('input', () => { player.volume = Number(volume.value); localStorage.setItem('aiTruckRadio.playerVolume', volume.value); });
      ['play','pause','ended','emptied','error','loadeddata','progress','durationchange','timeupdate'].forEach((name) => player.addEventListener(name, refreshPlayer));
    }
    initSystemTabs();
    window.addEventListener('hashchange', () => navigate(location.hash.slice(1), {replace: true}));
    document.addEventListener('keydown', (event) => {
      const dragHandle = event.target.closest?.('.drag-handle:not(:disabled)');
      if (dragHandle && ['ArrowUp', 'ArrowDown'].includes(event.key)) {
        event.preventDefault();
        if (planMovePending) return;
        const index = Number(dragHandle.closest('[data-plan-row-idx]')?.dataset.planRowIdx || 0);
        const targetIndex = event.key === 'ArrowUp' ? index - 1 : index + 1;
        if (targetIndex >= 1 && targetIndex <= planItems().length) {
          movePlanItem(index, targetIndex, event.key === 'ArrowUp' ? 'before' : 'after');
        }
        return;
      }
      if (event.key === 'Escape') {
        setSidebarOpen(false);
        setPlanSettingsOpen(false);
        setPlanMoreOpen(false);
        closeTimelineRowMenus();
      }
      if (event.key === '/' && !event.target.matches('input, textarea, select')) {
        event.preventDefault();
        $('.nav-item')?.focus();
      }
    });
  }

  injectSettings();
  renderHosts();
  bindEvents();
  updateDependencies();
  updateResetButtons();
  updateAllFormDirtyStates();
  const initialView = location.hash.slice(1) || localStorage.getItem('aiTruckRadio.activeView') || 'plan';
  navigate(initialView, {replace: true});
  setText('planDate', new Intl.DateTimeFormat('ru-RU', {weekday: 'long', day: 'numeric', month: 'long', year: 'numeric'}).format(new Date()));
  updateStatusUi();
  refreshPlayer();
  loadModels();
  setInterval(refreshStatus, 1500);
})();
