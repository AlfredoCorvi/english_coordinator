# Recorrido funcional de la fase 7

El recorrido se automatizó en `tests/test_functional_demo.py` con Streamlit
`AppTest`, SQLite temporal y credenciales ficticias. No modifica la base del
usuario ni requiere consumir la API de Mockaroo.

En una ejecución completa se verificó:

1. Inicio de sesión de Secretaría y carga del escenario, que crea dos periodos y
   configura los datos ficticios de alumnos, niveles, docentes y bloques.
2. Generación de dos propuestas diferentes: 200 alumnos, 190 activos, 158
   elegibles, 20 exentos y 12 pendientes de nivel. En esa ejecución ambas búsquedas
   devolvieron `OPTIMAL`; los tiempos y la prueba de optimalidad pueden variar.
3. Comparación de versiones y cambio docente validado desde la interfaz.
4. Publicación parcial con las dos confirmaciones explícitas.
5. Cierre de sesión y acceso de un docente efectivamente asignado; consulta de
   sus grupos y alumnos oficiales.
6. Registro de próximo nivel para el segundo periodo y envío de una incidencia.
7. Nueva sesión de Secretaría, aprobación de la incidencia y comprobación de que
   permanece pendiente de aplicación porque pertenece a un grupo publicado.
8. Apertura de Reportes, comprobación de ambos controles de descarga y lectura de
   los archivos Excel y PDF generados por el servicio. La prueba comprueba los
   bytes y su contenido; no automatiza una descarga de navegador físico.
9. Apertura de una conexión nueva y una sesión nueva de Streamlit sobre el mismo
   SQLite temporal; la publicación, los alumnos y la incidencia siguen guardados.

La prueba también comprueba un grupo multinivel pequeño y una mezcla de carreras.
Los horarios y credenciales son exclusivamente ficticios. Para ejecutarla:

```powershell
python -m unittest discover -s tests -p test_functional_demo.py -v
```

La segunda búsqueda dispone de hasta 60 segundos; si el límite se agota, un estado
`FEASIBLE` no debe interpretarse como demostración de todas las prioridades. El
resultado exacto puede variar entre ejecuciones.
