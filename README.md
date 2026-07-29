# fotoalpes-examples — rama `async-sec`

Ejemplo resuelto del caso **Foto Alpes** para el curso de Arquitecturas Ágiles de Software (MISW). Esta rama combina todo: patrón **CQRS**, **comunicación asíncrona** con Redis, **TLS** entre todos los componentes, **autenticación con tokens JWT** y un componente **ACL** que autoriza qué cola puede usar cada servicio.

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

El certificado actual vence en **2046**. Para regenerarlo:

```sh
sh nginx/generar_certificados.sh
docker compose up -d --build --wait
```

> Los certificados originales de este ejemplo vencieron en mayo de 2024 y hacían fallar la rama completa. El CI ahora verifica la vigencia en cada corrida.

## Autenticación

**Todos los servicios exigen un token JWT.** Primero pida un token al componente `jwt`:

```sh
curl -k https://localhost:5000/api-queries/jwt
```

Y envíelo en la cabecera `Authorization` de las demás peticiones:

```sh
curl -k https://localhost:5000/api-queries/users \
  -H "Authorization: Bearer <token>"
```

Sin token, los servicios responden **401**.

## Verificar que todo funciona

Con los servicios corriendo:

```sh
python3 smoke_test.py
```

La prueba recorre el camino completo: obtiene un token, comprueba que sin token la respuesta es 401, crea usuario y producto, espera a que el worker los replique en la base de datos del servicio de órdenes, crea una orden, verifica que el procesamiento asíncrono la marcó como `completed` y descontó el stock, y finalmente modifica el producto para comprobar que la réplica se actualiza.

Si prefiere no depender de Python en su máquina:

```sh
docker run --rm --network fotoalpes-examples_default \
  -v "$PWD/smoke_test.py:/smoke_test.py:ro" \
  fotoalpes-examples-users-commands python /smoke_test.py https://nginx:443
```

## Endpoints

Todas las rutas pasan por el API Gateway en `https://localhost:5000` y **requieren token**, excepto `/api-queries/jwt`.

| Componente | Operación | Método | Ruta |
|---|---|---|---|
| Jwt | Obtener token (**sin** token) | GET | `/api-queries/jwt` |
| Usuarios | Crear usuario | POST | `/api-commands/users` |
| Usuarios | Listar usuarios | GET | `/api-queries/users` |
| Usuarios | Consultar usuario | GET | `/api-queries/users/<id>` |
| Productos | Crear producto | POST | `/api-commands/products` |
| Productos | Modificar producto | PUT | `/api-commands/products/<id>` |
| Productos | Listar productos | GET | `/api-queries/products` |
| Productos | Consultar producto | GET | `/api-queries/products/<id>` |
| Órdenes | Crear orden | POST | `/api-commands/orders` |
| Órdenes | Listar órdenes | GET | `/api-queries/orders` |
| Órdenes | Consultar orden | GET | `/api-queries/orders/<id>` |

> El componente **ACL no se publica** por el gateway: solo lo consultan los servicios entre sí dentro de la red de Docker.

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
>
> El usuario y el producto deben existir **en la base de datos del servicio de órdenes**, donde llegan por replicación asíncrona. Si crea una orden inmediatamente después de crear el usuario, puede recibir un 400: espere un momento y reintente.

En [POSTMAN.md](POSTMAN.md) está el paso a paso de Postman con capturas, incluido cómo enviar el token en la cabecera `Authorization`.

## Descripción de los componentes

Al implementar CQRS, cada servicio de negocio expone sus operaciones en dos partes: comandos (`api_commands.py`) y consultas (`api_queries.py`), y cada parte corre en su propio contenedor.

### Jwt

Expone una sola operación (`jwt/api.py`): **crear token** (`AuthResource.get`). En cada operación de los demás servicios se declara `@jwt_required()`, que obliga a validar ese token:

```python
class OrderListResource(Resource):
    @jwt_required()
    def get(self):
```

### ACL

Valida que un servicio tenga permiso de usar una cola de mensajería (`acl/api.py`). Cada servicio lo consulta **al arrancar** para saber qué base de datos de Redis puede usar:

```python
q = Queue(connection=Redis(host='redis', port=6379, db=obtener_cola("orders", "q")))
```

Las autorizaciones se cargan en `acl/build_database.py`:

| Servicio | Cola | Valor (db de Redis) |
|---|---|---|
| `orders` | `q` | 0 |
| `orders` | `q2` | 1 |
| `products` | `q` | 0 |
| `users` | `q` | 0 |

> Esa consulta ocurre al importar el módulo. Si `jwt` o `acl` aún no responden, el contenedor moriría al arrancar, por lo que `obtener_cola()` reintenta y el `docker-compose.yaml` declara la dependencia con `condition: service_healthy`.

### Órdenes

En `api_commands.py`: **crear una nueva orden**. Una vez creada se encola su id para procesarla:

```python
# add to queue to process order
q.enqueue(process_order, new_order.id)
```

En `api_queries.py`: **listar todas las órdenes** y **consultar una orden específica**.

### Productos

En `api_commands.py`: **crear** y **modificar** un producto. En `api_queries.py`: **listar** y **consultar**.

### Usuarios

En `api_commands.py`: **crear un nuevo usuario**. En `api_queries.py`: **listar** y **consultar**.

### API Gateway

nginx recibe todo el tráfico en HTTPS y lo redirige al servicio correspondiente según la operación y la ruta, también por HTTPS:

```
listen 443 ssl;
http2 on;
ssl_protocols TLSv1.2 TLSv1.3;

location /api-commands/users {
  proxy_pass https://users-commands:5000;
  ...
}
location /api-queries/users {
  proxy_pass https://users-queries:5000;
  ...
}
```

La configuración completa está en `nginx/nginx-proxy.conf`.

## Comunicación asíncrona

Cada servicio tiene una copia de la estructura de la base de datos de los demás, por lo que hay que propagar los cambios cuando alguno actualiza su información. Para eso se usan **dos colas de Redis**, atendidas por dos workers distintos:

| Cola | Worker | Corre en | Responsabilidad |
|---|---|---|---|
| db `0` | `worker-orders` | contenedor de `ordenes` | Procesa órdenes y replica usuarios y productos en la BD de órdenes |
| db `1` | `worker-products` | contenedor de `productos` | Descuenta el stock en la BD de productos |

### Notificar cambios

En `api_commands.py` se publica en la cola la información del producto creado o modificado:

```python
# Publicación en la cola en la creación de un producto
def post(self):
    ...
    q.enqueue(send_product, product_schema.dump(new_product))

# Publicación en la cola en la modificación de un producto
def put(self):
    ...
    q.enqueue(put_product, product_schema.dump(product))
```

`sender.py` publica el producto nuevo y `putter.py` el producto modificado.

### Actualizar cambios

La actualización del stock la solicita el servicio de órdenes. En `ordenes/base.py`, `process_order` verifica las existencias, cambia el estado de la orden y publica en la segunda cola la cantidad a descontar:

```python
def process_order(order_id):
    ...
    q2.enqueue(update_product, {
        'id': product.id,
        'quantity': order.quantity
    })
```

`productos/updater.py` implementa el descuento real.

> **Detalle importante para entender el ejemplo:** `ordenes/base.py` importa un `update_product` local que no hace nada (`ordenes/updater.py`). Ese *stub* existe solo para poder encolar la referencia: RQ la serializa como `updater.update_product` y quien la ejecuta es `worker-products`, que resuelve ese nombre contra `productos/updater.py`. Lo mismo ocurre con `sender.py` y `putter.py` en los otros servicios. Es decir, **la función que se importa no es la que se ejecuta**.

## Notas de mantenimiento

- **Todas las versiones están fijadas**, incluidas las imágenes de Redis y nginx. Sin eso el ejemplo deja de compilar solo con que pase el tiempo.
- Las llamadas entre servicios usan `verify=False` porque los certificados son autofirmados. **Es aceptable solo en este ejemplo**; en un sistema real habría que validar la cadena de certificación.
- La configuración de nginx ya no acepta TLS 1.0 ni 1.1: están obsoletos y las versiones actuales de nginx y OpenSSL los rechazan.
- `Flask-JWT-Extended` usa `JWT_SECRET_KEY = "secret-jwt"` y tokens que **no expiran** (`JWT_ACCESS_TOKEN_EXPIRES = False`). Ambas cosas son deliberadas para simplificar el ejemplo y ambas serían graves en producción.
- El `docker-compose.yaml` **no define política de `restart`** a propósito: si un servicio falla, debe quedar caído y visible en `docker compose ps`.
- Las bases de datos son SQLite en archivo, compartidas por bind mount entre el contenedor de comandos y el de consultas de cada servicio. Suficiente para el ejemplo, no apto para producción.
- Los servicios corren con el servidor de desarrollo de Flask y certificados `adhoc`. Adecuado para el aula, no para despliegues reales.
