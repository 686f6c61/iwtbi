"""
Servicio para consultar la GitHub REST API pública.

Permite obtener el SHA del HEAD de un repositorio sin autenticación
y sin clonarlo. Se usa para detectar si el análisis cacheado sigue
vigente comparando el SHA almacenado con el actual.

También expone get_repo_size_kb() para verificar el tamaño del repositorio
antes de clonarlo, evitando que repos de cientos de MB agoten el disco.
"""

import logging

import httpx

_logger = logging.getLogger(__name__)

# Accept header que hace que GitHub devuelva solo el SHA como texto plano,
# evitando parsear el JSON completo del commit.
_GITHUB_SHA_ACCEPT = "application/vnd.github.sha"


async def get_repo_size_kb(repo_full_name: str) -> int | None:
    """
    Devuelve el tamaño del repositorio en KB según la GitHub REST API.

    El campo ``size`` del endpoint GET /repos/{owner}/{repo} es una
    estimación en KB del tamaño del árbol de trabajo (sin objetos git).
    Es suficientemente preciso para rechazar repos excesivamente grandes
    antes de iniciar el clonado.

    Args:
        repo_full_name: Nombre del repo en formato «owner/repo».

    Returns:
        Tamaño en KB, o None si la petición falla (repo privado, rate limit, etc.).
        Devolver None implica que el tamaño no puede verificarse: el llamador
        decide si continuar o rechazar.
    """
    url = f"https://api.github.com/repos/{repo_full_name}"
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(url, headers={"Accept": "application/vnd.github+json"})
            response.raise_for_status()
            return response.json().get("size")
    except Exception as exc:
        _logger.warning(
            "No se pudo obtener el tamaño de '%s' desde GitHub API: %s",
            repo_full_name,
            exc,
        )
        return None


async def get_repo_topics(repo_full_name: str) -> list[str]:
    """
    Devuelve los topics (etiquetas) del repositorio desde la GitHub REST API.

    Los topics son las etiquetas que el autor del repo define en GitHub
    (ej. «python», «fastapi», «docker»). Se usan para mostrar chips
    de tecnología en las cards de la biblioteca sin necesidad de analizar
    el código fuente.

    Args:
        repo_full_name: Nombre del repo en formato «owner/repo».

    Returns:
        Lista de topics en minúsculas, o lista vacía si la petición falla
        (repo privado, rate limit, error de red). La lista vacía evita
        bloquear el pipeline cuando los topics no están disponibles.
    """
    url = f"https://api.github.com/repos/{repo_full_name}/topics"
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(
                url,
                headers={
                    "Accept": "application/vnd.github+json",
                    "X-GitHub-Api-Version": "2022-11-28",
                },
            )
            response.raise_for_status()
            return response.json().get("names", [])
    except Exception as exc:
        _logger.warning(
            "No se pudo obtener los topics de '%s' desde GitHub API: %s",
            repo_full_name,
            exc,
        )
        return []


async def get_head_sha(repo_full_name: str) -> str | None:
    """
    Obtiene el SHA del HEAD del repositorio mediante la GitHub REST API.

    No requiere autenticación para repositorios públicos. El límite de
    rate sin autenticación es 60 peticiones/hora por IP.

    Args:
        repo_full_name: Nombre del repo en formato «owner/repo».

    Returns:
        SHA completo del HEAD (40 caracteres hex), o None si la petición
        falla. Devolver None en lugar de lanzar garantiza que el pipeline
        no se interrumpe por un fallo del check de caché.
    """
    url = f"https://api.github.com/repos/{repo_full_name}/commits/HEAD"
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(
                url,
                headers={"Accept": _GITHUB_SHA_ACCEPT},
            )
            response.raise_for_status()
            return response.text.strip()
    except Exception as exc:
        _logger.warning(
            "No se pudo obtener el SHA de '%s' desde GitHub API: %s",
            repo_full_name,
            exc,
        )
        return None
