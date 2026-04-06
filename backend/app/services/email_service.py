"""
Servicio de notificaciones por email vía Resend.

Envía el email de «análisis listo» cuando el pipeline completa.
Si la API key no está configurada o el envío falla, se registra el error
pero nunca se interrumpe el flujo principal — las notificaciones son
best-effort.
"""

import logging

import resend

from app.config import settings

_logger = logging.getLogger(__name__)

# La API key se asigna una sola vez al importar el módulo, no en cada llamada.
# Asignarla como global en cada invocación es un anti-patrón en entornos
# multi-worker: puede generar condiciones de carrera si la key cambia.
if settings.resend_api_key:
    resend.api_key = settings.resend_api_key


def send_analysis_ready(
    to_email: str,
    repo_full_name: str,
    biblioteca_url: str,
) -> bool:
    """
    Envía el email de notificación cuando el análisis de un repo ha terminado.

    La función es síncrona porque la SDK de Resend no ofrece API async.
    Las llamadas se hacen desde el orquestador al final del pipeline, donde
    el tiempo de espera adicional es aceptable.

    Args:
        to_email: Dirección de correo del destinatario.
        repo_full_name: Nombre «owner/repo» del repositorio analizado.
        biblioteca_url: URL completa a la página del análisis en la biblioteca.

    Returns:
        True si el email se envió correctamente, False en caso de error.
    """
    if not settings.resend_api_key:
        _logger.warning(
            "RESEND_API_KEY no configurada — email a '%s' para repo '%s' omitido.",
            to_email,
            repo_full_name,
        )
        return False

    try:
        resend.Emails.send({
            "from": settings.resend_from,
            "to": [to_email],
            "subject": f"Tu análisis de {repo_full_name} está listo",
            "html": _build_html(repo_full_name, biblioteca_url),
        })
        _logger.info(
            "Email de análisis listo enviado a '%s' para repo '%s'.",
            to_email,
            repo_full_name,
        )
        return True
    except Exception as exc:
        _logger.error(
            "Error al enviar email a '%s' para repo '%s': %s",
            to_email,
            repo_full_name,
            exc,
        )
        return False


def _build_html(repo_full_name: str, biblioteca_url: str) -> str:
    """
    Construye el cuerpo HTML del email de notificación.

    Args:
        repo_full_name: Nombre «owner/repo» del repositorio.
        biblioteca_url: URL a la página del análisis.

    Returns:
        HTML completo del email.
    """
    return f"""<!DOCTYPE html>
<html lang="es">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
</head>
<body style="font-family: 'Public Sans', Arial, sans-serif; background: #E8F4FF; margin: 0; padding: 40px 20px;">
  <div style="max-width: 520px; margin: 0 auto; background: #fff; border: 2px solid #000;
              box-shadow: 6px 6px 0 #000; padding: 40px;">
    <h1 style="font-family: 'Archivo Black', Arial Black, sans-serif; font-size: 24px;
               margin: 0 0 16px; color: #000;">
      Tu análisis está listo
    </h1>
    <p style="font-size: 16px; color: #333; margin: 0 0 24px;">
      El análisis de <strong>{repo_full_name}</strong> ha terminado.
      Puedes ver el documento completo en la biblioteca:
    </p>
    <a href="{biblioteca_url}"
       style="display: inline-block; background: #FFB5A7; color: #000; font-weight: 700;
              border: 2px solid #000; box-shadow: 3px 3px 0 #000; padding: 12px 24px;
              text-decoration: none; font-size: 15px;">
      Ver análisis &rarr;
    </a>
    <p style="font-size: 13px; color: #888; margin: 32px 0 0;">
      Has recibido este email porque lo solicitaste al iniciar el análisis en
      <a href="https://app.example.com" style="color: #000;">app.example.com</a>.
    </p>
  </div>
</body>
</html>"""
