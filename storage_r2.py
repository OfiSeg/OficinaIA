"""
Capa de almacenamiento para los manuales de OficinaIA.

Cloudflare R2 es compatible con la API S3, por eso se utiliza boto3.
Los PDFs permanecen privados en el bucket y el backend es el único que
conoce las credenciales.
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import BinaryIO

import boto3
from botocore.exceptions import BotoCoreError, ClientError


def _config():
    endpoint = os.getenv("R2_ENDPOINT_URL")
    access_key = os.getenv("R2_ACCESS_KEY_ID")
    secret_key = os.getenv("R2_SECRET_ACCESS_KEY")
    bucket = os.getenv("R2_BUCKET_NAME")

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
    lector de pypdf pueda procesarlo.

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
    try:
        with _cliente().get_object(Bucket=_bucket(), Key=r2_key)["Body"] as body:
            with temporal.open("wb") as salida:
                for bloque in iter(lambda: body.read(1024 * 1024), b""):
                    salida.write(bloque)
        temporal.replace(destino)
        return destino
    except (BotoCoreError, ClientError, OSError) as exc:
        temporal.unlink(missing_ok=True)
        raise RuntimeError("No se pudo descargar el PDF desde Cloudflare R2.") from exc


def obtener_objeto_stream(r2_key: str):
    """Devuelve el streaming body de R2 para servir un PDF sin hacerlo público."""
    try:
        return _cliente().get_object(
            Bucket=_bucket(),
            Key=r2_key,
        )
    except (BotoCoreError, ClientError) as exc:
        raise RuntimeError("No se pudo obtener el PDF desde Cloudflare R2.") from exc


# ==========================================================
# EXCEL INTERNO
# ==========================================================

EXCEL_INTERNO_R2_KEY = "excel/excel_interno.xlsx"


def existe_objeto(r2_key: str) -> bool:
    """Indica si un objeto existe en R2 sin descargarlo."""
    try:
        _cliente().head_object(Bucket=_bucket(), Key=r2_key)
        return True
    except ClientError as exc:
        error_code = str(exc.response.get("Error", {}).get("Code", ""))
        if error_code in {"404", "NoSuchKey", "NotFound"}:
            return False
        raise RuntimeError("No se pudo comprobar el objeto en Cloudflare R2.") from exc
    except BotoCoreError as exc:
        raise RuntimeError("No se pudo comprobar el objeto en Cloudflare R2.") from exc


def subir_excel_interno(archivo: Path, r2_key: str = EXCEL_INTERNO_R2_KEY) -> None:
    """Sube el Excel interno al mismo bucket R2 utilizado por los manuales."""
    try:
        with Path(archivo).open("rb") as fileobj:
            _cliente().upload_fileobj(
                fileobj,
                _bucket(),
                r2_key,
                ExtraArgs={
                    "ContentType": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                },
            )
    except (BotoCoreError, ClientError, OSError) as exc:
        raise RuntimeError("No se pudo guardar el Excel interno en Cloudflare R2.") from exc


def descargar_excel_interno(destino: Path, r2_key: str = EXCEL_INTERNO_R2_KEY) -> bool:
    """
    Descarga el Excel interno desde R2 al filesystem local.
    Devuelve True si se descargó y False si el objeto no existe.
    """
    destino = Path(destino)
    temporal = destino.with_suffix(destino.suffix + ".r2tmp")
    try:
        respuesta = _cliente().get_object(Bucket=_bucket(), Key=r2_key)
        with temporal.open("wb") as salida:
            body = respuesta["Body"]
            for bloque in iter(lambda: body.read(1024 * 1024), b""):
                salida.write(bloque)
        temporal.replace(destino)
        return True
    except ClientError as exc:
        temporal.unlink(missing_ok=True)
        error_code = str(exc.response.get("Error", {}).get("Code", ""))
        if error_code in {"404", "NoSuchKey", "NotFound"}:
            return False
        raise RuntimeError("No se pudo descargar el Excel interno desde Cloudflare R2.") from exc
    except (BotoCoreError, OSError) as exc:
        temporal.unlink(missing_ok=True)
        raise RuntimeError("No se pudo descargar el Excel interno desde Cloudflare R2.") from exc
