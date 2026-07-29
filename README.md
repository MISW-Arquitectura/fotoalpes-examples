# fotoalpes-examples — rama `main`

Ejemplo resuelto del caso **Foto Alpes** para el curso de Arquitecturas Ágiles de Software (MISW). Esta rama implementa el patrón **CQRS** con **comunicación asíncrona** entre microservicios, usando Redis como plataforma de mensajería.

## Ramas del proyecto

| Rama | Contenido |
|---|---|
| `main` | CQRS y comunicación asíncrona |
| `sync` | Comunicación síncrona |
| `sync-sec` | Tokens JWT y certificados, con comunicación síncrona |
| `async-sec` | Tokens JWT y certificados, con comunicación asíncrona |

## Requisitos

Solo necesita **Docker** con **Compose v2**. Todo lo demás (Python, Flask, Redis, nginx) corre dentro de contenedores.

- **macOS / Windows:** instale [Docker Desktop](https://www.docker.com/products/docker-desktop/), que ya incluye Compose v2.
- **Ubuntu / Debian:** ejecute el script incluido y luego cierre y reabra la sesión.

  ```sh
  sh install.sh
  ```

Verifique la instalación con:

```sh
docker compose version
```

> El comando moderno es `docker compose` (sin guion). El antiguo `docker-compose` corresponde a la v1, que ya no tiene soporte.

## Ejecución

Desde la raíz del repositorio:

```sh
docker compose up --build
```

O en segundo plano, esperando a que todos los servicios queden saludables:

```sh
docker compose up -d --build --wait
```

> **La primera vez tarda varios minutos.** Docker descarga la imagen base de Python e instala las dependencias de cada servicio. Aunque la terminal parezca detenida, está compilando: no la interrumpa. Las siguientes ejecuciones son casi inmediatas gracias a la caché.

Los servicios quedan expuestos a través del API Gateway en **http://localhost:5000**.

Para revisar el estado y los logs:

```sh
docker compose ps
docker compose logs -f orders-commands
```

Para detener todo y borrar los datos (bases SQLite y cola de Redis):

```sh
docker compose down -v
```

## Verificar que todo funciona

El repositorio incluye una prueba de humo que recorre el flujo completo: crea un usuario y un producto, espera a que el worker los replique en la base de datos del servicio de órdenes, crea una orden, comprueba que el procesamiento asíncrono la marcó como `completed` y descontó el stock, y finalmente modifica el producto para verificar que la réplica se actualiza.

Con los servicios ya corriendo:

```sh
python3 smoke_test.py
```

Si prefiere no depender de Python en su máquina, puede correrla dentro de la red de Docker:

```sh
docker run --rm --network fotoalpes-examples_default \
  -v "$PWD/smoke_test.py:/smoke_test.py:ro" \
  fotoalpes-examples-users-commands python /smoke_test.py http://nginx:80
```

La prueba termina con código de salida 0 si todo está bien y 1 si algo falló, indicando qué verificación no pasó.

## Endpoints

Todas las rutas pasan por el API Gateway en `http://localhost:5000`.

### Usuarios

| Operación | Método | Ruta |
|---|---|---|
| Crear usuario | POST | `/api-commands/users` |
| Listar usuarios | GET | `/api-queries/users` |
| Consultar usuario | GET | `/api-queries/users/<id>` |

Cuerpo para crear un usuario:

```json
{ "username": "nombre_del_usuario" }
```

### Productos

| Operación | Método | Ruta |
|---|---|---|
| Crear producto | POST | `/api-commands/products` |
| Modificar producto | PUT | `/api-commands/products/<id>` |
| Listar productos | GET | `/api-queries/products` |
| Consultar producto | GET | `/api-queries/products/<id>` |

Cuerpo para crear o modificar un producto:

```json
{
  "name": "Nombre del producto",
  "description": "Descripción del producto",
  "value": 1500,
  "stock": 100
}
```

### Órdenes

| Operación | Método | Ruta |
|---|---|---|
| Crear orden | POST | `/api-commands/orders` |
| Listar órdenes | GET | `/api-queries/orders` |
| Consultar orden | GET | `/api-queries/orders/<id>` |

Cuerpo para crear una orden. Los campos `user` y `product` deben corresponder al id de un usuario y un producto **creados previamente**:

```json
{
  "user": 1,
  "product": 1,
  "quantity": 10
}
```

> La orden se crea en estado `processing` y un worker la procesa de forma asíncrona. Consúltela de nuevo unos segundos después para verla en `completed` o `failed`.

Ejemplo con `curl`:

```sh
curl -X POST http://localhost:5000/api-commands/users \
  -H 'Content-Type: application/json' \
  -d '{"username":"ana"}'
```

**Con Postman:** importe el archivo [`fotoalpes.postman_collection.json`](fotoalpes.postman_collection.json) que viene en el repositorio y tendrá todas las operaciones listas, sin escribir una sola URL. Los ids de usuario, producto y orden se guardan solos al crearlos. En [POSTMAN.md](POSTMAN.md) está el paso a paso con capturas.

## Descripción de los servicios

Al implementar el patrón CQRS, cada servicio expone sus operaciones en dos partes: comandos (`api_commands.py`) y consultas (`api_queries.py`). Cada parte corre en su propio contenedor.

### Órdenes

En `api_commands.py`:

- **Crear una nueva orden** (`OrderListResource.post`). Una vez creada, se encola el id de la orden para que sea procesada:

  ```python
  # add to queue to process order
  q.enqueue(process_order, new_order.id)
  ```

En `api_queries.py`:

- **Listar todas las órdenes** (`OrderListResource.get`).
- **Consultar una orden específica** (`OrderResource.get`).

### Productos

En `api_commands.py`:

- **Crear un nuevo producto** (`ProductListResource.post`).
- **Modificar un producto** (`ProductResource.put`).

En `api_queries.py`:

- **Listar todos los productos** (`ProductListResource.get`).
- **Consultar un producto específico** (`ProductResource.get`).

### Usuarios

En `api_commands.py`:

- **Crear un nuevo usuario** (`UserListResource.post`).

En `api_queries.py`:

- **Listar todos los usuarios** (`UserListResource.get`).
- **Consultar un usuario específico** (`UserResource.get`).

### API Gateway

Se usa la configuración de proxy de **nginx** como API Gateway. Todas las solicitudes llegan a nginx, que las redirige al servicio correspondiente según la ruta:

```
location /api-commands/users {
  proxy_pass http://users-commands:5000;
  proxy_set_header X-Real-IP  $remote_addr;
  proxy_set_header X-Forwarded-For $remote_addr;
  proxy_set_header Host $host;
}
location /api-queries/users {
  proxy_pass http://users-queries:5000;
  ...
}
```

La configuración completa está en `nginx/nginx-proxy.conf`.

## Comunicación asíncrona

En esta rama cada servicio tiene una copia de la estructura de la base de datos de los demás, por lo que hay que propagar los cambios cuando alguno actualiza su información. Para eso cada servicio usa la cola de mensajería.

Se usan **dos colas de Redis**, atendidas por dos workers distintos:

| Cola | Worker | Corre en | Responsabilidad |
|---|---|---|---|
| db `0` | `worker-orders` | contenedor de `ordenes` | Procesa órdenes y replica usuarios y productos en la BD de órdenes |
| db `1` | `worker-products` | contenedor de `productos` | Descuenta el stock en la BD de productos |

### Notificar cambios

En `api_commands.py` se publica en la cola la información del producto creado o modificado, para que los demás servicios actualicen su base de datos:

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

La actualización del stock la solicita el servicio de órdenes. En `ordenes/base.py`, la función `process_order` verifica que el producto tenga existencias suficientes, cambia el estado de la orden y publica en la segunda cola la cantidad a descontar:

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

- **Todas las versiones están fijadas**, tanto la imagen base de Python como cada dependencia en los `requirements.txt` y las imágenes de Redis y nginx. Esto es deliberado: sin fijarlas, el ejemplo deja de compilar solo con que pase el tiempo.
- Al actualizar dependencias, corra `smoke_test.py` antes de subir los cambios. La prueba verifica el flujo asíncrono completo, que es justamente lo que se rompe en silencio.
- El `docker-compose.yaml` **no define política de `restart`** a propósito: si un servicio falla, debe quedar caído y visible en `docker compose ps` en vez de reiniciarse en bucle ocultando el error.
- Las bases de datos son SQLite en archivo, compartidas por bind mount entre el contenedor de comandos y el de consultas de cada servicio. Es suficiente para el ejemplo, pero no es un diseño apto para producción.
- Los servicios corren con el servidor de desarrollo de Flask (`app.run(debug=True)`). Es adecuado para el aula, no para despliegues reales.
