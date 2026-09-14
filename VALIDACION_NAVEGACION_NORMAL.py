from pathlib import Path


ROOT = Path(__file__).resolve().parent


def read(relative_path):
    return (ROOT / relative_path).read_text(encoding="utf-8")


app = read("app.py")
javascript = read("static/js/app.js")
base = read("templates/base.html")
documentos = read("templates/documentos.html")
actions = read("templates/_global_actions.html")

# El servidor nunca debe devolver fragmentos aunque llegue un header legado.
assert '"base_template": "base.html"' in app
assert "X-Partial-Navigation" not in app

# Los enlaces internos vuelven a seguir el ciclo normal del navegador: una sola
# petición documental y una inicialización completa por página.
for forbidden in (
    "history.pushState",
    "OIA_partialNavigate",
    "X-Partial-Navigation",
    "addEventListener('popstate'",
    "applyPartial(",
):
    assert forbidden not in javascript, forbidden

# Chat IA lleva sus acciones dentro de la barra Conversaciones. El shell sólo
# las agrega en páginas internas, de modo que siempre existe un único botón.
assert "{% if request.endpoint != 'documentos' %}" in base
assert base.count("render_global_actions('global-actions-inline')") == 1
assert documentos.count("render_global_actions('global-actions-inline')") == 1
assert actions.count('id="themeToggle"') == 1

print("OK - navegación normal sin doble request y un único control de tema por página")
