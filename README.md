# Port Manager

Panel web **de solo lectura** para inventariar puertos TCP/UDP publicados por Docker y sockets en escucha en el servidor Linux.

## Requisitos

- Ubuntu Server (o Linux equivalente) con Docker Engine y Docker Compose v2.
- Docker Engine local accesible mediante `/var/run/docker.sock`.
- Acceso SSH a tu servidor y permisos para utilizar `docker compose`.
- Conexión a Internet en el **primer build** para descargar las imágenes base y las dependencias Python.

## Instalación

1. Descomprime el ZIP y entra en la carpeta `port-manager`.
2. Crea la configuración: `cp .env.example .env`.
3. Inicia ambos servicios: `docker compose up -d --build`.
4. Comprueba: `docker compose ps` y `docker compose logs --tail=50 collector`.

Por defecto la web queda en **http://127.0.0.1:8765** en el servidor. Ese acceso está limitado a localhost por seguridad. Si navegas desde tu PC, abre un túnel SSH en el PC:

```bash
ssh -L 8765:127.0.0.1:8765 USUARIO@IP_DEL_SERVIDOR
```

Después visita [http://localhost:8765](http://localhost:8765) en tu navegador.

### Acceso directo desde LAN o Tailscale

Edita `.env` y cambia `BIND_IP` por **la IP LAN o Tailscale del servidor**. Por ejemplo:

```ini
BIND_IP=192.168.1.50
WEB_PORT=8765
INTERVAL_SECONDS=5
```

La IP `192.168.1.50` es solo un ejemplo: usa la tuya. Reinicia con `docker compose up -d` y accede mediante `http://IP_DEL_SERVIDOR:8765`. Mantén el acceso restringido a dispositivos de confianza; la aplicación no incorpora autenticación propia.

Si el puerto 8765 ya está ocupado, cambia `WEB_PORT` antes de arrancar. No hay que modificar el puerto interno 8080 del contenedor web.

## Qué muestra

- Lista de puertos publicados por contenedores Docker, incluido puerto interno, protocolo y dirección de publicación.
- Puertos TCP en escucha y sockets UDP detectados con `ss -H -lntup`, con proceso y PID cuando Linux permite obtenerlos.
- Búsqueda, filtros (Docker/Sistema y protocolo), consulta puntual de puerto, exportación CSV.
- Contenedores activos y detenidos, su imagen y proyecto Compose si está etiquetado.
- Estado de las dos fuentes de datos, errores de lectura y aviso de información antigua.

**La ausencia de coincidencias no garantiza que un puerto esté libre.** La detección es instantánea, puede haber cambios entre comprobación y despliegue, diferencias por IP/protocolo y restricciones de red/firewall. Puertos usados dentro de contenedores sin publicación al host no aparecen como publicaciones. Los contenedores con `network_mode: host` no tienen mapeos de puertos Docker: sus sockets pueden aparecer en Linux, pero no siempre se pueden atribuir inequívocamente a un contenedor. Algunos nombres/PID de procesos pueden no ser visibles desde el entorno del recolector. Se omiten conexiones salientes, no destinadas a recibir tráfico.

## Seguridad

La aplicación consta de **dos contenedores separados**:

- `collector`: tiene acceso al socket Docker y a los espacios de nombres de red/PID del host. Ejecuta consultas y escribe un JSON cada 5 segundos; no ofrece interfaz HTTP.
- `web`: solo puede **leer** el volumen de datos. No recibe el socket Docker, no ejecuta comandos del host, corre como usuario no privilegiado y expone la API únicamente en el puerto configurado.

**Importante:** montar `/var/run/docker.sock` con `:ro` **no vuelve la API Docker de solo lectura**. Cualquier proceso comprometido con acceso al socket podría emitir operaciones administrativas y adquirir privilegios elevados en el host. Por eso no debes instalar imágenes no confiables en el recolector ni publicar su proceso, y la web no recibe ese socket. Como opción de seguridad superior, se puede sustituir el contenedor `collector` por un proceso local con permisos cuidadosamente separados y un proxy filtrado de la API Docker.

La interfaz es de solo lectura: no incluye parar, eliminar ni desplegar contenedores. No hay cuentas, contraseñas ni almacenamiento externo. No expongas este panel directamente a Internet sin un sistema de autenticación y HTTPS delante.

## Mantenimiento

```bash
# Verificar contenedores
docker compose ps

# Ver logs del recolector
docker compose logs -f collector

# Ver logs web
docker compose logs -f web

# Reconstruir tras actualizar archivos
docker compose up -d --build

# Detener sin borrar datos ni volúmenes
docker compose down
```

Para problemas con `collector`, comprueba que existe el socket con `ls -l /var/run/docker.sock`. Si tu instalación es Docker rootless, el socket puede estar en otra ruta y necesitar cambios en Compose.

## Comprobación local de la lógica

Sin Docker, el parser y la lógica del recolector pueden comprobarse en una máquina con Python 3.10+:

```bash
python3 -m unittest discover -s tests -v
```

## Estructura

```text
port-manager/
├── compose.yaml
├── .env.example
├── collector/
│   ├── Dockerfile
│   └── collect.py
├── web/
│   ├── Dockerfile
│   ├── requirements.txt
│   ├── app.py
│   └── static/
│       ├── index.html
│       ├── styles.css
│       └── app.js
└── tests/
    └── test_collector.py
```
