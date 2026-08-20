# -*- coding: utf-8 -*-
from __future__ import annotations

from copy import deepcopy
from types import SimpleNamespace

from ai_truck_radio_app.config import APP_NAME, APP_VERSION, DEFAULT_CONFIG
from ai_truck_radio_app.panel import render_panel


def _render(*, station_name: str = "Волна FM") -> str:
    cfg = deepcopy(DEFAULT_CONFIG)
    cfg["station_name"] = station_name
    engine = SimpleNamespace(
        _guest_ref_status=lambda: {"audio_exists": False, "audio": "references/guest_ref.wav"}
    )
    snap = {
        "radio_running": False,
        "radio_starting": False,
        "music_count": 65,
        "ffmpeg_ok": True,
        "ffprobe_ok": True,
        "show_plan_preview": [],
    }
    return render_panel(engine, cfg, snap, deepcopy(DEFAULT_CONFIG), APP_NAME, APP_VERSION)


def test_panel_v2_replaces_legacy_shell_and_uses_section_scoped_forms() -> None:
    page = _render()

    assert "Control Center" not in page
    assert 'id="cfgForm"' not in page
    assert page.count('class="player-dock"') == 1
    assert "grid-column: 1 / -1" in page
    assert 'id="musicForm"' in page
    assert 'id="funForm"' in page
    assert 'id="hostsForm"' in page
    assert 'id="voiceForm"' in page
    assert 'id="systemForm"' in page
    assert "Интернет, затем LM" in page
    assert 'name="track_profiles_web_lookup_provider"' not in page


def test_panel_v2_contains_working_plan_inspector_and_readiness_contract() -> None:
    page = _render()

    assert 'id="selectedHost"' in page
    assert 'id="selectedHostLabel"' in page
    assert 'id="selectedScriptLabel"' in page
    assert "function inferHostNames(item)" in page
    assert "function planItemTitle(item)" in page
    assert "item?.hosts" in page
    assert "Ведущие" in page
    assert 'id="selectedScript"' in page
    assert 'id="saveSpeechBtn"' in page
    assert 'id="rerenderSpeechBtn"' in page
    assert 'id="readinessPanel"' in page
    assert "readinessCloseBtn" not in page
    assert "/api/show_plan/item/text" in page
    assert "/api/show_plan/item/audio" in page
    assert 'id="playerCurrent">Радио остановлено' in page


def test_panel_bootstrap_json_cannot_break_out_of_script_tag() -> None:
    page = _render(station_name='</script><script>alert("x")</script>')

    assert '</script><script>alert("x")</script>' not in page
    assert "\\u003c/script\\u003e" in page


def test_plan_editor_preserves_dirty_draft_and_locks_non_future_items() -> None:
    page = _render()

    assert "let selectedScriptDirty = false" in page
    assert "if (!selectedScriptDirty) selectedScriptDraft = selectedPlanItem.text || ''" in page
    assert "resetSelectedScriptState(selectedPlanItem)" in page
    assert "status.show_plan_index" in page
    assert "status.show_plan_next_index" in page
    assert "planItemPhase(selectedPlanItem) === 'future'" in page
    assert "textarea.readOnly = !editable" in page
    assert "byId('saveSpeechBtn').disabled = !editable || speechOperationPending" in page
    assert "Number(item.idx) >= nextIdx" in page


def test_plan_and_player_controls_have_real_state_and_accessibility_contracts() -> None:
    page = _render()

    assert "bi bi-grip-vertical" in page
    assert "timeline-more" in page
    assert "document.addEventListener('pointerdown'" in page
    assert "document.addEventListener('pointermove'" in page
    assert "setPointerCapture(pointerId)" in page
    assert "updatePointerPlanDrag(event)" in page
    assert "action: 'move'" in page
    assert "/api/show_plan/item/action" in page
    assert "/api/show_plan/cancel" in page
    assert 'id="cancelPlanBtn"' in page
    assert "timeline-drop-placeholder" in page
    assert "dragging-collapsed" in page
    assert "let planMovePending = false" in page
    assert "plan-reorder-pending" in page
    assert "aria-busy" in page
    assert "finally {" in page
    assert "Готово к запуску" not in page
    assert "LM Studio не запущена или недоступна" in page
    assert "friendlyReadinessError" in page
    assert "Запустите сервер в LM Studio и повторите проверку" in page
    assert 'id="planSettingsBtn" type="button" aria-expanded="false" aria-controls="planSettingsDrawer"' in page
    assert 'id="planMoreMenu" role="menu" aria-hidden="true"' in page
    assert 'id="playerCollapseBtn" type="button" aria-label="Свернуть плеер"' in page
    assert 'id="playerMenu"' not in page
    assert "setPlanMoreOpen(false)" in page
    assert "setPlanSettingsOpen(false)" in page
    assert "player-collapsed" in page
    assert "--player-height: 64px" in page
    assert "width: min(430px, calc(100% - 24px))" in page
    assert 'id="duplicatePlanItemBtn"' in page
    assert 'id="insertAfterPlanItemBtn"' in page
    assert 'id="deletePlanItemBtn"' in page
    assert "До успешного завершения прежняя озвучка останется доступной" in page
    assert "right: 500px" not in page
    assert 'id="omnivoiceServiceCard"' in page
    assert 'id="startOmnivoiceBtn"' in page
    assert 'id="stopOmnivoiceBtn"' in page
    assert "/api/omnivoice/${action}" in page
    assert "referenceAsrBackend" in page
    assert "referenceAsrLevel" in page
    assert "GigaAM — для русской речи" in page
    assert "Максимальная точность" in page
    assert "Без распознавания — мой текст" in page
    assert "whisperOnlyKeys" in page
    assert "wrapper.hidden = settingsBackend !== 'faster-whisper'" in page
    assert "[name=\"reference_asr_backend\"]')?.addEventListener('change', updateReferenceAsrHint)" in page
    assert "starting ? 'Отменить запуск'" in page
    assert "status.radio_running || status.radio_starting" in page
    assert ".player-controls #playBtn .bi-play-fill { transform: translateX(2px); }" in page
    assert ".inspector-main { flex: 1 1 auto; min-height: 0; overflow-x: hidden; overflow-y: auto;" in page


def test_mobile_settings_and_readiness_remain_responsive() -> None:
    page = _render()

    assert '.setting { position: relative; display: flex; align-items: stretch; flex-direction: column;' in page
    assert '.check.setting-bool { grid-template-columns: minmax(0, 1fr) auto;' in page
    assert '.app-shell.radio-running .readiness-panel { display: none; }' not in page
    assert "status.ffprobe_ok" in page
    assert "FFprobe не найден" in page


def test_settings_resets_switches_and_profiles_have_explicit_ui_contracts() -> None:
    page = _render()

    assert "bi bi-arrow-counterclockwise" in page
    assert "data-tooltip=\\\"По умолчанию\\\"" in page
    assert "button.disabled = !changed" in page
    assert "settingValuesEqual" in page
    assert "form.dataset.dirty = String(dirty)" in page
    assert "updateAllFormDirtyStates()" in page
    assert "border-radius: 999px; background: #d8dee7" in page
    assert ".check-main input:focus-visible ~ .switch-ui" in page
    assert "reference-auto-toggle" in page
    assert ".voice-upload-grid .reference-auto-toggle" in page
    assert 'id="settingsProfilesDialog"' in page
    assert 'id="settingsProfileSelect"' in page
    assert 'id="createSettingsProfileBtn"' in page
    assert 'id="renameSettingsProfileBtn"' in page
    assert 'id="deleteSettingsProfileBtn"' in page
    assert "/api/settings_profiles/apply" in page
    assert "Локальные пути, reference-голоса и секреты" in page


def test_news_section_renders_review_flow_sources_and_responsive_states() -> None:
    page = _render()

    assert 'data-view-target="news"' in page
    assert 'data-view="news"' in page
    assert 'id="newsRefreshBtn"' in page
    assert 'id="newsFeed" aria-live="polite" aria-busy="false"' in page
    assert 'id="newsErrorBanner" role="alert"' in page
    assert "status.news_status" in page
    assert "status.news_pack" in page
    assert "/api/news/refresh" in page
    assert "/api/news/item/status" in page
    assert "status: nextStatus" in page
    assert "meta.key === 'review'" in page
    assert "data-news-status=\"verified\"" in page
    assert "data-news-status=\"rejected\"" in page
    assert 'rel="noopener noreferrer"' in page
    assert "newsStateMarkup('loading'" in page
    assert "newsStateMarkup('error'" in page
    assert "newsStateMarkup('empty'" in page
    assert "status.news_refreshing" in page
    assert "Обновляю ленту…" in page
    assert "if (!loading) setText('newsFeedStatus'" in page
    assert ".news-feed { grid-template-columns: 1fr; }" in page


def test_long_track_profile_refresh_can_be_cancelled_from_panel() -> None:
    page = _render()

    assert "/api/track_profiles/cancel" in page
    assert "status.track_profile_building" in page
    assert "status.track_profile_cancel_requested" in page
    assert "Отменить обновление" in page
