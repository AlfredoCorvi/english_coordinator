# Planeación de inglés

Aplicación local en **Streamlit**, con persistencia SQLite y asignación mediante **OR-Tools CP-SAT**. Reúne estudiantes de distintas carreras, forma grupos, asigna docentes y salones, audita las restricciones y exporta Excel y PDF.

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

## Servicios institucionales: fase 2

Los servicios nuevos son independientes de la aplicación actual y usan una base
relacional **separada**. Inicialización explícita:

```python
from ingles.relational_storage import RelationalStore
store = RelationalStore('data/institucional.sqlite3')
store.initialize()
```

`initialize()` rechaza una base con la tabla antigua `revisions`. No migra ni
modifica `data/ingles.sqlite3`. La base relacional debe tener periodos y una cuenta
de Secretaría provisionada por un administrador mediante un proceso confiable;
no existe registro público. Antes de usar las APIs, hay que acordar los campos
reales y un vínculo confiable entre el identificador del maestro y el sujeto
estable que devuelve el proveedor de identidad. No se deduce de un nombre.

Configura las variables `INGLES_ALUMNOS_URL` y `INGLES_MAESTROS_URL` con las URL
HTTPS completas suministradas para Mockaroo, incluidas sus claves. Mantén esos
valores fuera del repositorio. Opcionalmente, `INGLES_ALUMNOS_FIELDS` y `INGLES_MAESTROS_FIELDS`
son objetos JSON que mapean el nombre canónico al campo real del endpoint. Por
ejemplo, un fragmento de mapeo es `{"matricula":"matricula_api"}`. El mapeo
completo debe incluir:

- Alumnos: `id_externo`, `matricula`, `nombre`, `carrera_id`, `carrera`,
  `grupo_id`, `grupo`, `edificio`, `turno`, `estatus`.
- Maestros: `id_externo`, `nombre`, `tipo_contratacion`, `sujeto_identidad`.

Los identificadores deben ser estables y las matrículas deben llegar como texto
para preservar ceros. `sujeto_identidad` debe ser el sujeto verificado por el
proveedor de autenticación; si la API no lo proporciona, se necesita una fuente
de vinculación confiable antes de sincronizar maestros. El formato real de los
endpoints se verificó posteriormente; consulta la sección de fase 3.

`INGLES_ALUMNOS_COMPLETE` y `INGLES_MAESTROS_COMPLETE` son `false` por defecto.
Usa `true` solo cuando la fuente garantice que la respuesta no vacía es una
instantánea completa y configura `INGLES_ALUMNOS_EXPECTED_COUNT` o
`INGLES_MAESTROS_EXPECTED_COUNT` con el conteo positivo confirmado por la fuente.
El tamaño de la respuesta debe coincidir; en maestros esto permite desactivar los
ausentes. El conteo por sí solo no demuestra que los datos sean completos: debe
provenir de una fuente confiable y actualizarse para cada instantánea. Un lote vacío,
inválido o fallido se rechaza y no provoca bajas; un lote parcial no desactiva
maestros. Los alumnos se marcan activos o inactivos únicamente por su estatus
explícito y se conserva una instantánea por inscripción y periodo.

Para construir proveedores, usa `provider_from_environment('ALUMNOS')` o
`provider_from_environment('MAESTROS')` de `ingles.integrations`. Con una sesión
de Secretaría autenticada, `SyncService.sync_students(session, provider, period_id)`
y `sync_teachers(session, provider)` ejecutan las operaciones. La sincronización
valida permisos en el servicio, no en la pantalla.

`AuthService` requiere un proveedor que devuelva `Identity(provider, subject)`
tras verificar credenciales. `ConfigurableTestAuth` es exclusivamente para pruebas
ficticias; no es un servicio institucional ni debe usarse en producción. Las
sesiones actuales viven en memoria del proceso. Consulta la sección de fase 3
para conocer el portal de desarrollo y sus limitaciones.

Pruebas sin llamadas a la red:

```powershell
python -m unittest discover -s tests -p test_relational_storage.py -v
python -m unittest discover -s tests -p test_institutional_services.py -v
```

## Portal institucional de desarrollo: fase 3

El portal nuevo es `app_institucional.py`; `app.py` conserva la planeación antigua
y su base independiente. La aplicación antigua no tiene autenticación y no debe
exponerse como portal institucional. El portal nuevo no presenta su generación ni
sus editores como funciones integradas: usan datos y reglas anteriores.

En PowerShell, desde el proyecto, crea de forma explícita la primera cuenta de
Secretaría en una base nueva y configura credenciales **ficticias** en la sesión
local. El comando de alta solo acepta crear la primera Secretaría y no pide ni
guarda contraseñas:

```powershell
$env:INGLES_RELATIONAL_DB_PATH = 'data/institucional.sqlite3'
python -m ingles.bootstrap --db $env:INGLES_RELATIONAL_DB_PATH --subject secretaria.demo
$env:INGLES_DEV_AUTH = '{"secretaria":{"password":"clave-ficticia","subject":"secretaria.demo"},"docente":{"password":"otra-clave-ficticia","subject":"docente.demo"}}'
python -m streamlit run app_institucional.py
```

Inicia sesión con `secretaria` y `clave-ficticia`. En Periodos crea un periodo;
después, en Sincronización, selecciona los datos ficticios y sincroniza maestros
para dar de alta el docente de ejemplo. Cierra sesión y usa `docente` y
`otra-clave-ficticia`. Estos valores son solo ejemplos de desarrollo; el proveedor
de prueba mantiene las credenciales en memoria y no debe utilizarse en producción.
La sesión dura 30 minutos como máximo y se comprueba en cada operación del portal.
Al reiniciar el proceso se pierden las sesiones. Retira `INGLES_DEV_AUTH` del
entorno cuando termines; no lo guardes en el repositorio ni lo compartas.

Los endpoints documentados se consultaron y devolvieron listas con estos campos:
alumnos: `matricula`, `nombre`, `carrera`, `grupo_academico`, `edificio`, `turno`,
`estatus_escolar`, `nivel`; maestros: `numero_empleado`, `nombre`,
`tipo_contratacion`. Las matrículas y números de empleado recibidos eran enteros;
se convierten a texto y no es posible recuperar ceros iniciales no enviados por
la fuente. El campo `nivel` institucional no sobrescribe decisiones de inglés.

Para esos esquemas basta configurar `INGLES_ALUMNOS_URL` y `INGLES_MAESTROS_URL`
con las URL HTTPS completas facilitadas por la institución. El adaptador usa la
matrícula como identificador del alumno y, provisionalmente, los nombres de carrera
y la combinación carrera/grupo como identificadores de esos catálogos; cambios de
nombre pueden crear nuevas identidades y deben sustituirse por IDs institucionales
estables. Para maestros configura además `INGLES_MAESTROS_IDENTIDADES` como objeto
JSON que relacione cada número de empleado con el sujeto **previamente verificado**
por el proveedor de identidad. La API de maestros no proporciona ese sujeto y no
se supone que ambos identificadores coincidan. La sincronización rechaza registros
sin esa vinculación. Las variables `*_FIELDS` son opcionales para adaptar otros
esquemas; si se usan, deben incluir todos los campos canónicos indicados arriba.
Las claves de las URL deben permanecer fuera del código y de los registros.

Con Mockaroo, `*_COMPLETE` permanece en `false` salvo que exista confirmación de
un lote completo y se configure `*_EXPECTED_COUNT`. Los datos locales siempre se
importan como lote parcial. Los resultados y errores se muestran en el portal;
las consultas de docentes se limitan a sus grupos publicados y sus integrantes.
Todavía faltan la autenticación institucional real y la gestión de sesiones apta
para despliegue compartido.

## Funcionalidades académicas: fase 4

Reinicia el portal tras actualizar el código para incorporar las tablas nuevas a
la base relacional existente. Como Secretaría, crea el cuatrimestre actual y el
siguiente, sincroniza alumnos y docentes y abre **Alumnos**. Allí puedes consultar
y filtrar registros, registrar el nivel inicial cuando falte y autorizar de forma
explícita a un docente para un alumno y cuatrimestre. También se autoriza la
consulta de alumnos de grupos publicados asignados al docente. Revocar un permiso
explícito no elimina el acceso que provenga de un grupo publicado.

Como docente, abre **Alumnos**, selecciona el cuatrimestre actual y el periodo
destino, revisa el nivel sugerido y guarda el próximo nivel. El destino debe ser
el siguiente periodo configurado y no tener un plan publicado. El historial de
decisiones se conserva; no se requieren grupos del periodo destino. Secretaría
puede registrar únicamente el nivel inicial ausente del periodo actual.

En **Bloques horarios**, agrega manualmente los intervalos institucionales ya
confirmados. Cada uno debe durar 45 minutos y respetar la jornada y el receso.
Selecciona siete intervalos, como máximo dos por día, y guarda una versión del
bloque para el periodo. También puedes crear manualmente bloques adicionales;
las versiones anteriores se conservan. En **Docentes** puedes definir la
participación, límites y disponibilidad, y consultar la carga y horarios restantes.
En **Configuración del algoritmo** puedes guardar cupos y tiempo de búsqueda por
periodo respetando el mínimo de 8 y máximo de 35; las demás reglas obligatorias
siguen vigentes y las propuestas anteriores conservan su configuración.

En **Incidencias**, un docente puede solicitar un cambio de nivel para un alumno
autorizado y Secretaría puede aprobarlo o rechazarlo. Si el alumno no pertenece a
un grupo publicado, aprobar actualiza su nivel y conserva el historial. Si pertenece
a uno, el cambio queda pendiente de aplicación hasta validar y publicar una
versión con el movimiento.
El catálogo **Niveles** es informativo y marca Advance 1 y Advance 2 como exentos.

## Generación relacional: fase 5

La generación se puede invocar desde Python con una sesión válida de Secretaría.
El método `generate` toma una instantánea de la base relacional y devuelve la
propuesta en memoria sin guardarla ni publicarla:

```python
from ingles.planning_service import PlanningService

# store es RelationalStore, auth es AuthService y session procede de auth.login(...)
result = PlanningService(store, auth).generate(session, period_id=1)
print(result['status'], result['message'])
print(result['groups'], result['assignments'], result['pending'])
```

Debe existir al menos un bloque activo válido para el periodo. Configura sus
siete intervalos, docentes participantes, disponibilidad, inscripciones y niveles
en el portal. Si no existe una fila de configuración para el periodo, se usan
8, 28, 35 y 30 segundos como valores iniciales. Una configuración existente no
puede reducir el mínimo de 8 ni superar el máximo de 35.

Los resultados `OPTIMAL`, `FEASIBLE`, `NO_ASSIGNMENTS`, `INFEASIBLE` y `TIMEOUT`
distinguen el estado de búsqueda. `proven_stages` muestra las prioridades cuya
optimalidad se demostró; `FEASIBLE` no garantiza todas ellas. `pending` distingue
alumnos sin nivel de alumnos elegibles sin asignación, y `exempt` enumera los
exentos. La propuesta se verifica con un auditor independiente antes de
entregarla. Los alumnos inactivos no forman parte de la entrada.

La base todavía no registra disponibilidad individual ni horarios regulares de
los alumnos: la compatibilidad modelada es el bloque común de cada grupo
académico. El método `generate` descrito arriba sigue devolviendo una propuesta
sin guardarla; el portal de la fase 6 utiliza `generate_and_save`.

## Propuestas y publicación: fase 6

Reinicia `app_institucional.py` después de actualizar para que se creen las tablas
adicionales; las tablas existentes y las publicaciones anteriores se conservan.
Con una cuenta de Secretaría y los datos académicos ya configurados:

1. En **Generación de grupos**, elige el periodo y revisa alumnos, pendientes de
   nivel, exentos, docentes y bloques. Pulsa **Generar y guardar propuesta**.
2. En **Grupos de inglés**, selecciona la versión; filtra los grupos y abre uno
   para ver sus integrantes. Los cambios de docente, bloque o alumno se validan
   y crean otra versión, con motivo, sin editar la versión de origen.
3. En **Historial y versiones**, compara dos versiones y consulta los eventos y
   movimientos académicos. La comparación usa las asignaciones reales, no el
   nombre generado del grupo.
4. En **Grupos de inglés → Publicar propuesta**, revisa la organización y confirma
   la publicación. Si hay pendientes, revisa sus motivos y marca también la
   confirmación de publicación parcial. La sustitución de una publicación es
   transaccional; si cambió la versión oficial que revisaste, actualiza su estado
   y revisa de nuevo antes de confirmar.
5. Para una incidencia aprobada y pendiente, selecciona la versión y usa
   **Preparar aplicación de incidencia aprobada**. La incidencia solo se marca
   aplicada cuando se publica la versión resultante. Si el nivel es exento, se
   valida la salida del alumno del grupo en lugar de asignarle otro.

La generación de alternativas excluye las organizaciones ya registradas por sus
alumnos, docentes y bloques, manteniendo al menos la mejor cobertura previa cuando
los datos de entrada no han cambiado. Si se agota el tiempo, el sistema no afirma
que no haya alternativas. Una propuesta puede dejar de ser publicable cuando se
modifiquen los datos que usó; en ese caso hay que generar una nueva. La auditoría
impide guardar o publicar asignaciones inválidas. No se generan horarios, salones
ni materias; tampoco se modifican automáticamente las publicaciones oficiales.

Las cuentas de desarrollo y las sesiones del portal siguen siendo simuladas. Antes
de un despliegue compartido se necesita integrar el proveedor institucional real
y una gestión de sesiones adecuada. El optimizador de alternativas introduce
variables por alumno; es necesario medir tiempos y recursos con la matrícula real.

## Escenario y reportes: fase 7

Para una demostración aislada, abre PowerShell en el directorio del proyecto y
prepara **una base nueva y separada**. El alta de Secretaría se ejecuta solo la
primera vez; no la repitas al reutilizar esa base:

```powershell
$env:INGLES_RELATIONAL_DB_PATH = Join-Path (Get-Location) 'data\demo_ingles.sqlite3'
$env:INGLES_DEMO_DB_PATH = $env:INGLES_RELATIONAL_DB_PATH
$env:INGLES_DEMO_MODE = '1'
python -m ingles.bootstrap --db $env:INGLES_RELATIONAL_DB_PATH --subject secretaria.demo

$credencialesDemo = @{secretaria = @{password='ficticia-demo'; subject='secretaria.demo'}}
for ($i = 1; $i -le 12; $i++) {
    $usuarioDemo = 'docente{0:D2}' -f $i
    $sujetoDemo = if ($i -eq 1) { 'docente.demo' } else { 'docente.demo.{0:D2}' -f $i }
    $credencialesDemo[$usuarioDemo] = @{password='ficticia-demo'; subject=$sujetoDemo}
}
$env:INGLES_DEV_AUTH = $credencialesDemo | ConvertTo-Json -Compress
python -m streamlit run app_institucional.py
```

Entra como `secretaria` / `ficticia-demo` y pulsa **Cargar escenario de
demostración** en el panel. La carga crea los periodos y configura datos y
horarios **ficticios**: 200 alumnos, 12 docentes, cuatro carreras, diez grupos
académicos y cinco bloques. Una segunda carga no altera el escenario. Por seguridad
se rechaza una base que ya contenga datos académicos y no tenga el marcador del
escenario. No utilices esta base para datos institucionales reales.
El servicio rechaza sincronizaciones institucionales en una base marcada como
demostración; cambia primero a una base institucional separada.

En **Generación de grupos** selecciona `DEMO-SEP-DIC-2026`; genera y revisa una
propuesta y después solicita una alternativa. La búsqueda puede tardar hasta 60
segundos y un resultado `FEASIBLE` no demuestra todas las prioridades óptimas.
En **Grupos de inglés** revisa y modifica una versión; compárala en **Historial y
versiones** y publica con las confirmaciones necesarias. Para entrar como uno de
los docentes asignados, usa `docente01` a `docente12` según el número mostrado
en el grupo y la contraseña ficticia `ficticia-demo`. En **Alumnos** selecciona
el periodo actual y `DEMO-ENE-ABR-2027` para registrar el próximo nivel; en
**Incidencias** puedes solicitar un cambio y resolverlo como Secretaría.

En **Reportes**, selecciona periodo, versión y tipo: cada uno se descarga por
separado en Excel y PDF. La versión y su estado aparecen en ambos archivos.
Los reportes se basan en la instantánea histórica del plan. Las versiones nuevas
conservan también las inscripciones inactivas para el reporte por grupo académico;
las versiones creadas antes de la fase 7 indican cuando no tienen esa instantánea.
El reporte de conflictos de una publicación también comprueba los datos actuales.

Para volver a usar la base institucional, cierra Streamlit, elimina las variables
de demostración de esa sesión y configura `INGLES_RELATIONAL_DB_PATH` con la ruta
institucional correspondiente. Las credenciales anteriores son ficticias y solo
se usan en memoria durante el desarrollo.

### Configuración de Mockaroo en PowerShell

En la misma terminal desde la que iniciarás Streamlit, proporciona las URL HTTPS
completas del documento sin guardarlas en archivos del proyecto:

```powershell
$alumnosUrlSegura = Read-Host 'URL completa de la API de alumnos' -AsSecureString
$maestrosUrlSegura = Read-Host 'URL completa de la API de maestros' -AsSecureString
$env:INGLES_ALUMNOS_URL = [System.Net.NetworkCredential]::new('', $alumnosUrlSegura).Password
$env:INGLES_MAESTROS_URL = [System.Net.NetworkCredential]::new('', $maestrosUrlSegura).Password
$env:INGLES_MAESTROS_IDENTIDADES = '{"NUMERO_EMPLEADO":"SUJETO_VERIFICADO"}'
$env:INGLES_ALUMNOS_COMPLETE = 'false'
$env:INGLES_MAESTROS_COMPLETE = 'false'
python -m streamlit run app_institucional.py
```

Sustituye el mapa de ejemplo por todos los números y sujetos efectivamente
verificados. No se infiere identidad a partir del número de empleado. Las URL
contienen claves y deben mantenerse privadas; configurarlas en otra terminal no
modifica el proceso de Streamlit ya iniciado. Con `COMPLETE=false` no se dan de
baja docentes ausentes. Solo cambia a `true` y configura el `EXPECTED_COUNT`
correspondiente si la fuente confirma una instantánea completa y su conteo.

La matriz de cobertura por caso está en [docs/matriz_cobertura_fase7.md](docs/matriz_cobertura_fase7.md).
