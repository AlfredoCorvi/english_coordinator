# Planeación de inglés

Aplicación local en **Streamlit**, con persistencia SQLite y asignación mediante **OR-Tools CP-SAT**. Reúne estudiantes de distintas carreras, forma grupos, asigna docentes y salones, audita las restricciones y exporta Excel y PDF.

Documentación funcional: [casos de uso, actores y reglas de negocio](docs/casos_de_uso.md).

## Iniciar en Windows

Desde `C:\Users\josea\software_projects\hackaton`:

```powershell
.\venv\Scripts\python.exe -m pip install -r requirements.txt
.\venv\Scripts\python.exe -m streamlit run app.py
```

Abre <http://localhost:8501>. También puedes ejecutar `./iniciar.ps1` desde PowerShell. El script crea el entorno si no existe; si ya existe, instala primero los requisitos con el comando anterior. Python 3.12–3.14; verificado aquí con Python 3.14.

En otro equipo:

```powershell
python -m venv venv
.\venv\Scripts\python.exe -m pip install -r requirements.txt
.\venv\Scripts\python.exe -m streamlit run app.py
```

La aplicación escucha únicamente en `127.0.0.1`. Esta versión está pensada para una coordinadora en un equipo; no incorpora autenticación ni roles. Para un servicio institucional compartido, se recomienda Django con autenticación, permisos y PostgreSQL. Streamlit ofrece el editor tabular necesario para este flujo; la lógica de dominio está separada de la interfaz para facilitar una migración.

Referencias técnicas: [editor de Streamlit](https://docs.streamlit.io/develop/api-reference/data/st.data_editor), [Django](https://www.djangoproject.com/start/overview/), [estados del solver CP-SAT](https://github.com/google/or-tools/blob/stable/ortools/sat/docs/troubleshooting.md).

## Recorrido

1. En **Vista general**, puedes cargar una demostración identificada con 180 alumnos ficticios. La base inicia vacía.
2. En **Datos**, carga los Excel de alumnos y docentes; agrega los salones o importa su Excel. Descarga los ejemplos para conocer las columnas.
3. Selecciona la hoja, relaciona columnas, elige agregar/actualizar por identificador o reemplazar y pulsa **Llevar a revisión**. Edita la tabla y pulsa **Validar y guardar**. Una importación no modifica la base hasta ese paso. Guarda antes de cambiar de sección.
4. En **Bloques y reglas**, define jornada, agrupación, cupos y traslados. Crea bloques de siete horas o pulsa **Proponer bloques sin superposición**, revisa y guarda la propuesta.
5. En **Generar**, calcula una asignación completa. Si encuentra una propuesta y pasa la auditoría, abre **Resultados** y guarda una versión.
6. Revisa las listas por grupo y **Auditoría**: semana por docente/salón/bloque, cargas y reservas para carreras.
7. Modifica grupos o matrículas en **Ajustes manuales**. **Auditar y guardar nueva versión** rechaza conflictos. Los cambios en los catálogos marcan las versiones anteriores como desactualizadas; revalídalas o genera otra propuesta antes de exportar.
8. En **Exportar**, prepara y descarga Excel y PDF.

## Reglas implementadas

- Niveles originales: Prebasic y Basic 1 → A1; Basic 2 y Basic 3 → A2; Intermediate 1 y 2 → B1; Intermediate 3 y 4 → B2; Advanced 1 → C1.
- Por la indicación de agrupar A con A, B con B y C con C, el valor inicial es **familia A/B/C**. Esto mezcla A1 con A2 y B1 con B2. Se puede cambiar a MCER individual (A1, A2, B1, B2, C1) o curso exacto. El nivel original siempre aparece en los listados.
- Máximo configurable de **25 a 30** alumnos, inicialmente 30, limitado además por la capacidad del salón. El mínimo inicial es 1, porque un remanente debe poder recibir clase; los grupos menores de 25 generan avisos. Puede exigirse otro mínimo.
- Cada alumno queda en exactamente un grupo de inglés. **Todos los alumnos de la misma combinación Carrera + Grupo deben compartir un único bloque semanal**, con los mismos días y horas, aunque estén repartidos entre distintos grupos de inglés según su nivel. Esta regla es obligatoria en la generación, las ediciones manuales y la auditoría. Grupos de carrera distintos pueden tener bloques diferentes.
- Un grupo tiene un docente, un salón fijo, un nivel agrupado y un bloque de exactamente siete periodos entre lunes y viernes. Un bloque admite varios grupos simultáneos con recursos distintos.
- Los periodos duran 60 minutos, con jornada continua. El inicio de jornada y la cantidad de periodos son configurables. No se modelan aún recesos, periodos de diferente duración ni traslados de alumnos entre sus clases regulares, que todavía no existen.
- Docentes de cualquier nivel, dentro de sus edificios permitidos, disponibilidad y carga semanal. Las horas máximas son las horas **disponibles para inglés**, después de descontar otras obligaciones.
- Cinco edificios: 1, 2, 3, 4 e Idiomas. Los edificios de alumnos son preferencia, salvo que se active la restricción estricta. Los edificios permitidos del docente son una restricción obligatoria. Usa un solo edificio si el docente no puede trasladarse.
- Un periodo libre entre clases en edificios diferentes para docentes, configurable de 0 a 4. No hay una matriz de tiempos entre edificios; todas las parejas usan la misma regla conservadora.
- Los bloques pueden solaparse, pero los salones y docentes nunca se solapan. La comprobación usa día y periodo reales, no solo el nombre del bloque.
- **Bloque fijo** reserva un bloque para todo el grupo de carrera del alumno que lo indique. Si dos compañeros indican bloques diferentes, la validación pide corregirlos. Si nadie indica una reserva, el sistema elige un bloque común.
- Se minimiza primero el número de grupos y después el número de alumnos asignados fuera de su edificio. No se promete equilibrio de tamaño entre grupos ni una solución óptima si el solver informa `FEASIBLE`.
- El solver elige entre los patrones de bloques guardados. La propuesta automática de patrones distribuye periodos sin solaparlos; **no busca todas las formas posibles de repartir siete horas**. Un resultado imposible se refiere a esos bloques y restricciones; prueba modificando los patrones.
- No se exportan asignaciones incompletas o con errores. Un límite de tiempo sin solución se distingue de una imposibilidad demostrada.

## Excel de entrada

Formatos `.xlsx`, primera fila con encabezados, una fila por registro. Se aceptan alias comunes y se pueden relacionar manualmente las columnas. Se conserva la matrícula como texto, incluidos ceros iniciales escritos como texto o mediante formato de ceros de Excel. Convierte fórmulas a valores antes de importar.

| Tabla | Columnas |
| --- | --- |
| Alumnos | Matricula, Nombre, Grupo, Carrera, Edificio, Nivel, Bloque fijo (opcional) |
| Docentes | ID, Nombre, Edificios, Horas máximas, Lunes, Martes, Miércoles, Jueves, Viernes |
| Salones | ID, Salón, Edificio, Capacidad, Lunes, Martes, Miércoles, Jueves, Viernes |
| Bloques | Bloque, Lunes, Martes, Miércoles, Jueves, Viernes |

En los días, `1,2,4-6` indica periodos disponibles; `*` toda la jornada y celda vacía ninguna disponibilidad. Cada bloque debe sumar siete periodos distintos. Ejemplo con ocho periodos diarios:

| Bloque | Lunes | Martes | Miércoles | Jueves | Viernes |
| --- | --- | --- | --- | --- | --- |
| Bloque 1 | 1,2 | | 4 | 7,8 | 4,5 |

En docentes, `Edificios` acepta `1,2,Idiomas` o `*`. La clave de cada salón debe ser única, aunque pueda existir un salón 101 en edificios distintos. La pareja Carrera + Grupo identifica un grupo de origen.

## Resultados y auditoría

La primera hoja del Excel usa exactamente estas columnas:

`Matricula | Nombre | Grupo | Nombre de materia | Grupo Inglés | Nivel de inglés | Docente | Salón`

**Grupo** conserva el grupo de carrera, **Nombre de materia** es el bloque y **Grupo Inglés** es la asignación generada. **Salón** incluye también el edificio. El libro agrega resúmenes, horarios con horas, carga docente, auditoría, reservas para carreras y una hoja imprimible por grupo de inglés.

El PDF contiene resumen, carga docente, avisos, calendario de cada bloque y listas por grupo. Los encabezados se repiten al continuar una tabla en otra página.

La auditoría es independiente del solver y revisa datos, cobertura exacta, niveles, cupos, referencias, horarios, edificios, carga y traslados. También se aplica a los ajustes manuales y antes de exportar.

**Planeación posterior de materias regulares:** cada grupo de carrera tiene siete horas comunes de inglés. La hoja **Reservas carrera** registra esos días y periodos por Carrera + Grupo para que sus materias regulares eviten ese horario. No se exige el mismo bloque a toda una carrera, solo a cada grupo de origen. Todavía no se importan ni se auditan horarios de materias regulares.

## Base de datos e historial

Los datos se guardan en `data/ingles.sqlite3`. Cada guardado crea una revisión de catálogos/configuración y cada propuesta crea una versión de horario ligada a esa revisión. Los identificadores y claves se conservan como texto. Las transacciones rechazan el guardado desde una sesión que tenga una revisión anterior, para evitar sobrescrituras concurrentes.

Los horarios anteriores siguen disponibles; la interfaz los revisa contra los catálogos actuales y deshabilita exportaciones hasta que la revisión esté vigente. Para respaldar, detén la aplicación y copia el archivo SQLite. `INGLES_DB_PATH` permite usar otra ruta, útil para pruebas. La base, los Excel y PDF generados, y los entornos están excluidos de Git.

Al abrir una base de la versión anterior, que permitía desactivar el bloque compartido, se crea automáticamente una revisión con la nueva regla obligatoria. Se conserva el historial; los horarios anteriores deben revalidarse o regenerarse antes de exportar.

## Pruebas

```powershell
.\venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\venv\Scripts\python.exe -m pytest -q
```

Las pruebas cubren asignación completa, agrupación, capacidad, disponibilidad, traslados, choques con bloques diferentes, restricciones imposibles, cambios manuales, persistencia, concurrencia, lectura de Excel, exportaciones y el recorrido de Streamlit con una base temporal.

## Estructura

- `app.py`: interfaz y navegación.
- `ingles/domain.py`: niveles, validaciones, periodos y datos de demostración.
- `ingles/scheduler.py`: modelo de restricciones y objetivo CP-SAT.
- `ingles/audit.py`: auditor independiente.
- `ingles/storage.py`: SQLite y revisiones.
- `ingles/exchange.py`: lectura, plantillas y exportación Excel.
- `ingles/reports.py`: reporte PDF.
- `tests/`: pruebas de dominio e integración.

El núcleo no depende de Streamlit y se puede reutilizar desde Django si el alcance crece.
