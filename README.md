# fotoalpes-examples — rama `sync`

Ejemplo resuelto del caso **Foto Alpes** para el curso de Arquitecturas Ágiles de Software (MISW). Esta rama muestra la **comunicación síncrona** entre microservicios: el servicio de órdenes valida al usuario y al producto consultando por HTTP a los otros dos servicios antes de aceptar una orden.

## Ramas del proyecto

| Rama | Contenido |
|---|---|
| `main` | CQRS y comunicación asíncrona |
| `sync` | Comunicación síncrona |
| `sync-sec` | Tokens JWT y certificados, con comunicación síncrona |
| `async-sec` | Tokens JWT y certificados, con comunicación asíncrona |

## Requisitos

Solo necesita **Docker** con **Compose v2**. Todo lo demás corre dentro de contenedores.

- **macOS / Windows:** instale [Docker Desktop](https://www.docker.com/products/docker-desktop/), que ya incluye Compose v2.
- **Ubuntu / Debian:** ejecute `sh install.sh` y luego cierre y reabra la sesión.

Verifique con `docker compose version`.

> El comando moderno es `docker compose` (sin guion). El antiguo `docker-compose` corresponde a la v1, que ya no tiene soporte.

## Ejecución

```sh
docker compose up --build
```

O en segundo plano, esperando a que todos los servicios queden saludables:

```sh
docker compose up -d --build --wait
```

Los servicios quedan expuestos a través del API Gateway en **http://localhost:5000**.

Para detener todo y borrar los datos:

```sh
docker compose down -v
```

## Verificar que todo funciona

Con los servicios corriendo:

```sh
python3 smoke_test.py
```

La prueba crea un usuario y un producto, crea una orden, verifica que el worker la completó y descontó el stock, y comprueba que una orden por encima del stock disponible queda en estado `failed`. Sale con código 0 si todo está bien y 1 si algo falló.

Si prefiere no depender de Python en su máquina:

```sh
docker run --rm --network fotoalpes-examples_default \
  -v "$PWD/smoke_test.py:/smoke_test.py:ro" \
  fotoalpes-examples-users python /smoke_test.py http://nginx:80
```

## Endpoints

Todas las rutas pasan por el API Gateway en `http://localhost:5000`. A diferencia de la rama `main`, aquí **no** hay separación entre comandos y consultas: cada servicio expone una sola ruta.

### Usuarios

| Operación | Método | Ruta |
|---|---|---|
| Listar usuarios | GET | `/users` |
| Crear usuario | POST | `/users` |
| Consultar usuario | GET | `/users/<id>` |

```json
{ "username": "nombre_del_usuario" }
```

### Productos

| Operación | Método | Ruta |
|---|---|---|
| Listar productos | GET | `/products` |
| Crear producto | POST | `/products` |
| Consultar producto | GET | `/products/<id>` |
| Modificar producto | PUT | `/products/<id>` |

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
| Listar órdenes | GET | `/orders` |
| Crear orden | POST | `/orders` |
| Consultar orden | GET | `/orders/<id>` |

Los campos `user` y `product` deben corresponder al id de un usuario y un producto **creados previamente**:

```json
{
  "user": 1,
  "product": 1,
  "quantity": 10
}
```

> La orden se crea en estado `processing` y un worker la procesa. Consúltela unos segundos después para verla en `completed` o `failed`.

Ejemplo con `curl`:

```sh
curl -X POST http://localhost:5000/orders \
  -H 'Content-Type: application/json' \
  -d '{"user":1,"product":1,"quantity":10}'
```

También puede usar [Postman](https://www.postman.com/downloads/).

## Descripción de los servicios

### Órdenes

Las tres operaciones están en `ordenes/api.py`:

- **Listar todas las órdenes** (`OrderListResource.get`).
- **Crear una nueva orden** (`OrderListResource.post`).
- **Consultar una orden específica** (`OrderResource.get`).

La operación que crea una orden **valida de forma síncrona** que el usuario y el producto existan, usando las operaciones de consulta que exponen los otros dos servicios:

```python
user = requests.get(f"http://users:5000/users/{request.json['user']}")
product = requests.get(f"http://products:5000/products/{request.json['product']}")
```

Este es el punto central de la rama: **el servicio de órdenes queda acoplado en tiempo de ejecución a los otros dos**. Si `users` o `products` no responden, no se puede crear ninguna orden. Compare con la rama `main`, donde la comunicación es asíncrona a través de una cola.

El procesamiento posterior de la orden sí es asíncrono y vive en `ordenes/worker.py`. La función `process_order` consulta el stock del producto y, si alcanza, lo descuenta con un PUT al servicio de productos:

```python
def process_order(order_id):
    with app.app_context():
        order = db.session.get(Order, order_id)
        product = requests.get(f"http://products:5000/products/{order.product}")
        ...
```

### Productos

Expone cuatro operaciones en `productos/api.py`: listar, crear, consultar y modificar.

### Usuarios

Expone tres operaciones en `usuarios/api.py`: listar, crear y consultar.

### API Gateway

Se usa la configuración de proxy de **nginx** como API Gateway. Todas las solicitudes llegan a nginx, que las redirige al servicio correspondiente según la ruta:

```
location /users {
  proxy_pass http://users:5000;
  proxy_set_header X-Real-IP  $remote_addr;
  proxy_set_header X-Forwarded-For $remote_addr;
  proxy_set_header Host $host;
}
location /products {
  proxy_pass http://products:5000;
  ...
}
```

La configuración completa está en `nginx/nginx-proxy.conf`.

## Notas de mantenimiento

- **Todas las versiones están fijadas**, tanto la imagen base de Python como cada dependencia en los `requirements.txt` y las imágenes de Redis y nginx. Sin eso el ejemplo deja de compilar solo con que pase el tiempo.
- Al actualizar dependencias, corra `smoke_test.py` antes de subir los cambios.
- El `docker-compose.yaml` **no define política de `restart`** a propósito: si un servicio falla, debe quedar caído y visible en `docker compose ps` en vez de reiniciarse en bucle ocultando el error.
- Las bases de datos son SQLite en archivo. Es suficiente para el ejemplo, pero no es un diseño apto para producción.
- Los servicios corren con el servidor de desarrollo de Flask (`app.run(debug=True)`). Adecuado para el aula, no para despliegues reales.
