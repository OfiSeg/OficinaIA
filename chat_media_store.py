"""Persistencia de adjuntos visuales del chat.

Producción: Cloudflare R2 si está configurado. Desarrollo local: carpeta data/chat_assets.
La metadata vive junto al mensaje; este módulo sólo guarda/lee bytes.
"""
from __future__ import annotations
import hashlib
import os
import uuid
from pathlib import Path

import runtime_config
from storage_r2 import subir_bytes, obtener_objeto_stream

BASE_DIR = runtime_config.BASE_DIR
LOCAL_DIR = Path(BASE_DIR) / "data" / "chat_assets"


def _r2_disponible() -> bool:
    claves=("R2_ENDPOINT_URL","R2_ACCESS_KEY_ID","R2_SECRET_ACCESS_KEY","R2_BUCKET_NAME")
    return all(runtime_config.get_text(k) for k in claves)


def _ext(nombre: str) -> str:
    ext=Path(nombre or "").suffix.lower()
    return ext if ext and len(ext)<=10 else ""


def persistir_adjuntos(usuario: str, chat_id: int, adjuntos) -> list[dict]:
    salida=[]
    user_hash=hashlib.sha256(str(usuario or "").encode("utf-8")).hexdigest()[:12]
    for adj in list(adjuntos or []):
        datos=bytes(getattr(adj,"datos_binarios",b"") or b"")
        if not datos:
            continue
        asset_id=uuid.uuid4().hex
        nombre=str(getattr(adj,"nombre","") or "adjunto")
        mime=str(getattr(adj,"mime_type","") or "application/octet-stream")
        extension=_ext(nombre)
        key=f"chat-assets/{user_hash}/{int(chat_id)}/{asset_id}{extension}"
        backend="local"
        try:
            if _r2_disponible():
                subir_bytes(datos,key,mime)
                backend="r2"
            else:
                destino=LOCAL_DIR / user_hash / str(int(chat_id)) / f"{asset_id}{extension}"
                destino.parent.mkdir(parents=True,exist_ok=True)
                destino.write_bytes(datos)
                key=str(destino.relative_to(LOCAL_DIR)).replace(os.sep,"/")
        except Exception:
            # La persistencia visual nunca debe tumbar el análisis del turno.
            continue
        salida.append({
            "id":asset_id,
            "name":nombre,
            "mime":mime,
            "size":len(datos),
            "backend":backend,
            "key":key,
            "url":f"/api/chats/{int(chat_id)}/assets/{asset_id}",
        })
    return salida


def abrir_asset(asset: dict):
    if not isinstance(asset,dict):
        return None
    backend=asset.get("backend")
    key=str(asset.get("key") or "")
    if not key:
        return None
    if backend=="r2":
        obj=obtener_objeto_stream(key)
        return ("r2",obj)
    ruta=(LOCAL_DIR / key).resolve()
    base=LOCAL_DIR.resolve()
    try:
        ruta.relative_to(base)
    except Exception:
        return None
    if not ruta.is_file():
        return None
    return ("local",ruta)
