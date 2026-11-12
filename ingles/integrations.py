"""Contratos sustituibles para servicios institucionales; sin credenciales embebidas."""
from dataclasses import dataclass
import json
import os
from typing import Protocol
from urllib.request import Request, urlopen
from urllib.parse import urlsplit
from urllib.error import HTTPError, URLError


class IntegrationError(Exception):
    """Error seguro para mostrar y registrar, sin URL ni respuesta externa."""


@dataclass(frozen=True)
class Batch:
    records: list
    complete: bool = False


class DirectoryProvider(Protocol):
    def fetch(self) -> Batch: ...


@dataclass(frozen=True)
class Identity:
    provider: str
    subject: str


class AuthenticationProvider(Protocol):
    def authenticate(self, username: str, password: str) -> Identity | None: ...


class MockarooProvider:
    """Un arreglo JSON simple es incompleto salvo configuración explícita confiable."""
    def __init__(self, endpoint: str, *, complete_snapshot: bool = False, expected_count: int | None = None, timeout: float = 15):
        if urlsplit(endpoint).scheme != 'https' or not urlsplit(endpoint).hostname:
            raise ValueError('El endpoint debe usar HTTPS.')
        self._endpoint = endpoint
        self._complete = complete_snapshot
        if complete_snapshot and (type(expected_count) is not int or expected_count < 1):
            raise ValueError('Un lote completo requiere un conteo esperado positivo.')
        self._expected_count = expected_count
        self._timeout = timeout

    def fetch(self) -> Batch:
        try:
            with urlopen(Request(self._endpoint, headers={'Accept': 'application/json'}), timeout=self._timeout) as response:
                data = json.load(response)
        except HTTPError as exc:
            if exc.code in (401,403):
                raise IntegrationError('La API rechazó la clave o los permisos (HTTP 401/403).') from None
            if exc.code==404:
                raise IntegrationError('La API no encontró el recurso configurado (HTTP 404).') from None
            if exc.code==429:
                raise IntegrationError('La API alcanzó su límite de solicitudes (HTTP 429).') from None
            raise IntegrationError('La API devolvió un error HTTP.') from None
        except (URLError,OSError):
            raise IntegrationError('No fue posible conectar con la API institucional.') from None
        except (ValueError, UnicodeError):
            raise IntegrationError('La API devolvió una respuesta JSON inválida.') from None
        if not isinstance(data, list):
            raise IntegrationError('La respuesta institucional no es una lista.')
        if self._complete and len(data) != self._expected_count:
            raise IntegrationError('El tamaño del lote no coincide con el conteo esperado.')
        return Batch(data, self._complete)


class MappedProvider:
    """Mapea nombres externos a nombres canónicos sin suponer el esquema remoto."""
    def __init__(self, provider: DirectoryProvider, fields: dict):
        self._provider, self._fields = provider, dict(fields)

    def fetch(self):
        batch = self._provider.fetch()
        if not isinstance(batch, Batch) or not isinstance(batch.records, list):
            raise IntegrationError('Formato de lote inválido.')
        if any(not isinstance(row, dict) for row in batch.records):
            raise IntegrationError('Registro institucional inválido.')
        return Batch([{target: row.get(source) for target, source in self._fields.items()}
                      for row in batch.records], batch.complete)


class VerifiedMockarooMapping:
    """Campos observados en los endpoints; identidades de docentes se configuran aparte."""
    def __init__(self, provider, kind, identities=None):
        self.provider, self.kind, self.identities = provider, kind, identities or {}

    def fetch(self):
        batch = self.provider.fetch()
        result = []
        for row in batch.records:
            if not isinstance(row, dict):
                raise IntegrationError('Registro institucional inválido.')
            if self.kind == 'ALUMNOS':
                enrollment = row.get('matricula')
                career, group = row.get('carrera'), row.get('grupo_academico')
                if isinstance(enrollment, bool) or not isinstance(enrollment, (str, int)) or not str(enrollment).strip():
                    raise IntegrationError('La matrícula debe ser texto o un entero.')
                # Numeric identifiers cannot carry leading zeroes; the source must supply text to preserve them.
                enrollment = str(enrollment).strip()
                if not isinstance(career, str) or not career.strip() or not isinstance(group, str) or not group.strip():
                    raise IntegrationError('Faltan carrera o grupo académico.')
                result.append({'id_externo': enrollment, 'matricula': enrollment, 'nombre': row.get('nombre'),
                               'carrera_id': career.strip(), 'carrera': career, 'grupo_id': json.dumps([career.strip(), group.strip()], ensure_ascii=False),
                               'grupo': group, 'edificio': row.get('edificio'), 'turno': row.get('turno'), 'estatus': row.get('estatus_escolar')})
            else:
                number = row.get('numero_empleado')
                number = str(number).strip() if number is not None else ''
                result.append({'id_externo': number, 'nombre': row.get('nombre'), 'tipo_contratacion': row.get('tipo_contratacion'),
                               'sujeto_identidad': self.identities.get(number)})
        return Batch(result, batch.complete)


def provider_from_environment(kind: str):
    """Carga URL y mapeo desde el entorno, sin registrar sus valores."""
    if kind not in ('ALUMNOS', 'MAESTROS'):
        raise ValueError('Tipo de integración inválido.')
    prefix = f'INGLES_{kind}'
    endpoint, mapping = os.environ.get(prefix + '_URL'), os.environ.get(prefix + '_FIELDS')
    if not endpoint:
        raise ValueError(f'Falta la variable de entorno {prefix}_URL; configura la URL HTTPS completa antes de iniciar Streamlit.')
    fields = None
    if mapping:
        try:
            fields = json.loads(mapping)
        except ValueError:
            raise ValueError('El mapeo de campos debe ser JSON válido.') from None
        if not isinstance(fields, dict) or not all(isinstance(k, str) and isinstance(v, str) and k and v for k, v in fields.items()):
            raise ValueError('El mapeo de campos debe ser un objeto de nombres de texto.')
    complete = os.environ.get(prefix + '_COMPLETE', 'false').lower()
    if complete not in ('true', 'false'):
        raise ValueError('La configuración COMPLETE debe ser true o false.')
    expected = os.environ.get(prefix + '_EXPECTED_COUNT')
    if complete == 'true' and (not expected or not expected.isdecimal() or int(expected) < 1):
        raise ValueError('Un lote completo requiere EXPECTED_COUNT positivo.')
    provider = MockarooProvider(endpoint, complete_snapshot=complete == 'true',
                                expected_count=int(expected) if complete == 'true' else None)
    if fields is not None:
        return MappedProvider(provider, fields)
    identities = {}
    if kind == 'MAESTROS':
        if not os.environ.get('INGLES_MAESTROS_IDENTIDADES'):
            raise ValueError('Falta INGLES_MAESTROS_IDENTIDADES: se requiere un mapa verificado de número de empleado a sujeto de autenticación.')
        try:
            identities = json.loads(os.environ.get('INGLES_MAESTROS_IDENTIDADES', '{}'))
        except ValueError:
            raise ValueError('El mapa de identidades no es JSON válido.') from None
        if not isinstance(identities, dict) or not all(isinstance(k, str) and isinstance(v, str) and k and v for k, v in identities.items()):
            raise ValueError('El mapa de identidades debe contener textos.')
    return VerifiedMockarooMapping(provider, kind, identities)


class ConfigurableTestAuth:
    """Proveedor de pruebas en memoria; no usar como autenticación institucional."""
    def __init__(self, credentials: dict):
        self._credentials = dict(credentials)

    def authenticate(self, username, password):
        entry = self._credentials.get(username)
        if entry and entry[0] == password:
            return entry[1]
        return None
