from __future__ import annotations

import os
import sys
import types
from pathlib import Path

# El entorno de validación puede no tener instaladas las dependencias Google.
# En ese caso se crean stubs mínimos sólo para probar clasificación/retries; en
# producción requirements.txt instala las librerías reales.
try:
    import google.auth  # type: ignore
except ModuleNotFoundError:
    google = types.ModuleType("google")
    google_auth = types.ModuleType("google.auth")
    google_auth_ex = types.ModuleType("google.auth.exceptions")
    class GoogleAuthError(Exception):
        pass
    google_auth_ex.GoogleAuthError = GoogleAuthError
    google_oauth2 = types.ModuleType("google.oauth2")
    google_sa = types.ModuleType("google.oauth2.service_account")
    class Credentials:
        @classmethod
        def from_service_account_info(cls, info, scopes=None):
            return cls()
    google_sa.Credentials = Credentials
    gap = types.ModuleType("googleapiclient")
    gap_discovery = types.ModuleType("googleapiclient.discovery")
    gap_discovery.build = lambda *a, **k: object()
    gap_errors = types.ModuleType("googleapiclient.errors")
    class HttpError(Exception):
        pass
    gap_errors.HttpError = HttpError
    sys.modules.update({
        "google": google, "google.auth": google_auth,
        "google.auth.exceptions": google_auth_ex, "google.oauth2": google_oauth2,
        "google.oauth2.service_account": google_sa, "googleapiclient": gap,
        "googleapiclient.discovery": gap_discovery, "googleapiclient.errors": gap_errors,
    })

import google_sheets_service as sheets
import runtime_config
import service_diagnostics
import system_health

ROOT = Path(__file__).resolve().parent


def _with_env(name, value):
    old_present = name in os.environ
    old = os.environ.get(name)
    if value is None:
        os.environ.pop(name, None)
    else:
        os.environ[name] = value
    return old_present, old


def _restore_env(name, state):
    present, value = state
    if present:
        os.environ[name] = value
    else:
        os.environ.pop(name, None)


def test_env_missing_empty_configured():
    name = "OFICINAIA_TEST_ENV"
    state = _with_env(name, None)
    try:
        assert runtime_config.inspect_env(name).state == "missing"
        os.environ[name] = "   "
        assert runtime_config.inspect_env(name).state == "empty"
        os.environ[name] = "valor"
        assert runtime_config.inspect_env(name).state == "configured"
    finally:
        _restore_env(name, state)


def test_sheet_id_codes():
    name = "SHEET_ID_ASEGURADOS"
    state = _with_env(name, None)
    try:
        try:
            sheets._spreadsheet_id("1")
            raise AssertionError("debía fallar missing")
        except sheets.SheetsServiceError as exc:
            assert exc.code == "MISSING_SHEET_ID"
        os.environ[name] = "  "
        try:
            sheets._spreadsheet_id("1")
            raise AssertionError("debía fallar empty")
        except sheets.SheetsServiceError as exc:
            assert exc.code == "EMPTY_SHEET_ID"
    finally:
        _restore_env(name, state)


def test_retry_only_reads():
    class FakeRequest:
        def __init__(self, fails):
            self.fails = fails
            self.calls = 0
        def execute(self):
            self.calls += 1
            if self.calls <= self.fails:
                raise sheets.SheetsServiceError("GOOGLE_API_TEMPORARY", "temporal")
            return {"ok": True}

    r = FakeRequest(2)
    assert sheets._execute(r, operation="read") == {"ok": True}
    assert r.calls == 3

    w = FakeRequest(1)
    try:
        sheets._execute(w, operation="write")
        raise AssertionError("write no debe reintentarse por defecto")
    except sheets.SheetsServiceError as exc:
        assert exc.code == "GOOGLE_API_TEMPORARY"
    assert w.calls == 1


def test_health_cache_recovers():
    original = service_diagnostics.CHECKERS
    state = {"ok": False}
    def fake_checker(*, probe_external):
        status = "ok" if state["ok"] else "warning"
        code = "OK" if state["ok"] else "TEMP"
        return service_diagnostics.ServiceStatus("fake", "Fake", status, code, "x", [], "2026-09-10T15:00:00-03:00")
    try:
        service_diagnostics.CHECKERS = (fake_checker,)
        service_diagnostics.clear_health_cache()
        first = service_diagnostics.run_health_checks(probe_external=True, use_cache=False)
        assert first["services"]["fake"]["status"] == "warning"
        state["ok"] = True
        second = service_diagnostics.run_health_checks(probe_external=True, use_cache=False)
        assert second["services"]["fake"]["status"] == "ok"
    finally:
        service_diagnostics.CHECKERS = original
        service_diagnostics.clear_health_cache()


def test_no_secret_leak():
    raw = "postgresql://user:pass@example/db api_key=SUPERSECRETA spreadsheetId=ABC123"
    safe = service_diagnostics._safe_error_text(RuntimeError(raw))
    assert "pass" not in safe
    assert "SUPERSECRETA" not in safe
    assert "ABC123" not in safe
    detail = system_health._safe_detail("client_secret=SECRETO refresh_token=TOKEN password=CLAVE")
    assert "SECRETO" not in detail
    assert "TOKEN" not in detail
    assert "CLAVE" not in detail


def test_ui_servicios_integrada_en_salud():
    salud = (ROOT / "templates" / "salud.html").read_text(encoding="utf-8")
    base = (ROOT / "templates" / "base.html").read_text(encoding="utf-8")
    js = (ROOT / "static" / "js" / "salud.js").read_text(encoding="utf-8")
    assert "Servicios" in salud
    assert "healthRefreshBtn" in salud
    assert "/api/system/health" in js
    # Servicios no debe convertirse en navegación principal.
    assert 'data-tip="Servicios"' not in base
    assert 'data-tip="Salud"' in base


def test_google_missing_health_without_network():
    states = {}
    for name in ("SHEET_ID_ASEGURADOS", "GOOGLE_SHEETS_CREDENTIALS_JSON"):
        states[name] = _with_env(name, None)
    try:
        result = service_diagnostics.check_google_sheets(probe_external=False)
        assert result.status == "error"
        assert result.code == "MISSING_SHEET_ID"
    finally:
        for name, state in states.items():
            _restore_env(name, state)


def run():
    tests = [
        test_env_missing_empty_configured,
        test_sheet_id_codes,
        test_retry_only_reads,
        test_health_cache_recovers,
        test_no_secret_leak,
        test_ui_servicios_integrada_en_salud,
        test_google_missing_health_without_network,
    ]
    for test in tests:
        test()
        print("OK", test.__name__)
    print("OK TOTAL:", len(tests), "grupos")


if __name__ == "__main__":
    run()
