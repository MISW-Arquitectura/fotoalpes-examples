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
docker compose logs -f worker-orders
```

Para detener todo y borrar los datos (bases SQLite y cola de Redis):

```sh
docker compose down -v
```

## Verificar que todo funciona

Con los servicios ya corriendo:

```sh
python3 smoke_test.py
```

La prueba recorre el flujo completo y verifica, entre otras cosas, que la proyección al modelo de lectura ocurra, que la vista de órdenes venga denormalizada y que el stock se descuente. Termina con código 0 si todo está bien y 1 si algo falló, indicando qué verificación no pasó.

Si prefiere no depender de Python en su máquina:

```sh
docker run --rm --network fotoalpes-examples_default \
  -v "$PWD/smoke_test.py:/smoke_test.py:ro" \
  fotoalpes-examples-users-commands python /smoke_test.py http://nginx:80
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

## La proyección

Cada escritura encola un trabajo que actualiza el modelo de lectura. En `api_commands.py`:

```python
db.session.add(new_user)
db.session.commit()                                   # modelo de escritura
q_proyeccion.enqueue(proyectar_usuario, new_user.id)  # modelo de lectura
```

El proyector (`proyector.py` de cada servicio) lee del modelo de escritura y escribe el de lectura. Se vuelve a encolar **cada vez que cambia algo**: al crear, al modificar un producto, y cuando `process_order` cambia el estado de la orden.

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

Todas las rutas pasan por el API Gateway en `http://localhost:5000`.

### Usuarios

| Operación | Método | Ruta | Modelo |
|---|---|---|---|
| Crear usuario | POST | `/api-commands/users` | escritura |
| Listar usuarios | GET | `/api-queries/users` | lectura |
| Consultar usuario | GET | `/api-queries/users/<id>` | lectura |

```json
{ "username": "nombre_del_usuario" }
```

### Productos

| Operación | Método | Ruta | Modelo |
|---|---|---|---|
| Crear producto | POST | `/api-commands/products` | escritura |
| Modificar producto | PUT | `/api-commands/products/<id>` | escritura |
| Listar productos | GET | `/api-queries/products` | lectura |
| Consultar producto | GET | `/api-queries/products/<id>` | lectura |

```json
{
  "name": "Nombre del producto",
  "description": "Descripción del producto",
  "value": 1500,
  "stock": 100
}
```

La consulta devuelve además el campo derivado `disponible`.

### Órdenes

| Operación | Método | Ruta | Modelo |
|---|---|---|---|
| Crear orden | POST | `/api-commands/orders` | escritura |
| Listar órdenes | GET | `/api-queries/orders` | lectura |
| Consultar orden | GET | `/api-queries/orders/<id>` | lectura |

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
curl -X POST http://localhost:5000/api-commands/users \
  -H 'Content-Type: application/json' \
  -d '{"username":"ana"}'
```

**Con Postman:** importe el archivo [`fotoalpes.postman_collection.json`](fotoalpes.postman_collection.json) que viene en el repositorio y tendrá todas las operaciones listas, sin escribir una sola URL. Los ids de usuario, producto y orden se guardan solos al crearlos. En [POSTMAN.md](POSTMAN.md) está el paso a paso con capturas.

## Comunicación asíncrona

Se usan **tres colas de Redis**, atendidas por tres workers distintos:

| Cola | Worker | Corre en | Responsabilidad |
|---|---|---|---|
| db `0` | `worker-orders` | imagen de `ordenes` | Procesa órdenes, recibe las réplicas de usuarios y productos, y proyecta las órdenes |
| db `1` | `worker-products` | imagen de `productos` | Descuenta el stock y proyecta los productos |
| db `2` | `worker-users` | imagen de `usuarios` | Proyecta los usuarios |

Conviven **dos mecanismos asíncronos distintos**, y conviene no confundirlos:

1. **Replicación entre servicios.** El servicio de órdenes mantiene copias locales de usuarios y productos porque las necesita para validar. Eso lo hacen `sender.py` y `putter.py`.
2. **Proyección dentro de un servicio.** Cada servicio mantiene su propio modelo de lectura a partir de su modelo de escritura. Eso lo hace `proyector.py`. **Esto es CQRS**; lo anterior no.

### Notificar cambios entre servicios

En `api_commands.py` se publica la información del producto creado o modificado:

```python
q.enqueue(send_product, product_schema.dump(new_product))
q.enqueue(put_product, product_schema.dump(product))
```

### Actualizar el stock

La actualización la solicita el servicio de órdenes. En `ordenes/base.py`, `process_order` verifica las existencias, cambia el estado y publica en la segunda cola la cantidad a descontar:

```python
q2.enqueue(update_product, {'id': product.id, 'quantity': order.quantity})
```

> **Detalle importante:** `ordenes/base.py` importa un `update_product` local que no hace nada (`ordenes/updater.py`). Ese *stub* existe solo para poder encolar la referencia: RQ la serializa como `updater.update_product` y quien la ejecuta es `worker-products`, que resuelve ese nombre contra `productos/updater.py`. Es decir, **la función que se importa no es la que se ejecuta**. Los proyectores, en cambio, sí se ejecutan en su propio servicio.

## API Gateway

Se usa la configuración de proxy de **nginx** como API Gateway:

```
location /api-commands/users {
  set $destino users-commands;
  proxy_pass http://$destino:5000$request_uri;
  ...
}
location /api-queries/users {
  set $destino users-queries;
  proxy_pass http://$destino:5000$request_uri;
  ...
}
```

El `resolver` y la variable en `proxy_pass` no son adorno: sin ellos nginx resuelve los nombres una sola vez al arrancar, y al recrear contenedores puede terminar enviando una ruta al servicio equivocado. La configuración completa está en `nginx/nginx-proxy.conf`.

## Notas de mantenimiento

- **Todas las versiones están fijadas**, tanto la imagen base de Python como cada dependencia en los `requirements.txt` y las imágenes de Redis y nginx. Sin eso el ejemplo deja de compilar solo con que pase el tiempo.
- Al actualizar dependencias, corra `smoke_test.py` antes de subir los cambios.
- El `docker-compose.yaml` **no define política de `restart`** a propósito: si un servicio falla, debe quedar caído y visible en `docker compose ps` en vez de reiniciarse en bucle ocultando el error.
- Si el proyector se cae, las consultas siguen respondiendo **con datos viejos y sin error**. Es lo que pasaría en un sistema real, pero al depurar conviene revisar `docker compose logs worker-users` antes de sospechar del código de consultas.
- Los servicios corren con el servidor de desarrollo de Flask (`app.run(debug=True)`). Adecuado para el aula, no para despliegues reales.
