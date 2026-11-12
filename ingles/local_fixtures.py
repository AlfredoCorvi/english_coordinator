"""Datos ficticios, sin credenciales y siempre importados como lote parcial."""
from ingles.integrations import Batch


class LocalFixture:
    def __init__(self, kind):
        if kind not in ('ALUMNOS', 'MAESTROS'):
            raise ValueError('Tipo desconocido.')
        self.kind = kind

    def fetch(self):
        if self.kind == 'ALUMNOS':
            return Batch([{'id_externo': 'demo-001', 'matricula': 'DEMO001', 'nombre': 'Alumna ficticia',
                           'carrera_id': 'demo-carrera', 'carrera': 'Carrera ficticia', 'grupo_id': 'demo-grupo',
                           'grupo': 'DEMO-31', 'edificio': '1', 'turno': 'Matutino', 'estatus': 'Activo'}], False)
        return Batch([{'id_externo': 'demo-docente', 'nombre': 'Docente ficticio',
                       'tipo_contratacion': 'PA', 'sujeto_identidad': 'docente.demo'}], False)
