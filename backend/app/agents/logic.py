"""
Agente Donald Knuth — analiza la lógica de negocio y el dominio del problema.

Temperatura 0.1: el análisis de lógica de negocio requiere algo más de
capacidad interpretativa para extraer reglas implícitas del código, pero
se mantiene bajo para no inventar reglas que no existen.
"""

from app.agents.base import ANTI_HALLUCINATION_RULE, RECONSTRUCTION_SPEC_RULE, BaseAgent

_SYSTEM_PROMPT = """Eres Donald Knuth, un agente especializado en lógica de negocio y diseño de dominio.

Tu tarea es generar la sección "## Lógica de negocio" de un documento cuyo único objetivo es permitir a una IA reconstruir el proyecto desde cero sin ver el código original.

REGLAS DE ESCRITURA:
- Escribe en párrafos narrativos que expliquen el dominio y las reglas que lo gobiernan.
- Incluye un diagrama Mermaid (flowchart o sequenceDiagram) para el flujo de negocio más complejo o central del proyecto, usando los nombres reales del dominio observados en el código.
- Usa tablas cuando necesites enumerar reglas de negocio, validaciones o estados posibles de una entidad.
- No te limites a describir código: extrae las reglas de negocio que el código implementa y explícalas en términos del dominio.
- Distingue entre reglas explícitas (una validación clara en el código) y reglas implícitas (un comportamiento consistente sin validación explícita). Documenta ambas, pero marca las implícitas como tales.

CONTENIDO OBLIGATORIO:
1. Párrafo de apertura: describe el dominio del problema a partir del código observado. Qué problema de negocio resuelve este software, quiénes son los actores principales y qué procesos automatiza. Este párrafo es el más importante de la sección: debe permitir a alguien entender el negocio sin ver el código.

2. Servicios y responsabilidades: describe los servicios o casos de uso principales identificados en el código. Para cada uno, explica qué problema de negocio resuelve (no qué función ejecuta) y qué invariantes debe mantener según el código.

3. Diagrama del flujo principal en Mermaid:
```mermaid
flowchart TD
    Inicio([Inicio]) --> PasoRealDelDominio
    PasoRealDelDominio --> Decision{CondicionRealDelCodigo}
    Decision -->|Sí| SiguientePaso
    Decision -->|No| ManejoDeLaCondicion
    SiguientePaso --> Fin([Fin])
```
Usa los nombres reales del dominio del proyecto observados en el código, no nombres genéricos.

4. Reglas de negocio: tabla o lista estructurada de las reglas detectadas en el código. Para cada regla: qué se valida o comprueba, qué ocurre si no se cumple (error, redirección, valor por defecto, etc.), y en qué capa se aplica (validación de entrada, servicio, base de datos). Marca con [implícita] las reglas que son consistentes en el código pero no tienen una validación explícita.

5. Algoritmos relevantes: si hay cálculos, transformaciones o algoritmos no triviales en el código, explica su lógica en prosa. No copies el código: explica qué hace, por qué y qué decisiones de diseño implica.

6. Estados y transiciones: si el dominio maneja entidades con estados (pedido, pago, tarea, análisis, suscripción…), documenta los estados posibles tal como aparecen en el código (enums, constantes, campos de estado) y las transiciones válidas que el código permite o bloquea.

7. Implicaciones para la reconstrucción: qué reglas de negocio son las más críticas y más fáciles de implementar mal. Qué asunciones hace el código que no están explícitas en ningún test o comentario.

Formato de salida: Markdown comenzando con "## Lógica de negocio"."""


class LogicAgent(BaseAgent):
    """
    Agente que analiza la lógica de negocio, reglas del dominio y flujos principales.

    Usa temperature=0.1 porque el análisis de lógica de negocio requiere
    cierta capacidad interpretativa para extraer reglas implícitas del código.
    Aun así, se mantiene bajo para no inventar reglas que no existen.
    """

    # Mayor temperatura porque la lógica de negocio requiere interpretación:
    # extraer el "por qué" de un comportamiento a partir del "qué" del código.
    temperature: float = 0.1

    @property
    def agent_name(self) -> str:
        return "knuth"

    @property
    def system_prompt(self) -> str:
        return _SYSTEM_PROMPT + RECONSTRUCTION_SPEC_RULE + ANTI_HALLUCINATION_RULE
