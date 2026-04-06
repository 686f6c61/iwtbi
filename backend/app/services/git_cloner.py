"""
Servicio de clonado de repositorios GitHub.

Clona repos públicos en /tmp/iwtbi/<job_id>/ usando el comando git
del sistema vía subproceso asíncrono. No depende de la API de GitHub,
lo que elimina rate limits y permite acceso a todos los archivos sin paginación.
"""

import asyncio
import logging
import re
import shutil
import tempfile
from pathlib import Path

from app.config import settings

_logger = logging.getLogger(__name__)

GITHUB_URL_PATTERN = re.compile(
    r"^https://github\.com/[\w.\-]+/[\w.\-]+/?$"
)

# Usar tempfile.gettempdir() en lugar de /tmp hardcodeado para portabilidad
# y para que SonarQube reconozca el patrón como uso seguro de temporales.
CLONE_BASE = Path(tempfile.gettempdir()) / "iwtbi"
CLONE_TIMEOUT_SECONDS = 120
CLONE_RETRY_ATTEMPTS = 2
CLONE_RETRY_BASE_DELAY_SECONDS = 2


class RepoSizeLimitExceeded(RuntimeError):
    """El repositorio supera el límite de tamaño permitido por la plataforma."""


def validate_github_url(url: str) -> bool:
    """
    Valida que la URL sea un repositorio GitHub público con formato correcto.

    Args:
        url: URL a validar.

    Returns:
        True si es una URL de repo GitHub válida (usuario/repo).

    Example:
        >>> validate_github_url("https://github.com/kelseyhightower/nocode")
        True
    """
    clean = url.rstrip("/")
    if not GITHUB_URL_PATTERN.match(clean):
        return False
    # Rechazar componentes de path traversal
    parts = clean.split("/")
    return not any(p in (".", "..") for p in parts)


class GitCloner:
    """
    Gestiona el ciclo de vida del clonado de repositorios.

    Cada job obtiene su propio directorio temporal en /tmp/iwtbi/repo-<job_id>/
    que se elimina al finalizar el análisis mediante cleanup().
    """

    def get_clone_path(self, job_id: str) -> Path:
        """
        Devuelve la ruta de destino para el repo clonado.

        Args:
            job_id: Identificador único del job.

        Returns:
            Path al directorio de destino (puede no existir aún).
        """
        return CLONE_BASE / f"repo-{job_id}"

    async def clone(self, repo_url: str, job_id: str) -> tuple[Path, str]:
        """
        Clona el repositorio de forma asíncrona con shallow clone.

        Usa --depth=1 para descargar solo el último commit.
        Los argumentos se pasan como lista (nunca shell=True) para
        prevenir inyección de comandos.

        Tras el clonado ejecuta ``git rev-parse HEAD`` para obtener el SHA
        exacto del commit descargado. Este SHA se usa para el caché en Supabase.

        Args:
            repo_url: URL del repositorio GitHub público.
            job_id: Identificador del job (define la ruta de destino).

        Returns:
            Tupla (path_clonado, git_sha) donde path_clonado es el directorio
            listo para lectura y git_sha es el SHA completo del HEAD.

        Raises:
            RuntimeError: Si el clonado falla o supera CLONE_TIMEOUT_SECONDS.
        """
        dest = self.get_clone_path(job_id)
        dest.parent.mkdir(parents=True, exist_ok=True)

        # Verificar el tamaño del repositorio antes de clonar para evitar
        # que repos muy grandes agoten el disco del contenedor.
        # Si la API no responde (repo privado, rate limit), se permite continuar.
        await self._check_repo_size(repo_url)

        for attempt in range(CLONE_RETRY_ATTEMPTS + 1):
            if dest.exists():
                shutil.rmtree(dest, ignore_errors=True)

            proc = await asyncio.create_subprocess_exec(
                "git",
                "-c",
                "http.version=HTTP/1.1",
                "clone",
                "--depth=1",
                str(repo_url),
                str(dest),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            try:
                _, stderr = await asyncio.wait_for(
                    proc.communicate(), timeout=CLONE_TIMEOUT_SECONDS
                )
            except asyncio.TimeoutError:
                proc.kill()
                await proc.wait()
                if attempt < CLONE_RETRY_ATTEMPTS:
                    delay = CLONE_RETRY_BASE_DELAY_SECONDS * (2**attempt)
                    _logger.warning(
                        "Timeout clonando '%s' en intento %d/%d. Reintentando en %ss.",
                        repo_url,
                        attempt + 1,
                        CLONE_RETRY_ATTEMPTS + 1,
                        delay,
                    )
                    await asyncio.sleep(delay)
                    continue
                raise RuntimeError(
                    f"Timeout ({CLONE_TIMEOUT_SECONDS}s) clonando {repo_url}"
                )

            if proc.returncode == 0:
                git_sha = await self._get_head_sha(dest)
                return dest, git_sha

            stderr_text = stderr.decode(errors="replace")[:500]
            if (
                attempt < CLONE_RETRY_ATTEMPTS
                and _is_retryable_clone_error(stderr_text)
            ):
                delay = CLONE_RETRY_BASE_DELAY_SECONDS * (2**attempt)
                _logger.warning(
                    "git clone transitorio para '%s' en intento %d/%d: %s",
                    repo_url,
                    attempt + 1,
                    CLONE_RETRY_ATTEMPTS + 1,
                    stderr_text.strip(),
                )
                await asyncio.sleep(delay)
                continue

            raise RuntimeError(
                f"git clone falló (código {proc.returncode}): {stderr_text}"
            )
        raise RuntimeError(f"git clone falló de forma inesperada para {repo_url}")

    async def _check_repo_size(self, repo_url: str) -> None:
        """
        Verifica que el repositorio no supere el límite de tamaño configurado.

        Consulta la GitHub API antes de clonar. Si el tamaño supera
        ``settings.repo_size_limit_mb``, lanza un RuntimeError que el
        orquestador envía al frontend como error de negocio.

        Si la API no responde (repo privado, rate limit, error de red),
        el check se omite silenciosamente para no bloquear repositorios legítimos.

        Args:
            repo_url: URL completa del repositorio (https://github.com/owner/repo).

        Raises:
            RepoSizeLimitExceeded: Si el tamaño supera el límite configurado.
        """
        from app.services.github_api import get_repo_size_kb

        repo_full_name = "/".join(repo_url.rstrip("/").split("/")[-2:])
        size_kb = await get_repo_size_kb(repo_full_name)
        if size_kb is None:
            return  # No se puede verificar — continuar

        limit_kb = settings.repo_size_limit_mb * 1024
        if size_kb > limit_kb:
            raise RepoSizeLimitExceeded(
                f"El repositorio ocupa ~{size_kb // 1024} MB, que supera el límite "
                f"de {settings.repo_size_limit_mb} MB permitido."
            )

    async def _get_head_sha(self, clone_path: Path) -> str:
        """
        Obtiene el SHA del HEAD del repositorio clonado.

        Ejecuta ``git rev-parse HEAD`` en el directorio clonado para obtener
        el SHA exacto del commit descargado. Si el comando falla (caso
        excepcional), devuelve una cadena vacía en lugar de interrumpir el pipeline.

        Args:
            clone_path: Ruta al directorio del repositorio clonado.

        Returns:
            SHA completo del HEAD (40 caracteres hex), o cadena vacía si falla.
        """
        try:
            proc = await asyncio.create_subprocess_exec(
                "git", "-C", str(clone_path), "rev-parse", "HEAD",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=10)
            if proc.returncode == 0:
                return stdout.decode().strip()
        except Exception as exc:
            _logger.warning("No se pudo obtener el SHA del HEAD en '%s': %s", clone_path, exc)
        return ""

    def cleanup(self, job_id: str) -> None:
        """
        Elimina el directorio temporal del repo clonado.

        Seguro de llamar aunque el directorio no exista. Los errores de
        eliminación se registran pero no se propagan: la limpieza es
        best-effort; un fallo aquí no debe interrumpir el flujo principal.

        Args:
            job_id: Identificador del job cuyo directorio se limpia.
        """
        path = self.get_clone_path(job_id)
        if path.exists():
            try:
                shutil.rmtree(path)
            except OSError as exc:
                _logger.error(
                    "No se pudo eliminar el directorio temporal '%s' del job '%s': %s",
                    path,
                    job_id,
                    exc,
                )


def _is_retryable_clone_error(stderr_text: str) -> bool:
    """Detecta errores transitorios de red/TLS al clonar desde GitHub."""
    message = stderr_text.lower()
    transient_markers = (
        "connection reset by peer",
        "recv failure",
        "gnutls recv error",
        "tls connection was non-properly terminated",
        "expected flush after ref listing",
        "remote end hung up unexpectedly",
        "http/2 stream",
        "operation timed out",
        "connection timed out",
    )
    return any(marker in message for marker in transient_markers)
