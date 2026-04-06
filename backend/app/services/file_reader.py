"""
Lector de archivos de repositorio para construir el contexto de análisis.

Recorre el árbol de directorios del repo clonado, aplica filtros
deterministas (sin LLM) y construye el RepoContext que todos los
agentes reciben como entrada.

El proceso se divide en dos fases:

1. **Descubrimiento (árbol completo):** se recorre todo el repo para
   generar el árbol ASCII completo y recopilar metadatos de archivos.
   El árbol completo da a los agentes visión global de la estructura
   aunque no todos los archivos tengan contenido incluido.

2. **Selección (presupuesto de caracteres):** los archivos candidatos
   se ordenan por puntuación de prioridad (README > configs > código >
   tests) y se incluyen en ese orden hasta agotar ``max_context_chars``.
   Así, con repos grandes, los archivos más informativos entran primero
   y nunca se supera el límite de contexto del modelo.

Seguridad:
- Los symlinks se ignoran para prevenir path traversal.
- Se verifica que cada ruta resuelva dentro del directorio del repo.
- Los binarios se detectan por bytes nulos y se excluyen.
"""

import logging
from dataclasses import dataclass
from pathlib import Path

from app.models.repo_context import RepoContext

_logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Filtros de inclusión/exclusión
# ---------------------------------------------------------------------------

EXCLUDED_DIRS = frozenset({
    "node_modules", ".git", "vendor", "dist", "build",
    "__pycache__", ".next", ".nuxt", "coverage", ".cache",
    "venv", ".venv", "env", ".env", "target", ".turbo",
    ".vercel", ".netlify", "out", "public/build",
})

TEXT_EXTENSIONS = frozenset({
    ".py", ".js", ".ts", ".jsx", ".tsx", ".mjs", ".cjs",
    ".java", ".go", ".rs", ".rb", ".php", ".cs", ".cpp", ".c", ".h",
    ".html", ".css", ".scss", ".sass", ".less",
    ".json", ".yaml", ".yml", ".toml", ".ini", ".cfg",
    ".md", ".mdx", ".txt", ".rst",
    ".sql", ".graphql", ".proto",
    ".sh", ".bash", ".zsh", ".fish",
    ".astro", ".svelte", ".vue",
})

TEXT_FILENAMES = frozenset({
    "Dockerfile", ".dockerignore", ".gitignore",
    "Makefile", "Procfile", ".env.example", ".env.sample",
    "Justfile", "Taskfile",
})

# ---------------------------------------------------------------------------
# Puntuaciones de prioridad para la selección de archivos.
#
# Los archivos con mayor puntuación se incluyen primero cuando el contexto
# total se acerca al límite. El objetivo es que, incluso con repos grandes,
# los agentes reciban siempre los archivos más informativos.
# ---------------------------------------------------------------------------

# Nombres exactos de archivos con alta prioridad
_HIGH_PRIORITY_NAMES: dict[str, int] = {
    "README.md": 100, "README.rst": 100, "README.txt": 98,
    "package.json": 95, "go.mod": 95, "pyproject.toml": 95,
    "requirements.txt": 94, "Cargo.toml": 94, "pom.xml": 93,
    "build.gradle": 92, "composer.json": 92,
    ".env.example": 88, ".env.sample": 88,
    "docker-compose.yml": 87, "docker-compose.yaml": 87,
    "Dockerfile": 86, "Makefile": 85, "Justfile": 84,
    "go.sum": 20, "package-lock.json": 20, "yarn.lock": 20,
    "poetry.lock": 20, "Cargo.lock": 20,
}

# Patrones de nombre (prefijos) con prioridad alta
_HIGH_PRIORITY_PREFIXES = ("main.", "app.", "index.", "server.", "cmd.", "api.")

# Extensiones de test (baja prioridad)
_TEST_INDICATORS = ("test", "spec", "_test.", ".test.", ".spec.")


@dataclass(frozen=True, slots=True)
class ContextEstimate:
    """
    Resumen cuantitativo del contexto útil de un repositorio.

    Attributes:
        candidate_files: Archivos de texto legibles considerados.
        selected_files: Archivos que caben dentro del presupuesto global.
        total_candidate_chars: Suma de caracteres útiles de todos los candidatos.
        selected_chars: Caracteres que entrarían realmente al contexto.
        oversized_files: Archivos truncados por el límite por archivo.
        budget_truncated_files: Archivos truncados por el límite global.
    """

    candidate_files: int
    selected_files: int
    total_candidate_chars: int
    selected_chars: int
    oversized_files: int
    budget_truncated_files: int


def _score_file(path: Path, root: Path) -> int:
    """
    Calcula la puntuación de prioridad de un archivo para la selección.

    Los archivos con puntuación más alta se incluyen primero cuando el
    contexto alcanza el límite ``max_context_chars``.

    Args:
        path: Path absoluto al archivo.
        root: Raíz del repositorio.

    Returns:
        Puntuación de prioridad (mayor = más importante).
    """
    name = path.name
    rel = path.relative_to(root)
    depth = len(rel.parts) - 1  # 0 = raíz del repo

    # Nombre exacto con puntuación predefinida
    if name in _HIGH_PRIORITY_NAMES:
        return _HIGH_PRIORITY_NAMES[name]

    score = 60  # base para código fuente

    # Archivos en la raíz del repo son más informativos que los anidados
    score -= depth * 3

    # Archivos de entrada principal
    name_lower = name.lower()
    if any(name_lower.startswith(p) for p in _HIGH_PRIORITY_PREFIXES):
        score += 20

    # Archivos de migración / esquema de BD
    if "migrat" in name_lower or "schema" in name_lower or "model" in name_lower:
        score += 10

    # Archivos de test tienen menos prioridad
    if any(t in name_lower for t in _TEST_INDICATORS):
        score -= 20

    return max(score, 1)


class FileReader:
    """
    Construye el RepoContext a partir de un repositorio clonado.

    El árbol de directorios se genera siempre completo para dar a los
    agentes visión global de la estructura. Los contenidos de archivos
    se incluyen en orden de prioridad hasta agotar el presupuesto de
    caracteres, evitando superar el límite de contexto del modelo.

    Usage::

        reader = FileReader()
        ctx = reader.read(Path("/tmp/iwtbi/repo-abc123"))
    """

    def __init__(
        self,
        max_files: int = 2000,
        file_size_limit_kb: int = 500,
        max_context_chars: int = 80_000,
    ) -> None:
        self._max_files = max_files
        self._file_size_limit_bytes = file_size_limit_kb * 1024
        self._max_context_chars = max_context_chars

    def read(self, repo_path: Path) -> RepoContext:
        """
        Lee el repositorio y construye el contexto de análisis.

        Fase 1: genera el árbol ASCII completo y descubre archivos candidatos.
        Fase 2: selecciona archivos por prioridad hasta el límite de caracteres.

        Args:
            repo_path: Ruta raíz del repositorio clonado.

        Returns:
            RepoContext con árbol ASCII y diccionario de contenidos.
        """
        tree_lines, candidates = self._discover_candidates(repo_path)

        # Ordenar candidatos por puntuación descendente y seleccionar
        # hasta agotar el presupuesto de caracteres
        candidates.sort(key=lambda p: _score_file(p, repo_path), reverse=True)
        files = self._select_files(candidates, repo_path)

        _logger.info(
            "Contexto construido: %d archivos, %d chars (límite: %d)",
            len(files),
            sum(len(v) for v in files.values()),
            self._max_context_chars,
        )
        return RepoContext(tree="\n".join(tree_lines), files=files)

    def estimate(self, repo_path: Path) -> ContextEstimate:
        """
        Estima cuánto contexto útil aportaría el repo con las reglas actuales.

        Usa el mismo descubrimiento, filtros y prioridades que ``read()``,
        pero devuelve métricas para decidir si el análisis puede ser completo,
        optimizado o si conviene bloquearlo por tamaño.
        """
        _, candidates = self._discover_candidates(repo_path)
        candidates.sort(key=lambda p: _score_file(p, repo_path), reverse=True)
        return self._estimate_selection(candidates)

    def _discover_candidates(self, repo_path: Path) -> tuple[list[str], list[Path]]:
        """
        Recorre el repo y devuelve el árbol ASCII junto con los candidatos.
        """
        tree_lines: list[str] = []
        candidates: list[Path] = []
        self._walk_tree(repo_path, repo_path, tree_lines, candidates, "")
        return tree_lines, candidates

    def _walk_tree(
        self,
        root: Path,
        current: Path,
        tree_lines: list[str],
        candidates: list[Path],
        prefix: str,
    ) -> None:
        """
        Recorre recursivamente el árbol generando las líneas ASCII y
        recopilando los archivos candidatos a incluir.
        """
        try:
            entries = sorted(
                current.iterdir(),
                key=lambda p: (p.is_file(), p.name.lower()),
            )
        except PermissionError as exc:
            _logger.warning("Sin permiso para listar '%s': %s", current, exc)
            return

        for i, entry in enumerate(entries):
            is_last = i == len(entries) - 1
            connector = "└── " if is_last else "├── "
            extension = "    " if is_last else "│   "
            self._process_entry(
                entry, root, tree_lines, candidates, prefix, connector, extension
            )

    def _process_entry(
        self,
        entry: Path,
        root: Path,
        tree_lines: list[str],
        candidates: list[Path],
        prefix: str,
        connector: str,
        extension: str,
    ) -> None:
        """
        Procesa una entrada del árbol: la añade al árbol ASCII y, si es un
        archivo de texto, la añade a la lista de candidatos.

        Los symlinks se ignoran por seguridad (prevención de path traversal).
        """
        if entry.is_symlink():
            _logger.warning("Symlink ignorado: '%s'", entry)
            return

        try:
            entry.resolve().relative_to(root.resolve())
        except ValueError:
            _logger.warning("Path traversal bloqueado: '%s'", entry)
            return

        if entry.is_dir():
            if entry.name not in EXCLUDED_DIRS:
                tree_lines.append(f"{prefix}{connector}{entry.name}/")
                self._walk_tree(root, entry, tree_lines, candidates, prefix + extension)
        elif entry.is_file():
            tree_lines.append(f"{prefix}{connector}{entry.name}")
            if len(candidates) < self._max_files and self._is_text_file(entry):
                candidates.append(entry)

    def _select_files(self, candidates: list[Path], root: Path) -> dict[str, str]:
        """
        Lee el contenido de los archivos candidatos en orden de prioridad
        hasta agotar el presupuesto de caracteres.

        Args:
            candidates: Lista de archivos ya ordenados por prioridad.
            root: Raíz del repositorio.

        Returns:
            Diccionario {ruta_relativa: contenido} dentro del presupuesto.
        """
        files: dict[str, str] = {}
        chars_used = 0

        for path in candidates:
            if chars_used >= self._max_context_chars:
                _logger.info(
                    "Presupuesto de contexto agotado (%d chars). "
                    "%d archivos incluidos de %d candidatos.",
                    self._max_context_chars, len(files), len(candidates),
                )
                break

            content = self._read_file(path)
            if content is None:
                continue

            # Si el archivo cabe completo dentro del presupuesto restante,
            # se incluye tal cual. Si no, se trunca al espacio disponible.
            remaining = self._max_context_chars - chars_used
            if len(content) > remaining:
                content = content[:remaining] + "\n\n[... contexto truncado por límite global ...]"
                chars_used = self._max_context_chars
            else:
                chars_used += len(content)

            files[str(path.relative_to(root))] = content

        return files

    def _estimate_selection(self, candidates: list[Path]) -> ContextEstimate:
        """
        Replica la selección de contexto y devuelve métricas de cobertura.
        """
        candidate_files = 0
        selected_files = 0
        total_candidate_chars = 0
        selected_chars = 0
        oversized_files = 0
        budget_truncated_files = 0

        for path in candidates:
            content, oversized = self._read_file_with_meta(path)
            if content is None:
                continue

            candidate_files += 1
            total_candidate_chars += len(content)
            if oversized:
                oversized_files += 1

            if selected_chars >= self._max_context_chars:
                continue

            remaining = self._max_context_chars - selected_chars
            selected_files += 1
            if len(content) > remaining:
                budget_truncated_files += 1
                selected_chars = self._max_context_chars
            else:
                selected_chars += len(content)

        return ContextEstimate(
            candidate_files=candidate_files,
            selected_files=selected_files,
            total_candidate_chars=total_candidate_chars,
            selected_chars=selected_chars,
            oversized_files=oversized_files,
            budget_truncated_files=budget_truncated_files,
        )

    def _is_text_file(self, path: Path) -> bool:
        """
        Determina si un archivo es texto analizable por los agentes.
        """
        if path.name in TEXT_FILENAMES:
            return True
        return path.suffix.lower() in TEXT_EXTENSIONS

    def _read_file(self, path: Path) -> str | None:
        """Compatibilidad: devuelve solo el contenido legible."""
        content, _ = self._read_file_with_meta(path)
        return content

    def _read_file_with_meta(self, path: Path) -> tuple[str | None, bool]:
        """
        Lee el contenido de un archivo, truncando si supera el límite por archivo.

        Detecta binarios por bytes nulos en los primeros 512 bytes.

        Args:
            path: Path al archivo a leer.

        Returns:
            Tupla ``(contenido, oversized)``. ``contenido`` será None si es
            binario o ilegible; ``oversized`` indica si se truncó por límite
            por archivo.
        """
        try:
            raw = path.read_bytes()
            if b"\x00" in raw[:512]:
                return None, False
            text = raw.decode("utf-8", errors="replace")
            oversized = len(raw) > self._file_size_limit_bytes
            if oversized:
                limit_chars = self._file_size_limit_bytes
                text = text[:limit_chars] + "\n\n[... archivo truncado por límite de tamaño ...]"
            return text, oversized
        except OSError as exc:
            _logger.warning("No se pudo leer '%s': %s", path, exc)
            return None, False
