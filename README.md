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

> **La primera vez tarda varios minutos.** Docker descarga la imagen base de Python e instala las dependencias de cada servicio. Aunque la terminal parezca detenida, está compilando: no la interrumpa. Las siguientes ejecuciones son casi inmediatas gracias a la caché.

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

La prueba recorre el flujo completo y verifica, entre otras cosas, que los servicios exijan token, que la proyección al modelo de lectura ocurra, que la vista de órdenes venga denormalizada y que el stock se descuente.

Si prefiere no depender de Python en su máquina:

```sh
docker run --rm --network fotoalpes-examples_default \
  -v "$PWD/smoke_test.py:/smoke_test.py:ro" \
  fotoalpes-examples-users-commands python /smoke_test.py https://nginx:443
```

---

# CQRS: cómo está implementado

Esta es la parte central del ejemplo. **CQRS no es solo separar rutas de escritura y de lectura**: es tener dos modelos distintos, cada uno con la forma que su trabajo necesita, conectados por una proyección.

## Dos modelos, dos almacenes

Cada servicio tiene **dos bases de datos**:

| Almacén | Archivo | Quién lo escribe | Quién lo lee |
|---|---|---|---|
| Escritura | `<servicio>-escritura.db` | `api_commands.py` | el lado de comandos y el proyector |
| Lectura | `<servicio>-lectura.db` | el proyector | `api_queries.py` |

El de escritura es la **fuente de verdad**. El de lectura es una **proyección derivada**: se puede borrar entera y regenerarla.

## El modelo de lectura tiene otra forma

Aquí está el argumento del patrón. En `ordenes/base.py` conviven los dos modelos:

```python
class Order(db.Model):
    """Modelo de ESCRITURA. Normalizado y minimo."""
    id, user, product, quantity, state


class OrderView(db.Model):
    """Modelo de LECTURA, denormalizado."""
    __bind_key__ = 'lectura'
    id, user_id, user_username, product_id, product_name,
    product_value, quantity, total, state
```

El de escritura guarda **solo los ids**, que es lo que necesita para decidir si la orden es válida. El de lectura guarda además los **nombres ya resueltos** y el **total ya calculado**.

La diferencia se ve en las respuestas. Al crear una orden, el lado de comandos devuelve el modelo de escritura:

```json
{ "id": 1, "user": 1, "product": 1, "quantity": 10, "state": "processing" }
```

Y al consultarla, el lado de consultas devuelve el modelo de lectura:

```json
{
  "id": 1,
  "user_id": 1,
  "user_username": "ana",
  "product_id": 1,
  "product_name": "Camara",
  "product_value": 1500,
  "quantity": 10,
  "total": 15000,
  "state": "completed"
}
```

**Esa consulta se resuelve leyendo una sola fila**: sin joins y sin llamar a ningún otro servicio. Ese es el beneficio que justifica la complejidad de mantener dos modelos.

En productos ocurre lo mismo a menor escala: el modelo de lectura agrega `disponible`, un booleano que no existe en el de escritura y que se calcula al proyectar.

## La proyección, autorizada por el ACL

Cada escritura encola un trabajo que actualiza el modelo de lectura:

```python
db.session.add(new_user)
db.session.commit()                                   # modelo de escritura
q_proyeccion.enqueue(proyectar_usuario, new_user.id)  # modelo de lectura
```

En esta rama, **la cola de proyección también está sujeta al ACL**, igual que las de comunicación entre servicios. Cada servicio pregunta al arrancar qué cola tiene autorizada:

```python
q_proyeccion = Queue(
    connection=Redis(host='redis', port=6379, db=obtener_cola("users", "proyeccion"))
)
```

Las autorizaciones se cargan en `acl/build_database.py`:

| Servicio | Cola | Valor (db de Redis) | Para qué |
|---|---|---|---|
| `orders` | `q` | 0 | Órdenes por procesar y réplicas entrantes |
| `orders` | `q2` | 1 | Pedir el descuento de stock |
| `orders` | `proyeccion` | 0 | Proyectar órdenes |
| `products` | `q` | 0 | Replicar hacia órdenes |
| `products` | `proyeccion` | 1 | Proyectar productos |
| `users` | `q` | 0 | Replicar hacia órdenes |
| `users` | `proyeccion` | 2 | Proyectar usuarios |

El proyector se vuelve a encolar **cada vez que cambia algo**: al crear, al modificar un producto, al descontar stock y cuando `process_order` cambia el estado de la orden.

## Consistencia eventual

Como la proyección es asíncrona, **hay un instante en el que la escritura ya ocurrió pero la consulta todavía no la refleja**. Un usuario recién creado puede no aparecer aún en `GET /api-queries/users`.

Eso no es un error: es la contrapartida de CQRS, y se llama consistencia eventual. En la práctica el retraso es de milisegundos, así que pasa desapercibido.

Para **verlo en clase**, levante el ejemplo con un retraso artificial en la proyección:

```sh
RETRASO_PROYECCION=5 docker compose up -d --build --wait
```

Ahora cree un usuario y consulte inmediatamente la lista: el `POST` devuelve el id al instante, pero el usuario tarda cinco segundos en aparecer en la consulta. Es el problema clásico de *read-your-own-writes*, visible y medible.

## Reconstruir la proyección

Como el modelo de lectura es derivado, se puede regenerar por completo:

```sh
docker compose exec users-commands    python reconstruir_proyeccion.py
docker compose exec products-commands python reconstruir_proyeccion.py
docker compose exec orders-commands   python reconstruir_proyeccion.py
```

Esto borra el modelo de lectura y lo vuelve a construir desde el de escritura. Es una operación habitual en sistemas con CQRS: se usa cuando la proyección se corrompe, cuando cambia su forma, o cuando se agrega una vista nueva sobre datos que ya existían. El CI verifica en cada corrida que la proyección reconstruida sea idéntica a la original.

## Qué **no** hace este ejemplo

Vale la pena ser explícito con los límites, para no confundir el ejemplo con el patrón completo:

- **No hay event sourcing.** El modelo de escritura guarda el estado actual, no la secuencia de eventos que lo produjo. Event sourcing suele acompañar a CQRS, pero es un patrón distinto.
- **Ambos contenedores montan el mismo directorio.** Por simplicidad, el contenedor de consultas *podría* abrir el archivo de escritura; simplemente no lo hace. En un sistema real serían bases separadas y el lado de consulta no tendría credenciales para el almacén de escritura.
- **La vista de una orden no se actualiza si después cambia el nombre del producto.** La proyección se rehace cuando cambia la orden, no cuando cambia el producto. Es una limitación real de las proyecciones denormalizadas y queda como ejercicio: ¿qué habría que encolar en `productos/api_commands.py` para arreglarlo, y qué costo tendría?
- **Las bases son SQLite en archivo**, suficiente para el aula pero no para producción.

---

## Endpoints

Todas las rutas pasan por el API Gateway en `https://localhost:5000` y **requieren token**, excepto `/api-queries/jwt`.

| Componente | Operación | Método | Ruta | Modelo |
|---|---|---|---|---|
| Jwt | Obtener token (**sin** token) | GET | `/api-queries/jwt` | — |
| Usuarios | Crear usuario | POST | `/api-commands/users` | escritura |
| Usuarios | Listar usuarios | GET | `/api-queries/users` | lectura |
| Usuarios | Consultar usuario | GET | `/api-queries/users/<id>` | lectura |
| Productos | Crear producto | POST | `/api-commands/products` | escritura |
| Productos | Modificar producto | PUT | `/api-commands/products/<id>` | escritura |
| Productos | Listar productos | GET | `/api-queries/products` | lectura |
| Productos | Consultar producto | GET | `/api-queries/products/<id>` | lectura |
| Órdenes | Crear orden | POST | `/api-commands/orders` | escritura |
| Órdenes | Listar órdenes | GET | `/api-queries/orders` | lectura |
| Órdenes | Consultar orden | GET | `/api-queries/orders/<id>` | lectura |

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

**Con Postman:** importe el archivo [`fotoalpes.postman_collection.json`](fotoalpes.postman_collection.json) que viene en el repositorio y tendrá todas las operaciones listas. Ejecute primero `Obtener token`: queda guardado y las demás peticiones lo envían solas, igual que los ids de usuario, producto y orden. En [POSTMAN.md](POSTMAN.md) está el paso a paso con capturas.

## Descripción de los componentes

### Jwt

Expone una sola operación (`jwt/api.py`): **crear token** (`AuthResource.get`). En cada operación de los demás servicios se declara `@jwt_required()`, que obliga a validar ese token:

```python
class OrderListResource(Resource):
    @jwt_required()
    def get(self):
```

### ACL

Valida que un servicio tenga permiso de usar una cola de mensajería (`acl/api.py`). Cada servicio lo consulta **al arrancar**, tanto para las colas de comunicación como para las de proyección.

> Esa consulta ocurre al importar el módulo. Si `jwt` o `acl` aún no responden, el contenedor moriría al arrancar, por lo que `obtener_cola()` reintenta y el `docker-compose.yaml` declara la dependencia con `condition: service_healthy`.

### Órdenes, Productos y Usuarios

Cada uno expone sus operaciones en dos partes: comandos (`api_commands.py`, sobre el modelo de escritura) y consultas (`api_queries.py`, sobre el modelo de lectura), y cada parte corre en su propio contenedor.

## Comunicación asíncrona

Se usan **tres bases de datos de Redis**, atendidas por tres workers distintos:

| Cola | Worker | Corre en | Responsabilidad |
|---|---|---|---|
| db `0` | `worker-orders` | imagen de `ordenes` | Procesa órdenes, recibe las réplicas de usuarios y productos, y proyecta las órdenes |
| db `1` | `worker-products` | imagen de `productos` | Descuenta el stock y proyecta los productos |
| db `2` | `worker-users` | imagen de `usuarios` | Proyecta los usuarios |

Conviven **dos mecanismos asíncronos distintos**, y conviene no confundirlos:

1. **Replicación entre servicios.** El servicio de órdenes mantiene copias locales de usuarios y productos porque las necesita para validar. Eso lo hacen `sender.py` y `putter.py`.
2. **Proyección dentro de un servicio.** Cada servicio mantiene su propio modelo de lectura a partir de su modelo de escritura. Eso lo hace `proyector.py`. **Esto es CQRS**; lo anterior no.

### Actualizar el stock

La actualización la solicita el servicio de órdenes. En `ordenes/base.py`, `process_order` verifica las existencias, cambia el estado y publica en la segunda cola la cantidad a descontar:

```python
q2.enqueue(update_product, {'id': product.id, 'quantity': order.quantity})
```

> **Detalle importante:** `ordenes/base.py` importa un `update_product` local que no hace nada (`ordenes/updater.py`). Ese *stub* existe solo para poder encolar la referencia: RQ la serializa como `updater.update_product` y quien la ejecuta es `worker-products`, que resuelve ese nombre contra `productos/updater.py`. Es decir, **la función que se importa no es la que se ejecuta**. Los proyectores, en cambio, sí se ejecutan en su propio servicio.

## API Gateway

nginx recibe todo el tráfico en HTTPS y lo redirige al servicio correspondiente, también por HTTPS:

```
listen 443 ssl;
http2 on;
ssl_protocols TLSv1.2 TLSv1.3;

location /api-commands/users {
  set $destino users-commands;
  proxy_pass https://$destino:5000$request_uri;
  ...
}
```

El `resolver` y la variable en `proxy_pass` no son adorno: sin ellos nginx resuelve los nombres una sola vez al arrancar, y al recrear contenedores puede terminar enviando una ruta al servicio equivocado. La configuración completa está en `nginx/nginx-proxy.conf`.

## Notas de mantenimiento

- **Todas las versiones están fijadas**, incluidas las imágenes de Redis y nginx. Sin eso el ejemplo deja de compilar solo con que pase el tiempo.
- Las llamadas entre servicios usan `verify=False` porque los certificados son autofirmados. **Es aceptable solo en este ejemplo**; en un sistema real habría que validar la cadena de certificación.
- La configuración de nginx ya no acepta TLS 1.0 ni 1.1: están obsoletos y las versiones actuales de nginx y OpenSSL los rechazan.
- `Flask-JWT-Extended` usa `JWT_SECRET_KEY = "secret-jwt"` y tokens que **no expiran** (`JWT_ACCESS_TOKEN_EXPIRES = False`). Ambas cosas son deliberadas para simplificar el ejemplo y ambas serían graves en producción.
- El `docker-compose.yaml` **no define política de `restart`** a propósito: si un servicio falla, debe quedar caído y visible en `docker compose ps`.
- Si el proyector se cae, las consultas siguen respondiendo **con datos viejos y sin error**. Es lo que pasaría en un sistema real, pero al depurar conviene revisar `docker compose logs worker-users` antes de sospechar del código de consultas.
- Los servicios corren con el servidor de desarrollo de Flask y certificados `adhoc`. Adecuado para el aula, no para despliegues reales.
