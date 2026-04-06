"""
Contexto de un repositorio clonado y leído.

RepoContext es la estructura que el módulo file_reader construye y que
todos los agentes reciben como entrada. El árbol ASCII permite a los
agentes entender la estructura global aunque algunos archivos estén truncados.
"""

from pydantic import BaseModel


class RepoContext(BaseModel):
    """
    Contexto completo de un repositorio para los agentes LangChain.

    Attributes:
        tree: Árbol de directorios en formato ASCII (siempre completo).
        files: Diccionario {ruta_relativa: contenido}. Los archivos
               grandes pueden estar truncados según FILE_SIZE_LIMIT_KB.
    """

    tree: str
    files: dict[str, str]

    @property
    def as_text(self) -> str:
        """
        Serializa el contexto como texto plano para el prompt del agente.

        El árbol se incluye primero para dar visión global de la estructura,
        seguido del contenido de cada archivo en bloques de código.

        Returns:
            Cadena con el árbol y los contenidos listos para el prompt.
        """
        parts = [f"## Árbol de archivos\n\n```\n{self.tree}\n```\n"]
        for path, content in self.files.items():
            parts.append(f"## {path}\n\n```\n{content}\n```\n")
        return "\n".join(parts)
