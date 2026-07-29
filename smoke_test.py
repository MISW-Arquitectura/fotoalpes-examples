#!/usr/bin/env python3
"""Prueba de humo end-to-end del ejemplo Foto Alpes (rama main).

Verifica el camino completo con CQRS y comunicacion asincrona:

  - que lo escrito por el lado de comandos aparezca en el modelo de lectura
    (consistencia eventual),
  - que el modelo de lectura de ordenes este denormalizado, con los nombres
    resueltos y el total precalculado,
  - que el procesamiento asincrono complete la orden y descuente el stock,
  - que modificar un producto se refleje en la replica del servicio de ordenes,
  - y que una orden por encima del stock disponible quede en 'failed'.

Solo usa la libreria estandar. Uso:

    python3 smoke_test.py [URL_BASE]

Sale con codigo 0 si todo funciona y 1 si algo falla.
"""

import json
import sys
import time
import urllib.error
import urllib.request

BASE = (sys.argv[1] if len(sys.argv) > 1 else "http://localhost:5000").rstrip("/")

STOCK_INICIAL = 100
CANTIDAD_ORDEN = 10
VALOR_PRODUCTO = 1500
# Margen amplio: cubre el retraso artificial de RETRASO_PROYECCION si se activa.
TIMEOUT_ESPERA = 45

fallos = []


def pedir(metodo, ruta, cuerpo=None):
    """Ejecuta una peticion HTTP y devuelve (codigo, json_decodificado)."""
    datos = json.dumps(cuerpo).encode() if cuerpo is not None else None
    req = urllib.request.Request(
        BASE + ruta,
        data=datos,
        method=metodo,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, json.loads(r.read() or "null")
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read() or "null")
        except ValueError:
            return e.code, None


def esperar(ruta, condicion):
    """Reintenta un GET hasta que la respuesta cumpla la condicion.

    Los reintentos no son un parche: en CQRS el modelo de lectura se actualiza
    de forma asincrona, asi que consultar justo despues de escribir puede no
    devolver nada todavia. Eso es consistencia eventual.
    """
    limite = time.time() + TIMEOUT_ESPERA
    ultimo = None
    while time.time() < limite:
        codigo, cuerpo = pedir("GET", ruta)
        ultimo = cuerpo
        if codigo == 200 and condicion(cuerpo):
            return cuerpo
        time.sleep(1)
    return ultimo


def ok(mensaje):
    print("  OK   " + mensaje)


def fallo(mensaje):
    print("  FALLA " + mensaje)
    fallos.append(mensaje)


print("Probando " + BASE)

# ---------------------------------------------------------------- usuarios
print("\n[1/8] Crear usuario y esperar su proyeccion al modelo de lectura")
nombre = "estudiante_" + str(int(time.time()))
codigo, usuario = pedir("POST", "/api-commands/users", {"username": nombre})
if codigo == 200 and isinstance(usuario, dict) and usuario.get("id"):
    ok("usuario creado en el modelo de escritura con id " + str(usuario["id"]))
else:
    fallo("no se pudo crear el usuario (HTTP " + str(codigo) + "): " + str(usuario))
    print("\nRESULTADO: FALLO")
    sys.exit(1)

vista = esperar(
    "/api-queries/users",
    lambda c: isinstance(c, list) and any(u.get("id") == usuario["id"] for u in c),
)
if isinstance(vista, list) and any(u.get("id") == usuario["id"] for u in vista):
    ok("el usuario aparece en el modelo de lectura")
else:
    fallo("el usuario nunca aparecio en el modelo de lectura: el proyector no corrio")

# --------------------------------------------------------------- productos
print("\n[2/8] Crear producto y verificar el campo derivado de la proyeccion")
codigo, producto = pedir("POST", "/api-commands/products", {
    "name": "Camara",
    "description": "Camara de prueba",
    "value": VALOR_PRODUCTO,
    "stock": STOCK_INICIAL,
})
if codigo == 200 and isinstance(producto, dict) and producto.get("id"):
    ok("producto creado en el modelo de escritura con id " + str(producto["id"]))
else:
    fallo("no se pudo crear el producto (HTTP " + str(codigo) + "): " + str(producto))
    print("\nRESULTADO: FALLO")
    sys.exit(1)

ruta_producto = "/api-queries/products/" + str(producto["id"])
vista_producto = esperar(ruta_producto, lambda c: isinstance(c, dict) and c.get("id"))

if isinstance(vista_producto, dict) and vista_producto.get("id"):
    ok("el producto aparece en el modelo de lectura")
else:
    fallo("el producto nunca aparecio en el modelo de lectura")

# 'disponible' no existe en el modelo de escritura: lo calcula el proyector.
if isinstance(vista_producto, dict) and vista_producto.get("disponible") is True:
    ok("el modelo de lectura incluye 'disponible', que el de escritura no tiene")
else:
    fallo("el modelo de lectura no calculo 'disponible': " + str(vista_producto))

# ------------------------------------------------- replicacion asincrona
print("\n[3/8] Esperar replicacion hacia el servicio de ordenes y crear la orden")
limite = time.time() + TIMEOUT_ESPERA
orden = None
while time.time() < limite:
    codigo, respuesta = pedir("POST", "/api-commands/orders", {
        "user": usuario["id"],
        "product": producto["id"],
        "quantity": CANTIDAD_ORDEN,
    })
    if codigo == 200 and isinstance(respuesta, dict) and respuesta.get("id"):
        orden = respuesta
        break
    time.sleep(1)

if orden:
    ok("usuario y producto replicados; orden creada con id " + str(orden["id"]))
else:
    fallo("la orden nunca fue aceptada: el worker no replico usuario/producto")
    print("\nRESULTADO: FALLO")
    sys.exit(1)

# La respuesta del POST viene del modelo de ESCRITURA: ids pelados.
if orden.get("product") == producto["id"] and orden.get("state") == "processing":
    ok("el modelo de escritura devuelve solo ids y estado 'processing'")
else:
    fallo("respuesta inesperada del modelo de escritura: " + str(orden))

# ----------------------------------------------- procesamiento de la orden
print("\n[4/8] Esperar a que el procesamiento complete la orden")
ruta_orden = "/api-queries/orders/" + str(orden["id"])
vista_orden = esperar(
    ruta_orden,
    lambda c: isinstance(c, dict) and c.get("state") in ("completed", "failed"),
)
estado = vista_orden.get("state") if isinstance(vista_orden, dict) else None

if estado == "completed":
    ok("la orden aparece como 'completed' en el modelo de lectura")
elif estado == "failed":
    fallo("la orden quedo en 'failed' (stock insuficiente?)")
else:
    fallo("la orden sigue en '" + str(estado) + "': no se proyecto el cambio de estado")

# ------------------------------------------------- modelo denormalizado
# Este es el punto central de CQRS en el ejemplo: el modelo de lectura tiene
# otra forma que el de escritura, con los nombres resueltos y el total ya
# calculado, de modo que la consulta no necesita joins ni llamadas a otros
# servicios.
print("\n[5/8] Verificar que el modelo de lectura de ordenes esta denormalizado")
if isinstance(vista_orden, dict):
    if vista_orden.get("user_username") == nombre:
        ok("la vista trae el nombre del usuario ('" + str(nombre) + "')")
    else:
        fallo("la vista no resolvio el nombre del usuario: "
              + str(vista_orden.get("user_username")))

    if vista_orden.get("product_name") == "Camara":
        ok("la vista trae el nombre del producto ('Camara')")
    else:
        fallo("la vista no resolvio el nombre del producto: "
              + str(vista_orden.get("product_name")))

    esperado_total = VALOR_PRODUCTO * CANTIDAD_ORDEN
    if vista_orden.get("total") == esperado_total:
        ok("la vista trae el total precalculado (" + str(esperado_total) + ")")
    else:
        fallo("total incorrecto en la vista: se esperaba " + str(esperado_total)
              + " y llego " + str(vista_orden.get("total")))
else:
    fallo("no se pudo leer la orden desde el modelo de lectura")

# ------------------------------------------------------ descuento de stock
print("\n[6/8] Verificar el descuento de stock en el modelo de lectura de productos")
esperado = STOCK_INICIAL - CANTIDAD_ORDEN
vista_producto = esperar(
    ruta_producto, lambda c: isinstance(c, dict) and c.get("stock") == esperado
)
stock = vista_producto.get("stock") if isinstance(vista_producto, dict) else None

if stock == esperado:
    ok("el stock bajo de " + str(STOCK_INICIAL) + " a " + str(stock))
else:
    fallo("se esperaba stock " + str(esperado) + " pero quedo en " + str(stock))

# ------------------------------------------- modificacion de producto (PUT)
# El PUT encola put_product, que actualiza la replica del producto en la BD de
# ordenes. Para comprobar que esa replica quedo actualizada creamos una segunda
# orden por una cantidad que solo cabe en el stock nuevo.
print("\n[7/8] Modificar producto (PUT) y verificar que la replica se actualiza")
STOCK_NUEVO = 500
CANTIDAD_GRANDE = 200

codigo, modificado = pedir("PUT", "/api-commands/products/" + str(producto["id"]), {
    "name": "Camara",
    "description": "Camara de prueba modificada",
    "value": VALOR_PRODUCTO,
    "stock": STOCK_NUEVO,
})
if codigo == 200 and isinstance(modificado, dict) and modificado.get("stock") == STOCK_NUEVO:
    ok("producto modificado, stock ahora " + str(STOCK_NUEVO))
else:
    fallo("no se pudo modificar el producto (HTTP " + str(codigo) + "): " + str(modificado))

limite = time.time() + TIMEOUT_ESPERA
orden2 = None
while time.time() < limite:
    codigo, respuesta = pedir("POST", "/api-commands/orders", {
        "user": usuario["id"],
        "product": producto["id"],
        "quantity": CANTIDAD_GRANDE,
    })
    if codigo == 200 and isinstance(respuesta, dict) and respuesta.get("id"):
        orden2 = respuesta
        break
    time.sleep(1)

if not orden2:
    fallo("no se pudo crear la segunda orden")
else:
    vista2 = esperar(
        "/api-queries/orders/" + str(orden2["id"]),
        lambda c: isinstance(c, dict) and c.get("state") in ("completed", "failed"),
    )
    estado2 = vista2.get("state") if isinstance(vista2, dict) else None
    if estado2 == "completed":
        ok("la replica en ordenes recibio el stock nuevo (put_product funciono)")
    elif estado2 == "failed":
        fallo("orden rechazada por stock: put_product no actualizo la replica en ordenes")
    else:
        fallo("la segunda orden quedo en '" + str(estado2) + "'")

# ------------------------------------------------------- orden rechazada
print("\n[8/8] Verificar que una orden sin stock suficiente queda en 'failed'")
# El paso anterior dejo un descuento en vuelo: se espera a que se estabilice
# antes de tomar la medida de referencia.
estabilizado = STOCK_NUEVO - CANTIDAD_GRANDE
vista_producto = esperar(
    ruta_producto, lambda c: isinstance(c, dict) and c.get("stock") == estabilizado
)
stock_antes = vista_producto.get("stock") if isinstance(vista_producto, dict) else None
if stock_antes != estabilizado:
    fallo("el stock no se estabilizo en " + str(estabilizado)
          + " antes de la prueba (quedo en " + str(stock_antes) + ")")

codigo, orden3 = pedir("POST", "/api-commands/orders", {
    "user": usuario["id"],
    "product": producto["id"],
    "quantity": STOCK_NUEVO * 10,
})
if codigo == 200 and isinstance(orden3, dict) and orden3.get("id"):
    vista3 = esperar(
        "/api-queries/orders/" + str(orden3["id"]),
        lambda c: isinstance(c, dict) and c.get("state") in ("completed", "failed"),
    )
    estado3 = vista3.get("state") if isinstance(vista3, dict) else None
    if estado3 == "failed":
        ok("la orden sin stock quedo correctamente en 'failed'")
    else:
        fallo("se esperaba 'failed' pero la orden quedo en '" + str(estado3) + "'")

    codigo, actual = pedir("GET", ruta_producto)
    stock_final = actual.get("stock") if isinstance(actual, dict) else None
    if stock_final == stock_antes:
        ok("el stock no se modifico por la orden rechazada")
    else:
        fallo("el stock cambio de " + str(stock_antes) + " a " + str(stock_final)
              + " tras una orden rechazada")
else:
    fallo("no se pudo crear la orden de prueba (HTTP " + str(codigo) + ")")

# ------------------------------------------------------------- resultado
print("")
if fallos:
    print("RESULTADO: FALLO (" + str(len(fallos)) + " verificacion(es))")
    for f in fallos:
        print("  - " + f)
    sys.exit(1)

print("RESULTADO: TODO OK — CQRS, proyecciones y flujo asincrono funcionan")
sys.exit(0)
