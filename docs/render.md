# Desplegar en Render

El repositorio incluye `render.yaml` para crear un Web Service de Python con Streamlit, una instancia y SQLite en un disco persistente. El archivo `.python-version` selecciona Python 3.14; Render instala el parche disponible de esa versión.

## Despliegue con Blueprint

1. Sube el código a un repositorio de GitHub o GitLab, incluidos `render.yaml`, `.python-version`, `requirements.txt`, `app.py`, `ingles/` y `.streamlit/config.toml`. No subas `venv/`, `data/`, archivos de alumnos ni secretos; las exclusiones están en `.gitignore`.
2. En Render, elige **New → Blueprint**, conecta el repositorio y selecciona la rama que quieras publicar.
3. Revisa la configuración y el costo antes de crear el servicio: el Blueprint especifica **Starter** y un disco persistente de **1 GB**. Estos recursos son de pago.
4. Inicia el despliegue. Render instala las dependencias, ejecuta Streamlit y comprueba `/_stcore/health`.
5. Cuando el servicio esté disponible, abre su URL `https://…onrender.com`. El primer despliegue empieza con una base vacía.

El proceso de generación puede necesitar un plan con más memoria según la cantidad de alumnos, salones y bloques. Si el servicio se queda sin memoria, revisa sus métricas y ajusta el plan.

## Configuración manual equivalente

Si creas un **Web Service** en lugar de un Blueprint, configura:

| Campo | Valor |
| --- | --- |
| Runtime | Python |
| Root Directory | Vacío, si `app.py` está en la raíz del repositorio |
| Build Command | `python -m pip install -r requirements.txt` |
| Start Command | `python -m streamlit run app.py --server.address=0.0.0.0 --server.port=$PORT --server.headless=true` |
| Health Check Path | `/_stcore/health` |
| Variable `INGLES_DB_PATH` | `/var/data/ingles.sqlite3` |
| Persistent Disk → Mount Path | `/var/data` |
| Persistent Disk → Size | `1 GB` |
| Instancias | `1` |

Los argumentos de arranque sustituyen la dirección local `127.0.0.1` del archivo de configuración. Render necesita escuchar en `0.0.0.0` y en el puerto indicado por `PORT`. Se mantienen las protecciones predeterminadas de Streamlit para CORS y XSRF.

## Datos y acceso

Solo lo escrito bajo `/var/data` se conserva entre reinicios y despliegues. No basta con definir `INGLES_DB_PATH`: también debes crear el disco. Los servicios gratuitos no admiten discos persistentes; para usarlos con datos duraderos habría que adaptar el almacenamiento a una base externa. Un servicio con disco funciona con una sola instancia y tiene una breve interrupción durante los despliegues.

La aplicación aún no incorpora autenticación ni roles. En un servicio público, cualquiera que pueda abrir su URL podrá consultar y modificar la planeación. Utiliza datos ficticios hasta incorporar control de acceso para trabajar con alumnos reales.

La base local no se transfiere al subir el código. Puedes importar los Excel desde la interfaz; esto no importa el historial de horarios. Para trasladar también el historial, realiza una copia consistente de SQLite con la aplicación local detenida y transfiérela mediante el acceso SSH del servicio. La sustitución de la base remota debe hacerse sin escrituras activas y conservando un respaldo de la base de destino. No publiques el archivo SQLite en el repositorio.

## Comprobar el despliegue

Abre la aplicación, guarda un cambio de prueba, reinicia el servicio y comprueba que el cambio siga presente. Prueba después una generación y las descargas de Excel/PDF. La comprobación HTTP verifica que Streamlit responde; no sustituye esta revisión de persistencia y funcionamiento.

Referencias oficiales: [servicios web y puerto](https://render.com/docs/web-services), [discos persistentes](https://render.com/docs/disks), [configuración de Blueprint](https://render.com/docs/blueprint-spec) y [versión de Python](https://render.com/docs/python-version).
