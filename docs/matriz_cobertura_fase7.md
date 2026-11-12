# Cobertura de casos de uso — fase 7

Evaluación funcional frente a `casos_de_uso_ingles.docx`. «Completo» significa que
el flujo descrito está disponible en el portal de desarrollo bajo las reglas
acordadas; no implica que exista autenticación institucional real.

| Caso | Estado | Evidencia y límite |
|---|---|---|
| CU-01-SA Panel | Implementado | Panel por periodo con alumnos, grupos, docentes disponibles y asignados, grupos sin docente, pendientes y conflictos. |
| CU-02.1-SA Registro de alumnos | Parcial | Sincronización de alumnos en `institutional_services`; el texto del caso está truncado y atribuye erróneamente el rol docente a alumnos. No se crean cuentas de alumno. |
| CU-02-SA Alumnos | Implementado | Consulta, filtros e importación de solo lectura; `test_institutional_services.py` y `test_academic_services.py`. Los IDs de carrera y grupo del simulador se derivan provisionalmente de nombres. |
| CU-04-SA Niveles | Implementado | Catálogo informativo y exenciones; `test_relational_storage.py`. |
| CU-5.1-SA Registro de maestros | Parcial | Sincronización y rol docente; la API no devuelve sujeto de identidad y exige un mapa externo verificado. |
| CU-05-SA Docentes | Implementado | Participación, disponibilidad y límites por periodo; `test_academic_services.py`. |
| CU-06-SA Bloques | Implementado | Cinco bloques iniciales, creación manual de más bloques, edición versionada, activación e intervalos configurables; `test_academic_services.py`. |
| CU-07-SA Generar grupos | Implementado | CP-SAT relacional con pendientes, exentos y auditoría; `test_relational_scheduler.py`. |
| CU-08-SA Asignar docentes y bloques | Implementado | Asignación conjunta sin salones, empalmes ni sobrecargas; `test_relational_scheduler.py`. |
| CU-09-SA Consultar y modificar grupos | Implementado | Vista, filtros y cambios derivados auditados; `test_planning_proposals.py`. |
| CU-10-SA Conflictos y pendientes | Parcial | Auditoría y pendientes visibles; no se determina una causa única para cada alumno sin grupo. |
| CU-11-SA Carga docente | Implementado | Grupos, horas, límites e intervalos restantes por docente; `test_academic_services.py`. |
| CU-12-SA Periodos | Implementado | Creación, selección e historial por periodo; `test_portal.py`. |
| CU-13-SA Reportes | Implementado | Ocho reportes por versión en Excel y PDF; `test_reports_demo.py` y `test_functional_demo.py`. En versiones anteriores a fase 7 se indica si falta la instantánea de inactivos. |
| CU-14-SA Configuración del algoritmo | Implementado | Cupos y tiempo de búsqueda configurables por periodo; se mantienen como obligatorios los límites acordados de niveles, horas y duración. `test_academic_services.py`. |
| CU-15-SA Incidencias | Implementado | Revisión y resolución; cambios de grupos publicados se preparan en versión y se aplican al publicarla; `test_planning_proposals.py`. |
| CU-16-SA Historial | Implementado | Historial académico, versiones y eventos; `test_academic_services.py`, `test_planning_proposals.py`. |
| CU-17-SA Versiones | Implementado | Alternativas distintas, comparación y publicación; `test_planning_proposals.py`. La búsqueda puede agotar el tiempo sin demostrar que no haya más alternativas. |
| CU-01-D Panel | Implementado | Muestra grupos oficiales, alumnos autorizados, bloques y decisiones pendientes para el periodo siguiente. |
| CU-02-D Alumnos | Parcial | Consulta limitada a alumnos autorizados y filtros; por seguridad la sincronización global está reservada a Secretaría. |
| CU-03-D Próximo nivel | Implementado | Sugerencia, repetición, exención y registro por periodo; `test_academic_services.py`. |
| CU-04-D Incidencia | Implementado | Solicitud limitada a alumnos autorizados; `test_academic_services.py`. |
| CU-01-G Registro de maestros | Parcial | Mismo flujo que CU-5.1-SA; depende de vinculación de identidad confiable. |
| CU-02-G Inicio de sesión | Parcial | Login simulado, roles locales y expiración; falta contrato y proveedor institucional real. `test_portal.py`. |

El documento no contiene CU-03-SA. Los reportes usan la instantánea de la versión;
el reporte de conflictos de una publicación también revisa los datos actuales.
No se modelan horarios regulares individuales de alumnos, salones ni materias.
