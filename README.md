# fotoalpes-examples — rama `sync-sec`

Ejemplo resuelto del caso **Foto Alpes** para el curso de Arquitecturas Ágiles de Software (MISW). Esta rama toma la comunicación **síncrona** de la rama `sync` y le agrega las tácticas de seguridad: **TLS** entre todos los componentes y **autenticación con tokens JWT**, más un componente **ACL** que decide a qué cola puede acceder cada servicio.

## Ramas del proyecto

| Rama | Contenido |
|---|---|
| `main` | CQRS y comunicación asíncrona |
| `sync` | Comunicación síncrona |
| `sync-sec` | Tokens JWT y certificados, con comunicación síncrona |
| `async-sec` | Tokens JWT y certificados, con comunicación asíncrona |

## Requisitos

Solo necesita **Docker** con **Compose v2**.

- **macOS / Windows:** instale [Docker Desktop](https://www.docker.com/products/docker-desktop/).
- **Ubuntu / Debian:** ejecute `sh install.sh` y luego cierre y reabra la sesión.

Verifique con `docker compose version`.

## Ejecución

```sh
docker compose up -d --build --wait
```

Los servicios quedan expuestos a través del API Gateway en **https://localhost:5000** (note el **https**).

Para detener todo y borrar los datos:

```sh
docker compose down -v
```

## Certificados

El API Gateway usa un certificado **autofirmado** versionado en `nginx/`. Su navegador y Postman mostrarán una advertencia de certificado no confiable: es lo esperado.

> **Estos son certificados de prueba.** La llave privada está en el repositorio a propósito para que el ejemplo funcione sin pasos adicionales. Nunca los use fuera del aula.

En Postman debe desactivar la verificación de certificados: **File → Settings → SSL certificate verification → Off**.

El certificado actual vence en **2046**. Si necesita regenerarlo (o cambiar los nombres que cubre), ejecute:

```sh
sh nginx/generar_certificados.sh
docker compose up -d --build --wait
```

> Los certificados originales de este ejemplo vencieron en mayo de 2024 y hacían fallar la rama completa. El CI ahora verifica la vigencia en cada corrida para que eso no vuelva a pasar en silencio.

## Autenticación

**Todos los servicios exigen un token JWT.** Antes de consumir cualquier operación debe pedir un token al componente `jwt`:

```sh
curl -k https://localhost:5000/jwt
```

Respuesta:

```json
{ "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..." }
```

Ese token se envía en la cabecera `Authorization` de todas las demás peticiones:

```sh
curl -k https://localhost:5000/users \
  -H "Authorization: Bearer <token>"
```

Sin token, los servicios responden **401**.

> La opción `-k` de curl omite la validación del certificado autofirmado, igual que el ajuste de Postman.

## Verificar que todo funciona

Con los servicios corriendo:

```sh
python3 smoke_test.py
```

La prueba verifica el flujo funcional completo **y** la parte de seguridad: que el componente `jwt` entregue un token, que los servicios rechacen peticiones sin token (401), que el ACL responda qué cola corresponde al servicio de órdenes, que la orden se complete descontando el stock, y que una orden por encima del stock quede en `failed`.

Si prefiere no depender de Python en su máquina:

```sh
docker run --rm --network fotoalpes-examples_default \
  -v "$PWD/smoke_test.py:/smoke_test.py:ro" \
  fotoalpes-examples-users python /smoke_test.py https://nginx:443
```

## Endpoints

Todas las rutas pasan por el API Gateway en `https://localhost:5000` y **requieren token**, excepto `/jwt`.

| Componente | Operación | Método | Ruta |
|---|---|---|---|
| Jwt | Obtener token (**sin** token) | GET | `/jwt` |
| ACL | Consultar cola de un servicio | GET | `/acl/<servicio>/<cola>` |
| Usuarios | Listar / crear | GET / POST | `/users` |
| Usuarios | Consultar | GET | `/users/<id>` |
| Productos | Listar / crear | GET / POST | `/products` |
| Productos | Consultar / modificar | GET / PUT | `/products/<id>` |
| Órdenes | Listar / crear | GET / POST | `/orders` |
| Órdenes | Consultar | GET | `/orders/<id>` |

Cuerpos de las peticiones:

```json
{ "username": "nombre_del_usuario" }
```

```json
{
  "name": "Nombre del producto",
  "description": "Descripción del producto",
  "value": 1500,
  "stock": 100
}
```

```json
{
  "user": 1,
  "product": 1,
  "quantity": 10
}
```

> La orden se crea en estado `processing` y un worker la procesa. Consúltela unos segundos después para verla en `completed` o `failed`.

En `vm/README.md` de la rama `main` está el paso a paso de Postman con capturas.

## Descripción de los componentes

### Jwt

Expone una sola operación (`jwt/api.py`):

- **Crear token** (`AuthResource.get`), que devuelve el token a incluir en las demás llamadas.

En cada operación de los otros servicios se declara `@jwt_required()`, que obliga a validar ese token:

```python
class OrderListResource(Resource):
    @jwt_required()
    def get(self):
```

### ACL

Expone una operación (`acl/api.py`) que responde qué cola tiene autorizada un servicio. El servicio de órdenes la consulta **al arrancar** para saber qué base de datos de Redis puede usar:

```python
queue_name = obtener_cola()
q = Queue(connection=Redis(host='redis', port=6379, db=queue_name))
```

> Esa consulta ocurre al importar el módulo. Si `jwt` o `acl` aún no responden, el contenedor moriría al arrancar, por lo que `obtener_cola()` reintenta y el `docker-compose.yaml` declara la dependencia con `condition: service_healthy`.

### Órdenes

Tres operaciones en `ordenes/api.py`: listar, crear y consultar. La creación **valida de forma síncrona** que el usuario y el producto existan, reenviando el token del cliente a los otros servicios:

```python
headers = {'Authorization': request.headers['Authorization']}
user = requests.get(f"https://users:5000/users/{...}", verify=False, headers=headers)
```

El procesamiento posterior vive en `ordenes/worker.py`, donde `process_order` pide su **propio** token (no hay un cliente del cual reenviarlo) y descuenta el stock con un PUT al servicio de productos.

### Productos y Usuarios

Exponen las mismas operaciones que en la rama `sync`, pero con `@jwt_required()` en todas y sirviendo por HTTPS.

### API Gateway

nginx recibe todo el tráfico en HTTPS y lo redirige al servicio correspondiente, también por HTTPS:

```
listen 443 ssl;
http2 on;
ssl_certificate /etc/ssl/certs/localhost.crt;
ssl_certificate_key /etc/ssl/private/localhost.key;
ssl_protocols TLSv1.2 TLSv1.3;

location /users {
  proxy_pass https://users:5000;
  ...
}
```

La configuración completa está en `nginx/nginx-proxy.conf`.

## Notas de mantenimiento

- **Todas las versiones están fijadas**, incluidas las imágenes de Redis y nginx. Sin eso el ejemplo deja de compilar solo con que pase el tiempo.
- Las llamadas entre servicios usan `verify=False` porque los certificados son autofirmados. **Es aceptable solo en este ejemplo**; en un sistema real habría que validar la cadena de certificación.
- La configuración de nginx ya no acepta TLS 1.0 ni 1.1: están obsoletos y las versiones actuales de nginx y OpenSSL los rechazan.
- `Flask-JWT-Extended` usa `JWT_SECRET_KEY = "secret-jwt"` y tokens que **no expiran** (`JWT_ACCESS_TOKEN_EXPIRES = False`). Ambas cosas son deliberadas para simplificar el ejemplo y ambas serían graves en producción.
- El `docker-compose.yaml` **no define política de `restart`** a propósito: si un servicio falla, debe quedar caído y visible en `docker compose ps`.
- Los servicios corren con el servidor de desarrollo de Flask y certificados `adhoc`. Adecuado para el aula, no para despliegues reales.
