from pathlib import Path


def test_static_index_contains_web_studio_shell_and_view_state_machine():
    html = Path(
        "C:/Users/ZhuanZ/Desktop/Projects_China_mobile/mvp-deepagents/src/webtestagent/web/static/index.html"
    ).read_text(encoding="utf-8")

    assert "Web Studio" in html
    assert "Dashboard" in html
    assert "Scripts" in html
    assert "Reports" in html
    assert 'data-view="dashboard"' in html
    assert 'data-view="scripts"' in html
    assert 'data-view="reports"' in html
    assert "deriveAvailability(state)" in html
    assert "deriveScriptsMode(state, scriptResource)" in html
    assert "deriveReportsMode(state, artifactsResource)" in html
    assert "coerceActiveView(activeView, availability)" in html
    assert "ensureScriptResource(state)" in html
    assert "ensureArtifactsResource(state)" in html
    assert "has_script ?? Boolean(state.test_script_path)" in html
    assert "has_report ?? Boolean(state.report_path || state.final_report)" in html


def test_static_index_normalizes_outputs_links_for_artifacts():
    html = Path(
        "C:/Users/ZhuanZ/Desktop/Projects_China_mobile/mvp-deepagents/src/webtestagent/web/static/index.html"
    ).read_text(encoding="utf-8")

    assert "function toPublicArtifactHref(value)" in html
    assert "normalized.indexOf('/outputs/')" in html
    assert "openScriptLink.href = toPublicArtifactHref(state.scriptPath) || '#'" in html
    assert "toPublicArtifactHref(source.manifest_path || state.manifest_path)" in html


def test_static_index_uses_manifest_for_primary_outputs_entry():
    html = Path(
        "C:/Users/ZhuanZ/Desktop/Projects_China_mobile/mvp-deepagents/src/webtestagent/web/static/index.html"
    ).read_text(encoding="utf-8")

    assert "openOutputsLink.href = toPublicArtifactHref(state.manifest_path) || '#'" in html
    assert "openOutputsLink.classList.toggle('is-disabled', !toPublicArtifactHref(state.manifest_path));" in html
    assert "openOutputsLink.href = toPublicArtifactHref(state.outputPath) || '#'" not in html


def test_static_index_contains_compact_dashboard_layout_markers():
    html = Path(
        "C:/Users/ZhuanZ/Desktop/Projects_China_mobile/mvp-deepagents/src/webtestagent/web/static/index.html"
    ).read_text(encoding="utf-8")

    assert 'class="composer-grid"' in html
    assert 'class="field-actions actions"' in html
    assert 'class="dashboard-side-stack"' in html
    assert 'class="panel overview-panel"' in html
    assert 'class="overview-compact"' in html


def test_static_index_contains_dashboard_collapse_controls():
    html = Path(
        "C:/Users/ZhuanZ/Desktop/Projects_China_mobile/mvp-deepagents/src/webtestagent/web/static/index.html"
    ).read_text(encoding="utf-8")

    assert 'id="dashboardComposer" class="panel dashboard-composer"' in html
    assert 'id="dashboardComposerSummary"' in html
    assert 'id="toggleDashboardComposerBtn"' in html
    assert 'aria-controls="dashboardComposerBody"' in html
    assert "dashboardComposer.classList.toggle('is-collapsed', uiState.dashboardComposerCollapsed);" in html
    assert "toggleDashboardComposerBtn.setAttribute('aria-expanded', uiState.dashboardComposerCollapsed ? 'false' : 'true');" in html
    assert "toggleDashboardComposerBtn.textContent = uiState.dashboardComposerCollapsed ? '展开顶部配置' : '收起顶部配置';" in html


def test_static_index_contains_final_vertical_compaction_values():
    html = Path(
        "C:/Users/ZhuanZ/Desktop/Projects_China_mobile/mvp-deepagents/src/webtestagent/web/static/index.html"
    ).read_text(encoding="utf-8")

    assert "padding: 15px;" in html
    assert "gap: 10px;" in html
    assert "textarea {\n        min-height: 96px;" in html
    assert ".log-list {\n        display: grid;\n        gap: 12px;\n        max-height: 640px;\n        min-height: 480px;" in html
    assert ".image-stage {\n        position: relative;\n        min-height: 540px;" in html
    assert ".overview-panel .panel-body {\n        padding: 12px 14px 14px;" in html


def test_static_index_contains_dark_cyber_academic_visual_tokens():
    html = Path(
        "C:/Users/ZhuanZ/Desktop/Projects_China_mobile/mvp-deepagents/src/webtestagent/web/static/index.html"
    ).read_text(encoding="utf-8")

    assert "--bg-main: #041c1c;" in html
    assert "--accent-gold: #d4b872;" in html
    assert "linear-gradient(var(--border-grid) 1px, transparent 1px)" in html
    assert '"Playfair Display", "Noto Serif SC", Georgia' in html
