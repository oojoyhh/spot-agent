"""Streamlit UI smoke tests for the integrated demo flow."""

from pathlib import Path

from streamlit.testing.v1 import AppTest


APP_PATH = Path(__file__).resolve().parents[1] / "app.py"


def _demo_app(monkeypatch) -> AppTest:
    monkeypatch.setenv("STUDYSPOT_FORCE_STUB", "1")
    return AppTest.from_file(str(APP_PATH), default_timeout=10).run()


def test_initial_screen_renders_without_exception(monkeypatch) -> None:
    app = _demo_app(monkeypatch)

    assert not app.exception
    assert any(title.value == "출점 후보 분석" for title in app.title)
    assert any(box.label == "stub 응답 시나리오" for box in app.selectbox)


def test_success_scenario_renders_ranked_cards(monkeypatch) -> None:
    app = _demo_app(monkeypatch)
    scenario = next(box for box in app.selectbox if box.label == "stub 응답 시나리오")
    scenario.select("success").run()
    next(button for button in app.button if button.label == "분석 요청").click().run()

    assert not app.exception
    rendered = [item.value for item in app.markdown]
    assert '<div class="studyspot-rank">1위 추천 상권</div>' in rendered
    assert '<div class="studyspot-card-title">[stub] 상권 A</div>' in rendered
    assert '<div class="studyspot-rank">2위 추천 상권</div>' in rendered
    assert any("점수는 창업 성공 확률이 아니라" in caption.value for caption in app.caption)
