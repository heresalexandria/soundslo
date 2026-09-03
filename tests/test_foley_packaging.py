import json
from pathlib import Path

from soundslo.config import FOLEY_RUNTIME_REVISION

ROOT = Path(__file__).parents[1]


def test_desktop_packages_the_pinned_foley_runtime() -> None:
    package = json.loads((ROOT / "app" / "package.json").read_text())
    resources = package["build"]["extraResources"]
    assert {
        "from": "build-resources/foley-runtime",
        "to": "foley-runtime",
    } in resources

    main = (ROOT / "app" / "main.js").read_text()
    assert FOLEY_RUNTIME_REVISION in main
    assert "SOUNDSLO_FOLEY_ROOT: FOLEY_DIR" in main
    assert "['.venv', 'ckpts']" in main

    build = (ROOT / "scripts" / "package" / "build.py").read_text()
    assert "requirements-foley.lock" in build


def test_foley_restricted_model_terms_ship_with_the_app() -> None:
    apple = ROOT / "licenses" / "APPLE_ML_RESEARCH_MODEL_LICENSE.md"
    third_party = ROOT / "licenses" / "FOLEY_OMNI_THIRD_PARTY.md"
    notice = (ROOT / "NOTICE").read_text()

    assert "exclusively for Research Purposes" in apple.read_text()
    assert "CC BY-NC 4.0" in third_party.read_text()
    assert "commercial-release blocker" in notice
