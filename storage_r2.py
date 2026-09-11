"""
Capa de almacenamiento para los manuales de OficinaIA.

Cloudflare R2 es compatible con la API S3, por eso se utiliza boto3.
Los PDFs permanecen privados en el bucket y el backend es el único que
conoce las credenciales.
"""
from __future__ import annotations

import tempfile

import runtime_config
from resilience import call_read_with_resilience, is_transient_error
from pathlib import Path
from typing import BinaryIO

import boto3
from botocore.exceptions import BotoCoreError, ClientError


def _config():
    endpoint = runtime_config.get_text("R2_ENDPOINT_URL")
    access_key = runtime_config.get_text("R2_ACCESS_KEY_ID")
    secret_key = runtime_config.get_text("R2_SECRET_ACCESS_KEY")
    bucket = runtime_config.get_text("R2_BUCKET_NAME")

    faltantes = [
        nombre
        for nombre, valor in (
            ("R2_ENDPOINT_URL", endpoint),
            ("R2_ACCESS_KEY_ID", access_key),
            ("R2_SECRET_ACCESS_KEY", secret_key),
            ("R2_BUCKET_NAME", bucket),
        )
        if not valor
    ]
    if faltantes:
        raise RuntimeError(
            "Faltan variables de entorno de Cloudflare R2: "
            + ", ".join(faltantes)
        )

    return endpoint, access_key, secret_key, bucket


def _cliente():
    endpoint, access_key, secret_key, _ = _config()
    return boto3.client(
        "s3",
        endpoint_url=endpoint,
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
    )


def _bucket():
    return _config()[3]


def subir_pdf(fileobj: BinaryIO, r2_key: str, tamaño: int) -> None:
    """Sube un PDF privado a R2."""
    try:
        _cliente().upload_fileobj(
            fileobj,
            _bucket(),
            r2_key,
            ExtraArgs={
                "ContentType": "application/pdf",
            },
        )
    except (BotoCoreError, ClientError) as exc:
        raise RuntimeError("No se pudo guardar el PDF en Cloudflare R2.") from exc


def eliminar_pdf(r2_key: str) -> None:
    """Elimina un objeto de R2. Si ya no existe, se considera éxito."""
    try:
        _cliente().delete_object(Bucket=_bucket(), Key=r2_key)
    except (BotoCoreError, ClientError) as exc:
        raise RuntimeError("No se pudo eliminar el PDF de Cloudflare R2.") from exc


def descargar_pdf_temporal(r2_key: str) -> Path:
    """
    Descarga un PDF de R2 a la carpeta temporal del sistema para que el
    lector de PDF pueda procesarlo.

    No se utiliza una carpeta del proyecto: es caché temporal del servidor.
    Si el mismo r2_key ya está descargado, se reutiliza.
    """
    cache_dir = Path(tempfile.gettempdir()) / "oficinaia_r2_pdf_cache"
    cache_dir.mkdir(parents=True, exist_ok=True)

    # El r2_key es controlado por la aplicación. Se conserva la estructura
    # mediante una codificación segura para evitar rutas arbitrarias.
    import hashlib
    digest = hashlib.sha256(r2_key.encode("utf-8")).hexdigest()
    destino = cache_dir / f"{digest}.pdf"

    if destino.is_file() and destino.stat().st_size > 0:
        return destino

    temporal = cache_dir / f".{digest}.tmp"

    def _descargar_una_vez():
        temporal.unlink(missing_ok=True)
        with _cliente().get_object(Bucket=_bucket(), Key=r2_key)["Body"] as body:
            with temporal.open("wb") as salida:
                for bloque in iter(lambda: body.read(1024 * 1024), b""):
                    salida.write(bloque)
        if not temporal.is_file() or temporal.stat().st_size <= 0:
            raise RuntimeError("EMPTY RESPONSE al descargar objeto desde R2")
        temporal.replace(destino)
        return destino

    def _retry_r2(exc: Exception) -> bool:
        if isinstance(exc, ClientError):
            try:
                status = int(exc.response.get("ResponseMetadata", {}).get("HTTPStatusCode", 0))
            except Exception:
                status = 0
            return status in {408, 425, 429, 500, 502, 503, 504}
        return isinstance(exc, (BotoCoreError, OSError)) or is_transient_error(exc)

    try:
        return call_read_with_resilience(
            _descargar_una_vez, operation="r2_download", provider="cloudflare_r2",
            attempts=3, delays=(0.0, 0.5, 1.2), retry_if=_retry_r2,
        )
    except (BotoCoreError, ClientError, OSError, RuntimeError) as exc:
        temporal.unlink(missing_ok=True)
        raise RuntimeError("No se pudo descargar el PDF desde Cloudflare R2.") from exc


def obtener_objeto_stream(r2_key: str):
    """Devuelve el streaming body de R2; GET es idempotente y reintentable."""
    try:
        return call_read_with_resilience(
            lambda: _cliente().get_object(Bucket=_bucket(), Key=r2_key),
            operation="r2_get_object", provider="cloudflare_r2", attempts=3,
        )
    except (BotoCoreError, ClientError, RuntimeError) as exc:
        raise RuntimeError("No se pudo obtener el PDF desde Cloudflare R2.") from exc



# Respaldo genérico: Sheets es la fuente viva; R2 sólo recibe snapshots.

def subir_bytes(datos: bytes, r2_key: str, content_type: str = "application/octet-stream") -> None:
    """Sube bytes arbitrarios; usado por respaldos programados."""
    try:
        _cliente().put_object(Bucket=_bucket(), Key=r2_key, Body=bytes(datos), ContentType=content_type)
    except (BotoCoreError, ClientError) as exc:
        raise RuntimeError("No se pudo guardar el respaldo en Cloudflare R2.") from exc


def listar_objetos(prefijo: str) -> list[dict]:
    salida = []
    token = None
    try:
        while True:
            kwargs = {"Bucket": _bucket(), "Prefix": str(prefijo or "")}
            if token:
                kwargs["ContinuationToken"] = token
            respuesta = _cliente().list_objects_v2(**kwargs)
            salida.extend(respuesta.get("Contents") or [])
            if not respuesta.get("IsTruncated"):
                break
            token = respuesta.get("NextContinuationToken")
        return salida
    except (BotoCoreError, ClientError) as exc:
        raise RuntimeError("No se pudieron listar los respaldos de Cloudflare R2.") from exc


def eliminar_objeto(r2_key: str) -> None:
    try:
        _cliente().delete_object(Bucket=_bucket(), Key=r2_key)
    except (BotoCoreError, ClientError) as exc:
        raise RuntimeError("No se pudo eliminar un respaldo antiguo de Cloudflare R2.") from exc


def comprobar_conexion() -> None:
    """Comprobación de sólo lectura para Salud → Servicios."""
    try:
        _cliente().list_objects_v2(Bucket=_bucket(), MaxKeys=1)
    except (BotoCoreError, ClientError) as exc:
        raise RuntimeError("No se pudo comprobar el acceso a Cloudflare R2.") from exc
