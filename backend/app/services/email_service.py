"""
Servicio de notificaciones por email vía Resend.

Envía el email de «análisis listo» cuando el pipeline completa.
Si la API key no está configurada o el envío falla, se registra el error
pero nunca se interrumpe el flujo principal — las notificaciones son
best-effort.
"""

import logging
from html import escape

import resend

from app.config import settings
from app.services.unsubscribe_tokens import build_unsubscribe_token

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
    repo_url: str,
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
            "html": _build_analysis_ready_html(
                to_email=to_email,
                repo_full_name=repo_full_name,
                biblioteca_url=biblioteca_url,
                repo_url=repo_url,
            ),
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


def send_repo_update_ready(
    *,
    to_email: str,
    repo_full_name: str,
    biblioteca_url: str,
    repo_url: str,
    git_sha: str,
) -> bool:
    """Envía un aviso de análisis nuevo cuando cambia el SHA de un repo suscrito."""
    if not settings.resend_api_key:
        _logger.warning(
            "RESEND_API_KEY no configurada — aviso evolutivo a '%s' para repo '%s' omitido.",
            to_email,
            repo_full_name,
        )
        return False

    try:
        resend.Emails.send({
            "from": settings.resend_from,
            "to": [to_email],
            "subject": f"Hay un análisis nuevo de {repo_full_name}",
            "html": _build_repo_update_html(
                to_email=to_email,
                repo_full_name=repo_full_name,
                biblioteca_url=biblioteca_url,
                repo_url=repo_url,
                git_sha=git_sha,
            ),
        })
        _logger.info(
            "Aviso de análisis nuevo enviado a '%s' para repo '%s'.",
            to_email,
            repo_full_name,
        )
        return True
    except Exception as exc:
        _logger.error(
            "Error al enviar aviso evolutivo a '%s' para repo '%s': %s",
            to_email,
            repo_full_name,
            exc,
        )
        return False


def _build_manage_links(to_email: str, repo_url: str) -> tuple[str, str]:
    repo_token = build_unsubscribe_token(
        scope="repo",
        email=to_email,
        repo_url=repo_url,
    )
    global_token = build_unsubscribe_token(
        scope="global",
        email=to_email,
    )
    base = settings.public_app_url.rstrip("/")
    repo_link = f"{base}/notificaciones?action=unsubscribe-repo&token={repo_token}"
    global_link = f"{base}/notificaciones?action=unsubscribe-global&token={global_token}"
    return repo_link, global_link


def _build_analysis_ready_html(
    *,
    to_email: str,
    repo_full_name: str,
    biblioteca_url: str,
    repo_url: str,
) -> str:
    """
    Construye el cuerpo HTML del email de notificación.

    Args:
        repo_full_name: Nombre «owner/repo» del repositorio.
        biblioteca_url: URL a la página del análisis.

    Returns:
        HTML completo del email.
    """
    repo_unsub_link, global_unsub_link = _build_manage_links(to_email, repo_url)
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
    <div style="margin: 24px 0 0; padding-top: 20px; border-top: 1px solid #d9d9d9;">
      <p style="font-size: 13px; color: #333; margin: 0 0 10px;">
        Si activaste avisos futuros, podrás gestionarlos aquí:
      </p>
      <p style="font-size: 13px; margin: 0;">
        <a href="{repo_unsub_link}" style="color: #000; font-weight: 700;">Dejar de recibir avisos de este repo</a>
        &nbsp;·&nbsp;
        <a href="{global_unsub_link}" style="color: #000; font-weight: 700;">Dejar de recibir todos los avisos futuros</a>
      </p>
    </div>
    <p style="font-size: 13px; color: #888; margin: 24px 0 0;">
      Has recibido este email porque lo solicitaste al iniciar el análisis en
      <a href="{escape(settings.public_app_url)}" style="color: #000;">{escape(settings.public_app_url)}</a>.
    </p>
  </div>
</body>
</html>"""


def _build_repo_update_html(
    *,
    to_email: str,
    repo_full_name: str,
    biblioteca_url: str,
    repo_url: str,
    git_sha: str,
) -> str:
    """HTML del email cuando aparece un análisis nuevo de un repo suscrito."""
    repo_unsub_link, global_unsub_link = _build_manage_links(to_email, repo_url)
    short_sha = git_sha[:7] if git_sha else "nuevo SHA"
    return f"""<!DOCTYPE html>
<html lang="es">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
</head>
<body style="font-family: 'Public Sans', Arial, sans-serif; background: #E8F4FF; margin: 0; padding: 40px 20px;">
  <div style="max-width: 520px; margin: 0 auto; background: #fff; border: 2px solid #000;
              box-shadow: 6px 6px 0 #000; padding: 40px;">
    <p style="display:inline-block; margin:0 0 14px; padding:6px 10px; border:2px solid #000; background:#FFF173; font-weight:700; font-size:12px;">
      Nuevo análisis detectado
    </p>
    <h1 style="font-family: 'Archivo Black', Arial Black, sans-serif; font-size: 24px;
               margin: 0 0 16px; color: #000;">
      {repo_full_name} tiene una versión nueva
    </h1>
    <p style="font-size: 16px; color: #333; margin: 0 0 12px;">
      Hemos detectado un análisis nuevo para este repositorio y ya está disponible en la biblioteca.
    </p>
    <p style="font-size: 14px; color: #333; margin: 0 0 24px;">
      SHA actual analizado: <strong>{short_sha}</strong>
    </p>
    <a href="{biblioteca_url}"
       style="display: inline-block; background: #FFB5A7; color: #000; font-weight: 700;
              border: 2px solid #000; box-shadow: 3px 3px 0 #000; padding: 12px 24px;
              text-decoration: none; font-size: 15px;">
      Ver análisis nuevo &rarr;
    </a>
    <div style="margin: 24px 0 0; padding-top: 20px; border-top: 1px solid #d9d9d9;">
      <p style="font-size: 13px; color: #333; margin: 0 0 10px;">
        Gestiona tus avisos futuros:
      </p>
      <p style="font-size: 13px; margin: 0;">
        <a href="{repo_unsub_link}" style="color: #000; font-weight: 700;">No avisarme más de este repo</a>
        &nbsp;·&nbsp;
        <a href="{global_unsub_link}" style="color: #000; font-weight: 700;">No recibir ningún aviso futuro</a>
      </p>
    </div>
    <p style="font-size: 13px; color: #888; margin: 24px 0 0;">
      Este aviso corresponde a suscripciones de seguimiento. Los análisis que pidas manualmente podrán seguir llegándote por email.
    </p>
  </div>
</body>
</html>"""
