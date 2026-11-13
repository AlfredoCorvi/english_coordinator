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
3. Selecciona la hoja, relaciona columnas, elige agregar/actualizar por matrícula, salón o bloque, o reemplazar, y pulsa **Llevar a revisión**. Edita la tabla y pulsa **Validar y guardar**. La pestaña seleccionada se conserva y aparece una notificación superior durante cuatro segundos. Una importación no modifica la base hasta ese paso. Guarda antes de cambiar de sección.
4. En **Bloques y reglas**, define inicio y fin de jornada, duración de periodos, receso, agrupación y cupos. En **Bloques semanales**, elige la **Cantidad de bloques a proponer**, pulsa **Proponer bloques sin superposición**, revisa y guarda la propuesta. El máximo se calcula según los periodos disponibles de lunes a viernes, a razón de siete por bloque. También puedes editar los bloques manualmente.
5. En **Generar**, calcula una asignación completa. Si encuentra una propuesta y pasa la auditoría, abre **Resultados** y guarda una versión. Si falla, muestra impedimentos con cantidades y grupos afectados, acciones sugeridas y botones para abrir la pestaña correspondiente. Los conflictos combinados se explican como un conjunto de condiciones incompatibles, no como una única causa garantizada.
6. Revisa **Por grupo de inglés** y **Auditoría**: semana por docente, salón, bloque, grupo de inglés o grupo de carrera, además de cargas y reservas para carreras. Para un grupo de carrera, selecciona primero la carrera y después el grupo; el calendario muestra su horario común con los grupos de inglés donde están asignados sus alumnos.
7. Modifica grupos o matrículas en **Ajustes manuales**. **Auditar y guardar nueva versión** rechaza conflictos. Los cambios en los catálogos marcan las versiones anteriores como desactualizadas; revalídalas o genera otra propuesta antes de exportar.
8. En **Exportar**, prepara y descarga el Excel general, el Excel por grupos de carrera y el PDF.

## Reglas implementadas

- Niveles originales: Prebasic y Basic 1 → A1; Basic 2 y Basic 3 → A2; Intermediate 1 y 2 → B1; Intermediate 3 y 4 → B2; Advanced 1 → C1.
- Por la indicación de agrupar A con A, B con B y C con C, el valor inicial es **familia A/B/C**. Esto mezcla A1 con A2 y B1 con B2. Se puede cambiar a MCER individual (A1, A2, B1, B2, C1) o curso exacto. El nivel original siempre aparece en los listados.
- Máximo configurable de **25 a 35** alumnos, inicialmente 30, limitado además por la capacidad del salón. El mínimo inicial es 1, porque un remanente debe poder recibir clase; los grupos menores de 25 generan avisos. Puede exigirse otro mínimo.
- Cada alumno queda en exactamente un grupo de inglés. **Todos los alumnos de la misma combinación Carrera + Grupo deben compartir un único bloque semanal**, con los mismos días y horas, aunque estén repartidos entre distintos grupos de inglés según su nivel. Esta regla es obligatoria en la generación, las ediciones manuales y la auditoría. Grupos de carrera distintos pueden tener bloques diferentes.
- Un grupo tiene un docente, un salón fijo, un nivel agrupado y un bloque de exactamente siete periodos entre lunes y viernes. Un bloque admite varios grupos simultáneos con recursos distintos.
- La duración de los periodos es configurable entre 1 y 180 minutos; el valor inicial es **45 minutos**. Cada bloque mantiene **siete periodos semanales**, equivalentes por defecto a **315 minutos (5 horas y 15 minutos)**. Todos los periodos de una planeación tienen la misma duración.
- El receso diario es configurable y por defecto va de **11:30 a 11:55**, de lunes a viernes. No es un periodo asignable ni cuenta como tiempo de clase. Si un periodo completo invade el receso, comienza al terminar este; no se divide ni se acorta. Los minutos que no alcancen para una clase antes del receso quedan libres.
- El inicio y fin de jornada son configurables; el fin inicial es **15:45**. La cantidad de periodos diarios se calcula automáticamente con los periodos completos que caben antes y después del receso. Por ejemplo, **08:30–15:40**, con periodos de 45 minutos y receso 11:30–11:55, permite **nueve periodos diarios**. Los minutos sobrantes al final quedan libres. La tabla **Jornada guardada** muestra sus horas reales. Cambiar estos valores desplaza las horas de los periodos; revisa disponibilidades y bloques guardados. No se modelan duraciones diferentes dentro de una misma jornada ni horarios regulares de alumnos.
- Docentes de cualquier nivel, dentro de sus edificios permitidos, disponibilidad y carga semanal. **Horas máximas** son horas de reloj disponibles para inglés, después de descontar otras obligaciones. La generación y auditoría calculan la carga en minutos exactos: siete periodos de 45 minutos consumen 5.25 horas, sin contar el receso. Los resúmenes muestran horas decimales redondeadas a dos posiciones.
- Cinco edificios: 1, 2, 3, 4 e Idiomas. Los edificios de alumnos son preferencia, salvo que se active la restricción estricta. Los edificios permitidos del docente son una restricción obligatoria. Usa un solo edificio si el docente no puede trasladarse.
- Se retiró el campo y la restricción de periodos libres para traslado. Un docente puede tener clases consecutivas en sus edificios permitidos, siempre sin superposición.
- Los bloques pueden solaparse, pero los salones y docentes nunca se solapan. La comprobación usa día y periodo reales, no solo el nombre del bloque.
- **Bloque fijo** reserva un bloque para todo el grupo de carrera del alumno que lo indique. Si dos compañeros indican bloques diferentes, la validación pide corregirlos. Si nadie indica una reserva, el sistema elige un bloque común.
- Se minimiza primero el número de grupos y después el número de alumnos asignados fuera de su edificio. No se promete equilibrio de tamaño entre grupos ni una solución óptima si el solver informa `FEASIBLE`.
- El solver elige entre los patrones de bloques guardados, incluidos los que usan los últimos periodos del día. La propuesta automática distribuye periodos por toda la jornada sin solaparlos; **no busca todas las formas posibles de repartir siete periodos**. Ampliar la jornada no modifica bloques ya guardados: edítalos o propón otros para aprovechar el nuevo horario. Un resultado imposible se refiere a esos bloques y restricciones.
- La cantidad elegida controla cuántos bloques crea la propuesta automática; no obliga a utilizar todos en una asignación. Si eliges menos que el máximo, selecciona patrones repartidos a lo largo de la jornada. La tabla se persiste al pulsar **Validar y guardar** y su cantidad se usa como valor inicial al volver a abrir la sección, limitada al máximo que permita la jornada actual. Con once periodos por día se pueden proponer de uno a siete bloques sin superposición. Los bloques manuales conservan la posibilidad de solaparse.
- No se exportan asignaciones incompletas o con errores. Un límite de tiempo sin solución se distingue de una imposibilidad demostrada.

## Excel de entrada

Formatos `.xlsx`, primera fila con encabezados, una fila por registro. Se aceptan alias comunes y se pueden relacionar manualmente las columnas. Se conserva la matrícula como texto, incluidos ceros iniciales escritos como texto o mediante formato de ceros de Excel. Convierte fórmulas a valores antes de importar.

| Tabla | Columnas |
| --- | --- |
| Alumnos | Matricula, Nombre, Grupo, Carrera, Edificio, Nivel, Bloque fijo (opcional) |
| Docentes | matricula_docente, Nombre, Edificios, Horas máximas, Lunes, Martes, Miércoles, Jueves, Viernes |
| Salones | Salón, Edificio, Capacidad, Lunes, Martes, Miércoles, Jueves, Viernes |
| Bloques | Bloque, Lunes, Martes, Miércoles, Jueves, Viernes |

En los días, `1,2,4-6` indica periodos disponibles; `*` toda la jornada y celda vacía ninguna disponibilidad. Cada bloque debe sumar siete periodos distintos. Ejemplo con ocho periodos diarios:

| Bloque | Lunes | Martes | Miércoles | Jueves | Viernes |
| --- | --- | --- | --- | --- | --- |
| Bloque 1 | 1,2 | | 4 | 7,8 | 4,5 |

En docentes, `Edificios` acepta `1,2,Idiomas` o `*`. `matricula_docente` es obligatoria y única; se conserva como texto. Los salones se identifican por Edificio + Salón. Las claves internas se generan automáticamente, no se muestran en las tablas y se conservan al editar o reimportar los mismos registros. En ajustes manuales se seleccionan docentes por nombre y matrícula, y salones por edificio y número. La pareja Carrera + Grupo identifica un grupo de origen.

Con la jornada predeterminada de 07:00 a 15:45 hay once periodos: los primeros seis van de 07:00 a 11:30, el séptimo de 11:55 a 12:40 y el último de 14:55 a 15:40. El receso no tiene número de periodo, por lo que ni un bloque manual ni una disponibilidad `*` pueden asignarle clases.

## Resultados y auditoría

La primera hoja del Excel usa exactamente estas columnas:

`Matricula | Nombre | Grupo | Nombre de materia | Grupo Inglés | Nivel de inglés | Docente | Salón`

**Grupo** conserva el grupo de carrera, **Nombre de materia** es el bloque y **Grupo Inglés** es la asignación generada. **Salón** incluye también el edificio. El libro agrega resúmenes, horarios con horas reales, jornada con el receso identificado como no asignable, carga docente en horas de reloj, auditoría, reservas para carreras con sus horas y una hoja imprimible por grupo de inglés.

El PDF contiene resumen, duración de periodos, receso, carga docente en horas de reloj, avisos, calendario de cada bloque y listas por grupo. Los calendarios marcan el receso como tiempo sin clases. Los encabezados se repiten al continuar una tabla en otra página.

El **Excel por grupos de carrera** es una descarga adicional, con una hoja por Carrera + Grupo aunque dos carreras tengan el mismo código de grupo. Cada hoja incluye título de carrera/grupo, horario común y las ocho columnas del listado. Conserva nivel original, grupo de inglés, docente y salón de cada alumno; está preparado para imprimir en horizontal y repetir los encabezados en cada página.

La tarjeta **Grupos que permiten las horas docentes** suma los grupos completos que cada docente puede cubrir según sus horas máximas. Es un límite teórico y no una promesa de cupos: los horarios, edificios y recursos simultáneos pueden reducirlo. El detalle por bloque muestra docentes y salones compatibles.

La auditoría es independiente del solver y revisa datos, cobertura exacta, niveles, cupos, referencias, horarios, límites de jornada, receso, edificios y carga docente. También se aplica a los ajustes manuales y antes de exportar.

**Planeación posterior de materias regulares:** cada grupo de carrera tiene siete periodos comunes de inglés. La hoja **Reservas carrera** registra esos días, periodos y horas reales por Carrera + Grupo para que sus materias regulares eviten ese horario. No se exige el mismo bloque a toda una carrera, solo a cada grupo de origen. Todavía no se importan ni se auditan horarios de materias regulares.

## Base de datos e historial

Los datos se guardan en `data/ingles.sqlite3`. Cada guardado crea una revisión de catálogos/configuración y cada propuesta crea una versión de horario ligada a esa revisión. Los identificadores y claves se conservan como texto. Las transacciones rechazan el guardado desde una sesión que tenga una revisión anterior, para evitar sobrescrituras concurrentes.

Los horarios anteriores siguen disponibles; la interfaz los revisa contra los catálogos actuales y deshabilita exportaciones hasta que la revisión esté vigente. Para respaldar, detén la aplicación y copia el archivo SQLite. `INGLES_DB_PATH` permite usar otra ruta, útil para pruebas. La base, los Excel y PDF generados, y los entornos están excluidos de Git.

Al abrir una base de la versión anterior, que permitía desactivar el bloque compartido, se crea automáticamente una revisión con la nueva regla obligatoria. Se conserva el historial; los horarios anteriores deben revalidarse o regenerarse antes de exportar.

Las bases anteriores a la configuración de recesos reciben una nueva revisión con periodos de 45 minutos y receso de 11:30 a 11:55. Se conservan alumnos, docentes, salones, bloques y versiones anteriores. La coordinadora puede ajustar esos valores en Reglas; los horarios previos deben revalidarse o regenerarse. Las configuraciones de duración y receso guardadas con esta versión se respetan al volver a abrir la aplicación.

La actualización de jornada completa agrega el fin 15:45 si no existía, calcula la cantidad de periodos y retira la configuración de traslados. Para docentes anteriores, `matricula_docente` se inicializa con la clave que ya tenían; puede corregirse sin romper sus asignaciones. La actualización genera una sola revisión y conserva el historial y los bloques existentes. Revalida o regenera los horarios antes de exportarlos.

## Pruebas

```powershell
.\venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\venv\Scripts\python.exe -m pytest -q
```

Las pruebas cubren asignación completa, agrupación, cupos hasta 35, jornada completa, receso, disponibilidad, choques con bloques diferentes, diagnósticos de restricciones imposibles, cambios manuales, migraciones, persistencia, concurrencia, lectura de Excel, exportación por carrera, conservación de pestañas y el recorrido de Streamlit con una base temporal.

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
