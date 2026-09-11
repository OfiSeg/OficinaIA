from __future__ import annotations

import json
import os
import sys
import types as pytypes

# Permite validar la capa aun en entornos sin google-genai instalado.
try:
    import google.genai  # type: ignore
except Exception:
    google_mod = sys.modules.get("google") or pytypes.ModuleType("google")
    genai_mod = pytypes.ModuleType("google.genai")
    types_mod = pytypes.ModuleType("google.genai.types")
    class HttpOptions:
        def __init__(self, **kwargs): self.kwargs = kwargs
    types_mod.HttpOptions = HttpOptions
    genai_mod.types = types_mod
    genai_mod.Client = object
    google_mod.genai = genai_mod
    sys.modules["google"] = google_mod
    sys.modules["google.genai"] = genai_mod
    sys.modules["google.genai.types"] = types_mod

import ai_gateway
from resilience import RecoverablePayloadError, call_read_with_resilience, parse_json_object


class FakeError(RuntimeError):
    def __init__(self, message, status_code=None):
        super().__init__(message)
        self.status_code = status_code


class Part:
    def __init__(self, text="x"): self.text = text
class Content:
    def __init__(self): self.parts = [Part()]
class Candidate:
    def __init__(self, finish_reason="STOP"):
        self.content = Content(); self.finish_reason = finish_reason
class Response:
    def __init__(self, text="ok", finish_reason="STOP", parts=True):
        self.text = text
        self.candidates = [Candidate(finish_reason)] if parts else []


class FakeModels:
    def __init__(self, sequence):
        self.sequence = list(sequence); self.calls = []
    def generate_content(self, **kwargs):
        self.calls.append(kwargs)
        item = self.sequence.pop(0)
        if isinstance(item, Exception): raise item
        return item
class FakeClient:
    def __init__(self, sequence): self.models = FakeModels(sequence)


def reset():
    ai_gateway.begin_request(60)


def test_ai_transient_retry_same_input():
    reset(); contents = ["mensaje", object()]
    c = FakeClient([FakeError("503 unavailable", 503), Response("bien")])
    r, _ = ai_gateway.generate_with_fallback(contents=contents, config={}, client=c, models=("m1","m2"), log_prefix="TEST")
    assert r.text == "bien" and len(c.models.calls) == 2
    assert c.models.calls[0]["contents"] is contents and c.models.calls[1]["contents"] is contents


def test_ai_three_fail_one_final_error():
    reset(); c = FakeClient([FakeError("503",503), FakeError("502",502), FakeError("timeout")])
    try:
        ai_gateway.generate_with_fallback(contents="x", config={}, client=c, models=("m1","m2"), log_prefix="TEST")
    except Exception:
        pass
    else: raise AssertionError("debió fallar")
    assert len(c.models.calls) == 3


def test_ai_permanent_fail_fast():
    reset(); c = FakeClient([FakeError("invalid api key",401), Response("no")])
    try:
        ai_gateway.generate_with_fallback(contents="x", config={}, client=c, models=("m1","m2"), log_prefix="TEST")
    except Exception: pass
    else: raise AssertionError("debió fallar")
    assert len(c.models.calls) == 1


def test_empty_response_retries():
    reset(); c = FakeClient([Response("", parts=False), Response("ok")])
    r,_=ai_gateway.generate_with_fallback(contents="x", config={}, client=c, models=("m1","m2"), log_prefix="TEST")
    assert r.text == "ok" and len(c.models.calls) == 2


def test_truncated_response_retries():
    reset(); c = FakeClient([Response("parcial", finish_reason="MAX_TOKENS"), Response("completo")])
    r,_=ai_gateway.generate_with_fallback(contents="x", config={}, client=c, models=("m1","m2"), log_prefix="TEST")
    assert r.text == "completo" and len(c.models.calls) == 2


def test_json_minor_repair_without_inventing():
    d = parse_json_object("texto```json\n{'dni': '40123456', 'cuil': '',}\n```")
    assert d == {"dni":"40123456", "cuil":""}


def test_invalid_json_is_retryable_in_validator():
    reset(); c = FakeClient([Response("nada"), Response('{"ok": true}')])
    def validator(resp):
        parse_json_object(resp.text)
    r,_=ai_gateway.generate_with_fallback(contents="x", config={}, client=c, models=("m1","m2"), log_prefix="TEST", response_validator=validator)
    assert json.loads(r.text)["ok"] is True and len(c.models.calls) == 2


def test_generic_read_retries_and_recovers():
    calls={"n":0}
    def fn():
        calls["n"]+=1
        if calls["n"] < 3: raise FakeError("503",503)
        return 7
    assert call_read_with_resilience(fn, operation="read", provider="test", delays=(0,0,0)) == 7
    assert calls["n"] == 3


def test_generic_permanent_not_retried():
    calls={"n":0}
    def fn(): calls["n"]+=1; raise FakeError("permission denied",403)
    try: call_read_with_resilience(fn, operation="read", provider="test", delays=(0,0,0))
    except Exception: pass
    assert calls["n"] == 1


def test_write_not_wrapped_globally():
    # Garantía de arquitectura: la capa genérica sólo expone call_read... y no una
    # función de write/action retry. Las escrituras quedan en sus módulos.
    import resilience
    assert not hasattr(resilience, "call_write_with_resilience")
    assert not hasattr(resilience, "retry_action")


def test_mail_not_integrated_into_global_retry():
    from pathlib import Path
    text=Path(__file__).with_name("mail_service.py").read_text(encoding="utf-8")
    assert "call_read_with_resilience" not in text
    assert "generate_with_fallback" not in text


def test_structured_modules_use_gateway_validator():
    from pathlib import Path
    base=Path(__file__).parent
    for name in ("alta_ops.py","cedula_ops.py","personal_document_ops.py","document_classifier.py","estudio_ops.py"):
        text=(base/name).read_text(encoding="utf-8")
        assert "response_validator=" in text, name


def main():
    tests=[v for k,v in globals().items() if k.startswith("test_") and callable(v)]
    for t in tests:
        t(); print("OK", t.__name__)
    print(f"OK TOTAL: {len(tests)} grupos")

if __name__ == "__main__": main()
