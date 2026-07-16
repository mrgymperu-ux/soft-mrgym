"""Envio de correo transaccional mediante Resend, desactivado sin API key."""

import json
import os
import urllib.error
import urllib.request


class EmailNoConfigurado(RuntimeError):
    pass


def esta_configurado() -> bool:
    return bool(os.getenv("RESEND_API_KEY") and os.getenv("EMAIL_FROM"))


def enviar(destino: str, asunto: str, html: str) -> None:
    api_key = os.getenv("RESEND_API_KEY")
    remitente = os.getenv("EMAIL_FROM")
    if not api_key or not remitente:
        raise EmailNoConfigurado("El proveedor de correo todavia no esta configurado")

    cuerpo = json.dumps({
        "from": remitente,
        "to": [destino],
        "subject": asunto,
        "html": html,
    }).encode("utf-8")
    solicitud = urllib.request.Request(
        "https://api.resend.com/emails",
        data=cuerpo,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "User-Agent": "Soft-Gym/1.0",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(solicitud, timeout=10) as respuesta:
            if respuesta.status >= 300:
                raise RuntimeError(f"El proveedor de correo respondio {respuesta.status}")
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"No se pudo enviar el correo ({exc.code})") from exc


def plantilla_accion(titulo: str, mensaje: str, boton: str, url: str) -> str:
    return f"""<!doctype html><html><body style='font-family:Arial,sans-serif;background:#f5f6fa;padding:24px'>
    <div style='max-width:560px;margin:auto;background:white;padding:28px;border-radius:14px'>
      <h1 style='font-size:22px;color:#27233a'>{titulo}</h1>
      <p style='color:#4b5563;line-height:1.5'>{mensaje}</p>
      <p><a href='{url}' style='display:inline-block;background:#6657b8;color:white;text-decoration:none;padding:12px 18px;border-radius:8px'>{boton}</a></p>
      <p style='font-size:12px;color:#7b8190'>Si no solicitaste esta accion, ignora este mensaje.</p>
    </div></body></html>"""
