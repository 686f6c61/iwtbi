"""
Singleton del cliente Supabase.

Proporciona una única instancia del cliente para todo el proceso del backend.
Usa la clave service_role para tener permisos de escritura sin restricciones de RLS.
"""

from functools import lru_cache

from supabase import Client, create_client

from app.config import settings


@lru_cache(maxsize=1)
def get_client() -> Client:
    """
    Devuelve el singleton del cliente Supabase.

    El decorador lru_cache garantiza que solo se crea una conexión
    durante toda la vida del proceso, independientemente de cuántos
    módulos importen esta función.

    Returns:
        Cliente Supabase autenticado con la clave service_role.

    Raises:
        ValueError: Si SUPABASE_URL o SUPABASE_SERVICE_KEY no están configurados.
    """
    if not settings.supabase_url or not settings.supabase_service_key:
        raise ValueError(
            "SUPABASE_URL y SUPABASE_SERVICE_KEY son obligatorias. "
            "Comprueba el fichero .env del backend."
        )
    return create_client(settings.supabase_url, settings.supabase_service_key)
