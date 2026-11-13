# Casos de uso — Sistema de planeación de inglés

Este documento describe el comportamiento de la versión actual del proyecto. Está orientado a la coordinadora que prepara los horarios de inglés antes de que se elaboren los horarios de las materias regulares.

## Alcance y actores

**Actor principal: coordinadora de inglés.** Carga y mantiene la información, configura la planeación, genera propuestas, revisa conflictos y descarga resultados. Las referencias a este actor describen su responsabilidad operativa; la aplicación local todavía no implementa cuentas ni permisos por rol.

**Personas involucradas:** los docentes proporcionan su disponibilidad y reciben sus asignaciones; los alumnos reciben su grupo y horario. En esta versión no interactúan directamente con el sistema. El personal que elabora las materias regulares utiliza las reservas de horario exportadas.

**Dentro del alcance:** catálogos de alumnos, docentes y salones; configuración de bloques; asignación automática; auditoría; ajustes manuales; persistencia e historial; exportación a Excel y PDF.

**Fuera del alcance actual:** autenticación, inscripción realizada por alumnos, notificaciones, aprobación por firmas, generación de materias regulares, control de asistencia y restauración de catálogos históricos desde la interfaz.

## Conceptos y reglas de negocio

| ID | Regla |
| --- | --- |
| RN-01 | Un grupo de carrera se identifica por la combinación **Carrera + Grupo**. Por ejemplo, Ingeniería / 1A es distinto de Administración / 1A. |
| RN-02 | Todos los alumnos del mismo grupo de carrera deben tener inglés en el **mismo bloque semanal**, con los mismos días y horas. Pueden distribuirse entre distintos grupos de inglés según su nivel. Esta regla es obligatoria. |
| RN-03 | Cada alumno debe tener exactamente una asignación a un grupo de inglés. |
| RN-04 | Cada grupo de inglés tiene un nivel de agrupación, un bloque, un docente y un salón fijo. Varios grupos de inglés pueden compartir un bloque con recursos distintos. |
| RN-05 | Cada bloque contiene exactamente siete periodos de duración configurable, inicialmente 45 minutos, de lunes a viernes. Con ese valor son 315 minutos o 5 horas y 15 minutos de clase efectiva. |
| RN-06 | La agrupación inicial es por familias A, B y C. También se puede configurar por nivel MCER individual o por curso exacto. El nivel original de cada alumno se conserva. |
| RN-07 | El máximo por grupo se configura entre 25 y 35 alumnos y no puede exceder la capacidad del salón. El mínimo inicial es 1; los grupos menores de 25 generan avisos. |
| RN-08 | Los docentes pueden impartir cualquier nivel, respetando disponibilidad, horas máximas semanales de reloj y edificios permitidos. La carga se calcula en minutos efectivos de clase, sin receso. No se exige un periodo libre para cambiar de edificio. |
| RN-09 | Un docente o salón no puede atender dos grupos simultáneos. Se comparan los días y periodos reales, aunque los bloques tengan nombres diferentes. |
| RN-10 | Los edificios disponibles son 1, 2, 3, 4 e Idiomas. El edificio del alumno es una preferencia, salvo que se active la obligación de permanecer en él. |
| RN-11 | Un bloque fijo indicado para un alumno reserva ese bloque para todo su grupo de carrera. Las reservas contradictorias dentro del mismo grupo impiden generar una propuesta. |
| RN-12 | Una propuesta debe incluir a todos los alumnos y superar la auditoría antes de guardarse desde la interfaz. Para exportarla, además debe corresponder a la revisión vigente de los datos. |
| RN-13 | Las importaciones se revisan antes de guardarse. Los cambios en catálogos o reglas crean una revisión; las generaciones y ajustes manuales aceptados crean versiones de horario. |
| RN-14 | El receso es configurable y por defecto va de 11:30 a 11:55 todos los días. No admite clases. Un periodo que lo invada se desplaza completo al final del receso; no se acorta ni se divide. |
| RN-15 | El inicio y fin de jornada determinan automáticamente los periodos completos disponibles antes y después del receso. El fin predeterminado es 15:45. La asignación puede utilizar los últimos periodos, siempre dentro de los bloques guardados. |

Equivalencias utilizadas:

| Cursos | Nivel MCER | Familia |
| --- | --- | --- |
| Prebasic y Basic 1 | A1 | A |
| Basic 2 y Basic 3 | A2 | A |
| Intermediate 1 y 2 | B1 | B |
| Intermediate 3 y 4 | B2 | B |
| Advanced 1 | C1 | C |

## Catálogo de casos de uso

El actor principal de todos los casos es la coordinadora de inglés.

| ID | Caso de uso | Sección |
| --- | --- | --- |
| CU-01 | Importar alumnos desde Excel | Datos → Alumnos |
| CU-02 | Importar docentes desde Excel | Datos → Docentes |
| CU-03 | Administrar salones | Datos → Salones |
| CU-04 | Definir bloques semanales | Bloques y reglas → Bloques semanales |
| CU-05 | Configurar reglas de asignación | Bloques y reglas → Reglas de asignación |
| CU-06 | Generar grupos y horarios automáticamente | Generar |
| CU-07 | Consultar resultados por grupo de inglés | Resultados → Por grupo de inglés |
| CU-08 | Auditar una propuesta de horario | Auditoría |
| CU-09 | Ajustar manualmente una propuesta | Resultados → Ajustes manuales |
| CU-10 | Actualizar datos guardados | Datos |
| CU-11 | Exportar resultados a Excel | Resultados → Exportar |
| CU-12 | Exportar el reporte PDF | Resultados → Exportar |
| CU-13 | Consultar versiones anteriores | Resultados / Auditoría |
| CU-14 | Consultar reservas para las materias regulares | Auditoría → Reservas para carreras |

## CU-01. Importar alumnos desde Excel

**Objetivo:** incorporar el padrón de alumnos que necesita recibir clases de inglés.

**Precondiciones:** la aplicación está disponible y la coordinadora dispone de un archivo `.xlsx` con los datos de los alumnos.

**Disparador:** la coordinadora abre **Datos → Alumnos** y selecciona un archivo.

**Flujo principal:**

1. El sistema presenta las hojas del archivo y permite elegir una.
2. La coordinadora relaciona las columnas con Matricula, Nombre, Grupo, Carrera, Edificio, Nivel y, opcionalmente, Bloque fijo.
3. Selecciona si desea agregar y actualizar por matrícula o reemplazar el padrón.
4. Pulsa **Llevar a revisión**.
5. El sistema presenta los registros en una tabla editable sin modificar todavía la base de datos.
6. La coordinadora corrige los datos y pulsa **Validar y guardar**.
7. El sistema valida la tabla y guarda una nueva revisión del padrón.

**Alternativas y excepciones:** un archivo inválido, fórmulas en las celdas o encabezados ambiguos impiden la lectura. Las matrículas repetidas impiden combinar la importación. Los campos obligatorios vacíos, niveles desconocidos o edificios inválidos impiden guardar. La coordinadora puede corregirlos o descartar los cambios.

**Postcondición:** el padrón queda persistido, conservando las matrículas como texto y los niveles originales. Las referencias a bloques fijos y su compatibilidad entre compañeros se verifican al validar el conjunto de datos antes de generar.

**Reglas relacionadas:** RN-01, RN-06, RN-10, RN-11 y RN-13.

## CU-02. Importar docentes desde Excel

**Objetivo:** registrar a los docentes y los recursos de tiempo que pueden dedicar a inglés.

**Precondiciones:** existe un archivo `.xlsx` con matricula_docente, nombre, edificios permitidos, horas máximas y disponibilidad de lunes a viernes.

**Disparador:** la coordinadora selecciona un archivo en **Datos → Docentes**.

**Flujo principal:**

1. Selecciona la hoja y relaciona sus columnas con los campos del sistema.
2. Elige agregar y actualizar por matricula_docente o reemplazar el catálogo. Las claves internas se conservan sin mostrarlas.
3. Lleva los registros a revisión.
4. Revisa edificios, carga semanal disponible para inglés y periodos de cada día.
5. Corrige los datos y pulsa **Validar y guardar**.
6. El sistema valida los registros y crea una nueva revisión. Conserva la pestaña Docentes y muestra una notificación superior durante cuatro segundos.

**Alternativas y excepciones:** se rechazan identificadores duplicados, horas máximas no válidas, edificios desconocidos o disponibilidad mal formada. Un día vacío significa que el docente no está disponible; `*` significa toda la jornada. Si faltan horarios reales, la coordinadora debe completarlos antes de guardar.

**Postcondición:** los docentes quedan disponibles para la planeación. Su registro no implica que ya tengan un grupo asignado.

**Reglas relacionadas:** RN-08, RN-10 y RN-13.

## CU-03. Administrar salones

**Objetivo:** disponer de un catálogo de espacios utilizables para las clases de inglés.

**Precondiciones:** se conocen el edificio, número de salón, capacidad y disponibilidad de cada espacio.

**Disparador:** la coordinadora abre **Datos → Salones**.

**Flujo principal:**

1. Agrega registros manualmente o importa un Excel y lo lleva a revisión.
2. Identifica cada salón por su edificio y número; la clave interna se genera automáticamente y no se muestra.
3. Registra su número, edificio, capacidad y periodos disponibles por día.
4. Pulsa **Validar y guardar**.
5. El sistema valida y guarda el catálogo como una nueva revisión. Conserva la pestaña Salones y muestra una notificación superior durante cuatro segundos.

**Alternativas y excepciones:** no se admite registrar dos veces el mismo salón dentro de un edificio. El salón 101 del edificio 1 y el salón 101 del edificio 2 son espacios distintos. Se rechazan capacidades no positivas y periodos inválidos.

**Postcondición:** los espacios guardados pueden utilizarse en la generación. Si se modifica un salón utilizado por una propuesta anterior, esta deberá revalidarse o regenerarse.

**Reglas relacionadas:** RN-04, RN-07, RN-09, RN-10 y RN-13.

## CU-04. Definir bloques semanales

**Objetivo:** establecer las alternativas de horario entre las que podrá elegir el sistema.

**Precondiciones:** la jornada y el número de periodos diarios están definidos.

**Disparador:** la coordinadora abre **Bloques y reglas → Bloques semanales**.

**Flujo principal:**

1. Crea un bloque con un nombre único.
2. Indica los periodos de clase de cada día de lunes a viernes.
3. Revisa que la distribución corresponda al horario deseado.
4. Pulsa **Validar y guardar**.
5. El sistema verifica que cada bloque tenga exactamente siete periodos válidos y guarda una nueva revisión.

**Alternativas y excepciones:** puede importar bloques desde Excel o usar **Proponer bloques sin superposición**, editar la propuesta y guardarla. Las plantillas aprovechan toda la jornada, incluidos los últimos periodos. Ampliar la jornada no altera bloques guardados: deben editarse o proponerse nuevamente. Un bloque con seis u ocho periodos, periodos repetidos dentro de un día o fuera de la jornada se rechaza. Los bloques definidos manualmente pueden solaparse; los conflictos de recursos se evitan al asignar grupos.

**Postcondición:** los bloques quedan disponibles para la generación. Definir un bloque no asigna todavía alumnos, docentes ni salones.

**Reglas relacionadas:** RN-02, RN-04, RN-05 y RN-09.

## CU-05. Configurar reglas de asignación

**Objetivo:** adaptar la planeación a los criterios académicos y a las restricciones operativas.

**Precondición:** la coordinadora conoce el criterio de agrupación y los límites de operación.

**Disparador:** abre **Bloques y reglas → Reglas de asignación**.

**Flujo principal:**

1. Selecciona agrupación por familia, nivel MCER o curso exacto.
2. Define cupo máximo entre 25 y 35 y el mínimo permitido por grupo.
3. Configura inicio y fin de jornada (fin predeterminado 15:45), duración de cada periodo e inicio y fin del receso. La cantidad de periodos se calcula automáticamente.
4. Define si los alumnos deben permanecer en su edificio. No existe un campo de periodos libres para traslado.
5. Establece el tiempo máximo de búsqueda.
6. Pulsa **Guardar reglas**; el sistema valida los valores y crea una nueva revisión.

**Alternativas y excepciones:** un mínimo superior al máximo, una duración inválida, un receso o jornada cuyo fin no sea posterior al inicio o una jornada sin un periodo completo disponible impiden guardar. El horario común por grupo de carrera no puede desactivarse. Al cambiar duración, jornada o receso se recalculan los periodos; la coordinadora debe revisar disponibilidades y bloques, y revalidar los horarios anteriores.

**Postcondición:** la siguiente generación y auditoría utilizarán las reglas guardadas. La tabla Jornada guardada muestra los periodos y el receso no asignable cuando está dentro de la jornada.

**Reglas relacionadas:** RN-02, RN-05 a RN-10 y RN-14.

## CU-06. Generar grupos y horarios automáticamente

**Objetivo:** obtener una propuesta completa y compatible con las restricciones.

**Precondiciones:** hay alumnos, docentes, salones y bloques guardados; el conjunto de datos supera la validación previa.

**Disparador:** la coordinadora pulsa **Generar propuesta**.

**Flujo principal:**

1. El sistema revisa los datos y la compatibilidad de las reservas de bloque.
2. Busca un bloque común para cada combinación Carrera + Grupo.
3. Distribuye a los alumnos entre grupos de inglés compatibles con su nivel de agrupación y los cupos disponibles.
4. Asigna un docente y un salón a cada grupo, respetando disponibilidad, edificios, carga efectiva en minutos y ausencia de superposiciones. Las horas reales excluyen el receso y respetan el fin de jornada.
5. Busca minimizar primero la cantidad de grupos y después los alumnos asignados fuera de su edificio de origen.
6. Ejecuta una auditoría independiente sobre la propuesta obtenida.
7. Si la propuesta está completa y no tiene errores, guarda una nueva versión y abre **Resultados**.

**Alternativas y excepciones:**

- Si faltan datos o hay bloques fijos contradictorios dentro de un grupo de carrera, la coordinadora debe corregirlos antes de iniciar la búsqueda.
- Si las restricciones hacen imposible una asignación, muestra los impedimentos detectados, cantidades y grupos afectados, sugerencias de corrección y botones a las pestañas correspondientes. Los conflictos entre varias condiciones se describen como un conjunto incompatible. No guarda un horario parcial.
- Si se agota el tiempo sin encontrar una solución, informa que la búsqueda es inconclusa; no lo presenta como una imposibilidad demostrada.
- Si encuentra una solución válida sin demostrar que sea óptima, puede guardarla e indica esa diferencia.
- Si la auditoría detecta errores o los datos cambian en otra sesión antes de guardar, la propuesta no se guarda.

**Postcondición:** existe una versión completa y auditada vinculada con la revisión de datos utilizada. Los horarios anteriores se conservan.

**Reglas relacionadas:** RN-01 a RN-15.

**Ejemplo:** Ingeniería / 1A tiene alumnos de familias A, B y C. El sistema puede distribuirlos en tres grupos de inglés diferentes, todos dentro del mismo bloque. Para atenderlos simultáneamente necesita docentes y salones compatibles para esos tres grupos. Si esos recursos no existen, no puede resolverlo enviando a parte de Ingeniería / 1A a otro bloque.

## CU-07. Consultar resultados por grupo de inglés

**Objetivo:** revisar la composición y los recursos asignados a cada grupo.

**Precondición:** existe al menos una versión de horario guardada.

**Disparador:** la coordinadora abre **Resultados → Por grupo de inglés**.

**Flujo principal:**

1. Selecciona una versión de horario.
2. El sistema la audita contra los datos actuales y muestra si está desactualizada.
3. Si no hay errores, presenta el resumen de grupos, niveles, bloques, docentes, salones, edificios y cupos.
4. La coordinadora selecciona un grupo de inglés o consulta todos.
5. Revisa su listado de alumnos y, al seleccionar un grupo, su horario semanal.

**Alternativas y excepciones:** si todavía no hay versiones, el sistema ofrece ir a generar. Si la versión tiene errores con los datos actuales, muestra los problemas y remite a su corrección. Si está desactualizada pero no tiene errores, puede consultarse con esa advertencia.

**Postcondición:** la coordinadora ha consultado la propuesta; esta operación no modifica las asignaciones.

**Reglas relacionadas:** RN-03, RN-04, RN-06 y RN-12.

## CU-08. Auditar una propuesta de horario

**Objetivo:** comprobar que la propuesta cumple las restricciones y detectar asuntos que necesitan atención.

**Precondición:** existe una versión de horario.

**Disparador:** la coordinadora abre **Auditoría** y selecciona una versión.

**Flujo principal:**

1. El sistema revisa los datos de entrada y las referencias de las asignaciones.
2. Comprueba cobertura de alumnos, compatibilidad de niveles, cupos y duración de bloques.
3. Verifica el horario común para cada grupo de carrera y el cumplimiento de bloques fijos.
4. Revisa choques, disponibilidades, edificios, carga docente efectiva, límites de jornada y que ninguna clase invada el receso.
5. Presenta los errores y avisos encontrados.
6. Si no hay errores, permite revisar visualmente la semana por docente, salón, bloque, grupo de inglés o grupo de carrera, las cargas y las comprobaciones. Para un grupo de carrera, se seleccionan carrera y grupo por separado; el calendario muestra el horario común y únicamente los grupos de inglés que contienen alumnos de ese grupo de carrera.

**Alternativas y excepciones:** los errores impiden exportar y requieren corrección. Un aviso, como un grupo pequeño que respeta el mínimo configurado, no invalida por sí mismo la propuesta. Una versión desactualizada requiere revalidación o regeneración aunque no tenga errores.

**Postcondición:** se conoce el estado de la propuesta frente a los datos actuales; la auditoría no reasigna alumnos automáticamente.

**Reglas relacionadas:** RN-01 a RN-12 y RN-14.

## CU-09. Ajustar manualmente una propuesta

**Objetivo:** corregir o reorganizar una asignación conservando todas las reglas obligatorias.

**Precondición:** existe una versión de horario que se desea modificar o revalidar.

**Disparador:** la coordinadora abre **Resultados → Ajustes manuales**.

**Flujo principal:**

1. Selecciona la versión que utilizará como base.
2. Modifica grupos de inglés, niveles de agrupación, bloques, docentes o salones.
3. Ajusta la relación entre matrículas y grupos de inglés cuando sea necesario.
4. Pulsa **Auditar y guardar nueva versión**.
5. El sistema comprueba la propuesta completa contra los datos actuales.
6. Si no hay errores y la revisión sigue vigente, guarda una nueva versión y conserva la anterior.

**Alternativas y excepciones:** se rechaza un cambio que separe el horario de compañeros del mismo grupo de carrera, provoque un choque, exceda un cupo, cambie un alumno a un nivel incompatible o deje matrículas sin asignar o duplicadas. Para incorporar alumnos nuevos, primero debe actualizarse el padrón. Si solo se necesita revalidar una versión, puede guardarse después de auditarla sin cambiar sus asignaciones, siempre que cumpla las reglas actuales.

**Postcondición:** existe una nueva versión válida, o se conservan los datos guardados y se muestran los conflictos que deben corregirse.

**Reglas relacionadas:** RN-01 a RN-13.

## CU-10. Actualizar datos guardados

**Objetivo:** mantener los catálogos sin tener que reconstruir toda la información desde cero.

**Precondición:** existe información guardada de alumnos, docentes o salones.

**Disparador:** la coordinadora abre la tabla correspondiente en **Datos**.

**Flujo principal:**

1. Consulta los registros existentes.
2. Agrega, edita o elimina filas, o importa un archivo para actualizar por identificador.
3. Pulsa **Validar y guardar**.
4. El sistema valida la tabla y guarda una nueva revisión.
5. Los horarios ligados a revisiones anteriores quedan pendientes de revalidación o regeneración antes de exportar.

**Alternativas y excepciones:** los registros inválidos no se guardan. **Descartar cambios sin guardar** recupera los datos persistidos. Si otra sesión guardó una revisión posterior, el sistema rechaza el intento de sobrescribirla y pide recargar. Los cambios de catálogos no reparan ni reasignan automáticamente los horarios existentes.

**Postcondición:** el catálogo actualizado permanece disponible al volver a abrir la aplicación; se conserva el historial de revisiones y propuestas.

**Reglas relacionadas:** RN-12 y RN-13.

## CU-11. Exportar resultados a Excel

**Objetivo:** obtener listados y horarios para su revisión, distribución o impresión.

**Precondiciones:** la versión seleccionada corresponde a los datos vigentes y no tiene errores de auditoría.

**Disparador:** la coordinadora abre **Resultados → Exportar**.

**Flujo principal:**

1. Pulsa **Preparar Excel y PDF**.
2. El sistema vuelve a auditar la propuesta y prepara los archivos.
3. La coordinadora pulsa **Descargar Excel**.
4. Obtiene un libro con el listado general, resúmenes, horarios con horas reales, jornada con receso no asignable, carga docente en horas de reloj, auditoría, reservas para carreras y una hoja por grupo de inglés.
5. También puede pulsar **Descargar Excel por grupos de carrera**. Obtiene otro libro con una hoja por Carrera + Grupo, título, horario común y las ocho columnas del listado, conservando el nivel y la asignación de cada alumno. Las hojas están preparadas para imprimir en horizontal y repetir encabezados.

**Alternativas y excepciones:** si hay errores o la versión está desactualizada, la descarga no se habilita; debe corregirse y guardarse una versión vigente. La generación del archivo no implica enviarlo a docentes ni imprimirlo automáticamente.

**Postcondición:** la coordinadora dispone del archivo descargado; las asignaciones no cambian.

**Columnas del listado principal, en este orden:**

`Matricula | Nombre | Grupo | Nombre de materia | Grupo Inglés | Nivel de inglés | Docente | Salón`

**Grupo** es el grupo de carrera; **Nombre de materia** corresponde al bloque; **Salón** incluye el edificio. La matrícula conserva sus ceros iniciales.

**Reglas relacionadas:** RN-02, RN-06 y RN-12.

## CU-12. Exportar el reporte PDF

**Objetivo:** obtener un reporte legible de la propuesta de horario.

**Precondiciones:** la propuesta seleccionada está vigente y no tiene errores de auditoría.

**Disparador:** la coordinadora abre **Resultados → Exportar**.

**Flujo principal:**

1. Pulsa **Preparar Excel y PDF**, si aún no ha preparado los archivos de esa versión.
2. El sistema audita y prepara el reporte con resumen, duración de periodos, receso, carga docente en horas de reloj, avisos, calendarios por bloque y listas de alumnos por grupo de inglés.
3. La coordinadora pulsa **Descargar reporte PDF**.
4. Obtiene el archivo correspondiente a la versión seleccionada.

**Alternativas y excepciones:** una propuesta con errores o basada en datos anteriores no puede exportarse. Los avisos permitidos se incluyen en el reporte para revisión de la coordinadora.

**Postcondición:** el reporte queda descargado y el horario guardado permanece sin cambios.

**Reglas relacionadas:** RN-04, RN-06 y RN-12.

## CU-13. Consultar versiones anteriores

**Objetivo:** revisar propuestas previas sin sobrescribir la planeación actual.

**Precondición:** existe al menos una versión guardada; para elegir una anterior deben existir varias.

**Disparador:** la coordinadora utiliza el selector **Versión del horario** en Resultados o Auditoría.

**Flujo principal:**

1. El sistema muestra las versiones disponibles con su identificador, descripción y revisión de datos asociada.
2. La coordinadora selecciona una versión.
3. El sistema recupera sus asignaciones y las evalúa contra los catálogos y reglas actuales.
4. Muestra sus resultados o los conflictos encontrados, junto con la advertencia de desactualización cuando corresponde.
5. Si desea utilizarla de nuevo, la coordinadora la ajusta o revalida mediante CU-09, o genera otra propuesta mediante CU-06.

**Alternativas y excepciones:** seleccionar una versión no restaura los catálogos de la fecha en que se creó. Las versiones antiguas siguen sujetas al horario común obligatorio por grupo de carrera. Al actualizar una base que conservaba esa regla como opcional, se crea una nueva revisión sin borrar el historial.

**Postcondición:** la versión consultada permanece intacta. Cualquier ajuste aceptado produce otra versión.

**Reglas relacionadas:** RN-02, RN-12 y RN-13.

## CU-14. Consultar reservas para las materias regulares

**Objetivo:** identificar las horas de inglés que deben quedar libres al elaborar el horario regular de cada grupo de carrera.

**Precondición:** existe una propuesta que supera la auditoría; para usarla como resultado vigente también debe corresponder a la revisión actual.

**Disparador:** la coordinadora abre **Auditoría → Reservas para carreras**.

**Flujo principal:**

1. Selecciona la versión que desea revisar.
2. El sistema reúne los días y periodos de inglés por combinación Carrera + Grupo.
3. Presenta los siete periodos compartidos por todos los alumnos de cada grupo de carrera, con sus horas reales y sin duplicarlos por cada grupo de inglés.
4. La coordinadora consulta la tabla o descarga el Excel mediante CU-11 para utilizarla al preparar las materias regulares.

**Alternativas y excepciones:** si la propuesta tiene errores, primero debe corregirse. Si está desactualizada, debe revalidarse antes de exportar. El sistema no compara estas reservas con horarios regulares externos ni genera automáticamente esas materias.

**Postcondición:** están identificadas las horas reservadas para inglés por grupo de carrera.

**Reglas relacionadas:** RN-01, RN-02, RN-05 y RN-12.

## Relaciones entre casos de uso

- CU-01 a CU-05 preparan los datos y restricciones utilizados por CU-06.
- CU-06 y CU-09 incluyen la comprobación independiente descrita en CU-08 antes de guardar una propuesta.
- CU-07, CU-08 y CU-14 permiten revisar una versión; CU-13 permite seleccionar versiones anteriores para esas revisiones.
- CU-10 puede hacer necesaria una nueva generación mediante CU-06 o una revalidación mediante CU-09.
- CU-11 y CU-12 requieren una propuesta vigente y sin errores; la preparación de sus archivos vuelve a ejecutar la auditoría.

## Criterios de aceptación transversales

| Escenario | Resultado esperado |
| --- | --- |
| Alumnos de Ingeniería / 1A tienen niveles A, B y C. | Se asignan a grupos de inglés compatibles y todos comparten un solo bloque. |
| Ingeniería / 1A y Administración / 1A necesitan horarios distintos. | Pueden recibir bloques diferentes porque pertenecen a grupos de carrera distintos. |
| Dos compañeros del mismo grupo de carrera tienen reservas en bloques distintos. | La validación informa la contradicción y no inicia la generación. |
| No existen suficientes docentes o salones simultáneos para atender los niveles de un grupo de carrera. | No se separan los horarios de sus compañeros para eludir la restricción; se informa la falta de una solución cuando se demuestra. |
| Una edición manual cambia de bloque a parte de un grupo de carrera. | La auditoría impide guardar y exportar esa propuesta. |
| Dos bloques con nombres distintos usan al mismo docente o salón en el mismo periodo. | La asignación se rechaza por conflicto de recursos. |
| Un grupo tiene 20 alumnos y el mínimo configurado es 1. | Puede ser válido y genera un aviso de grupo pequeño. |
| La búsqueda termina por tiempo sin una propuesta. | Se informa una búsqueda inconclusa, sin afirmar que el problema sea imposible. |
| Se modifica la disponibilidad de un docente después de generar. | La propuesta anterior requiere revalidación o regeneración antes de exportar. |
| Se cierra y vuelve a abrir la aplicación. | Los datos guardados y las versiones de horario siguen disponibles. |
| Se utilizan los valores predeterminados: inicio 07:00, periodos de 45 minutos y receso 11:30–11:55. | El periodo 6 termina a las 11:30 y el periodo 7 inicia a las 11:55; el bloque semanal conserva siete periodos. |
| Un periodo completo no cabe antes de iniciar el receso. | El periodo empieza después del receso y conserva su duración completa. |
| Un docente tiene seis horas de reloj disponibles para inglés. | Puede atender un bloque de siete periodos de 45 minutos, que consume 5.25 horas; el receso no suma tiempo de clase. |
| Se guardan una duración y un receso nuevos. | Las horas se actualizan en calendarios, reservas, Excel y PDF; las versiones anteriores deben revalidarse o regenerarse. |

## Referencias dentro del proyecto

- [Descripción del sistema](../README.md).
- [Interfaz y flujo de trabajo](../app.py).
- [Reglas y validaciones de datos](../ingles/domain.py).
- [Generación automática](../ingles/scheduler.py).
- [Auditoría independiente](../ingles/audit.py).
- [Persistencia y versiones](../ingles/storage.py).
- [Importación y exportación Excel](../ingles/exchange.py).
- [Reporte PDF](../ingles/reports.py).
