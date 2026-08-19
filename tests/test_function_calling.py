import sys
import types as pytypes
import importlib
import unittest
from unittest.mock import patch


class FakeSchema:
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)


class FakeFunctionDeclaration:
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)


class FakeTool:
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)


class FakePart:
    @staticmethod
    def from_function_response(name, response):
        return {"function_response": {"name": name, "response": response}}


class FakeGenerateContentConfig:
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)


fake_types = pytypes.ModuleType("google.genai.types")
fake_types.Schema = FakeSchema
fake_types.FunctionDeclaration = FakeFunctionDeclaration
fake_types.Tool = FakeTool
fake_types.Part = FakePart
fake_types.GenerateContentConfig = FakeGenerateContentConfig
fake_types.GoogleSearch = lambda: object()

fake_genai = pytypes.ModuleType("google.genai")
fake_genai.types = fake_types
fake_genai.Client = object

fake_google = pytypes.ModuleType("google")
fake_google.genai = fake_genai

sys.modules.setdefault("google", fake_google)
sys.modules.setdefault("google.genai", fake_genai)
sys.modules.setdefault("google.genai.types", fake_types)

import servicios_ia as ia


class TestHerramientasFunctionCalling(unittest.TestCase):
    def setUp(self):
        self.datos = [
            {"CLIENTE": "Juan Perez", "CIA": "ATM", "FORMA DE PAGO": "CBU", "PATENTE": "AA123BB", "VEHICULO": "Auto"},
            {"CLIENTE": "Juan Perez", "CIA": "ATM", "FORMA DE PAGO": "CBU", "PATENTE": "AB456CC", "VEHICULO": "Camion"},
            {"CLIENTE": "Maria Lopez", "CIA": "AGS", "FORMA DE PAGO": "Cuponera", "PATENTE": "AC789DD", "VEHICULO": "Moto"},
            {"CLIENTE": "Maria Lopez", "CIA": "AGS", "FORMA DE PAGO": "Cuponera", "PATENTE": "AC789DD", "VEHICULO": "Moto"},
        ]
    def patch_dataset(self):
        return (patch.object(ia, "_cargar_excel_interno", return_value=self.datos),)

    def test_consultar_excel_devuelve_filas_relevantes(self):
        with self.patch_dataset()[0]:
            resultado = ia.consultar_excel("Juan Perez")
        self.assertEqual(resultado["fuente"], "Excel interno")
        self.assertEqual(resultado["cantidad"], 2)
        self.assertTrue(all(r["CLIENTE"] == "Juan Perez" for r in resultado["registros"]))

    def test_contar_registros_deduplica_personas_sin_recortar(self):
        with self.patch_dataset()[0]:
            resultado = ia.contar_registros(compania="AGS")
        self.assertEqual(resultado["total_filas"], 2)
        self.assertEqual(resultado["campo_identidad"], "CLIENTE")
        self.assertEqual(resultado["total_unicos"], 1)

    def test_contar_registros_campo_valor(self):
        with self.patch_dataset()[0]:
            resultado = ia.contar_registros(campo="FORMA DE PAGO", valor="CBU")
        self.assertEqual(resultado["total_filas"], 2)
        self.assertEqual(resultado["total_unicos"], 1)

    def test_buscar_vehiculos_por_filtros(self):
        with self.patch_dataset()[0]:
            resultado = ia.buscar_vehiculos(compania="ATM", cliente="Juan Perez")
        self.assertEqual(resultado["cantidad"], 2)
        self.assertEqual({r["PATENTE"] for r in resultado["vehiculos"]}, {"AA123BB", "AB456CC"})

    def test_buscar_vehiculos_por_tipo(self):
        with self.patch_dataset()[0]:
            resultado = ia.buscar_vehiculos(tipo="Moto")
        self.assertEqual(resultado["cantidad"], 1)
        self.assertEqual(resultado["vehiculos"][0]["PATENTE"], "AC789DD")

    def test_buscar_en_manuales_reutiliza_funcion_existente(self):
        fake_app = pytypes.ModuleType("app")
        fake_app.buscar_en_documentos = lambda consulta: [{"texto": "Cobertura de remolque", "archivo": "manual.pdf", "pagina": 4}]
        with patch.dict(sys.modules, {"app": fake_app}):
            resultado = ia.buscar_en_manuales("remolque")
        self.assertEqual(resultado["cantidad"], 1)
        self.assertEqual(resultado["fragmentos"][0]["pagina"], 4)

    def test_deduplicacion_y_campo_identidad_se_conservan(self):
        self.assertEqual(ia._campo_identidad_principal(self.datos), "CLIENTE")
        unicos = ia._deduplicar_personas(self.datos)
        self.assertEqual(len(unicos), 2)
        self.assertEqual({r["CLIENTE"] for r in unicos}, {"Juan Perez", "Maria Lopez"})

    def test_flujo_gemini_mock_tool_call(self):
        class FakeCall:
            name = "contar_registros"
            args = {"compania": "ATM"}

        class FakeContent:
            parts = [pytypes.SimpleNamespace(function_call=FakeCall())]

        class FirstResponse:
            candidates = [pytypes.SimpleNamespace(content=FakeContent())]
            function_calls = [FakeCall()]
            text = None

        class FinalResponse:
            candidates = []
            function_calls = []
            text = "ATM tiene 1 asegurado único."

        class FakeModels:
            def __init__(self):
                self.calls = 0

            def generate_content(self, **kwargs):
                self.calls += 1
                return FirstResponse() if self.calls == 1 else FinalResponse()

        class FakeClient:
            def __init__(self):
                self.models = FakeModels()

        with self.patch_dataset()[0], patch.object(ia, "obtener_cliente_gemini", return_value=FakeClient()):
            resultado = ia.consultar_gemini("¿Cuántos asegurados tengo en ATM?")

        self.assertEqual(resultado, "ATM tiene 1 asegurado único.")


if __name__ == "__main__":
    unittest.main(verbosity=2)
