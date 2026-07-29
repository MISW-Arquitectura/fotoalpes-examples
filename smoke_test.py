#!/usr/bin/env python3
"""Prueba de humo end-to-end del ejemplo Foto Alpes (rama async-sec).

Verifica el camino completo con CQRS, comunicacion asincrona y seguridad:
obtener un token del componente jwt, comprobar que los servicios rechazan las
peticiones sin token, crear usuario y producto, esperar a que el worker los
replique en la BD de ordenes, crear una orden, comprobar que el procesamiento
asincrono la completo y descontó el stock, modificar el producto para verificar
que la replica se actualiza, y comprobar que una orden por encima del stock
disponible queda en 'failed'.

Todo el trafico va por HTTPS con un certificado autofirmado, por lo que la
verificacion del certificado se desactiva a proposito.

Solo usa la libreria estandar. Uso:

    python3 smoke_test.py [URL_BASE]

Sale con codigo 0 si todo funciona y 1 si algo falla.
"""

import json
import ssl
import sys
import time
import urllib.error
import urllib.request

BASE = (sys.argv[1] if len(sys.argv) > 1 else "https://localhost:5000").rstrip("/")

STOCK_INICIAL = 100
CANTIDAD_ORDEN = 10
TIMEOUT_ESPERA = 30  # segundos que esperamos por el procesamiento asincrono

# Certificado autofirmado: no tiene sentido validarlo en este ejemplo.
CONTEXTO_SSL = ssl.create_default_context()
CONTEXTO_SSL.check_hostname = False
CONTEXTO_SSL.verify_mode = ssl.CERT_NONE

fallos = []


def pedir(metodo, ruta, cuerpo=None, token=None):
    """Ejecuta una peticion HTTPS y devuelve (codigo, json_decodificado)."""
    datos = json.dumps(cuerpo).encode() if cuerpo is not None else None
    cabeceras = {"Content-Type": "application/json"}
    if token:
        cabeceras["Authorization"] = "Bearer " + token

    req = urllib.request.Request(BASE + ruta, data=datos, method=metodo, headers=cabeceras)
    try:
        with urllib.request.urlopen(req, timeout=15, context=CONTEXTO_SSL) as r:
            return r.status, json.loads(r.read() or "null")
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read() or "null")
        except ValueError:
            return e.code, None


def ok(mensaje):
    print("  OK   " + mensaje)


def fallo(mensaje):
    print("  FALLA " + mensaje)
    fallos.append(mensaje)


print("Probando " + BASE)

# ------------------------------------------------------------------- jwt
print("\n[1/7] Obtener token del componente jwt")
codigo, respuesta = pedir("GET", "/api-queries/jwt")
token = respuesta.get("access_token") if isinstance(respuesta, dict) else None
if codigo == 200 and token:
    ok("token obtenido")
else:
    fallo("no se pudo obtener el token (HTTP " + str(codigo) + "): " + str(respuesta))
    print("\nRESULTADO: FALLO")
    sys.exit(1)

# ------------------------------------------------------------- seguridad
print("\n[2/7] Verificar que los servicios exigen token")
codigo, _ = pedir("GET", "/api-queries/users")
if codigo == 401:
    ok("sin token, /api-queries/users responde 401 como se espera")
else:
    fallo("sin token se esperaba 401 pero respondio " + str(codigo))

# ---------------------------------------------------------------- usuarios
print("\n[3/7] Crear usuario")
nombre = "estudiante_" + str(int(time.time()))
codigo, usuario = pedir("POST", "/api-commands/users", {"username": nombre}, token=token)
if codigo == 200 and isinstance(usuario, dict) and usuario.get("id"):
    ok("usuario creado con id " + str(usuario["id"]))
else:
    fallo("no se pudo crear el usuario (HTTP " + str(codigo) + "): " + str(usuario))
    print("\nRESULTADO: FALLO")
    sys.exit(1)

codigo, listado = pedir("GET", "/api-queries/users", token=token)
if codigo == 200 and any(u.get("id") == usuario["id"] for u in listado):
    ok("el usuario aparece en la consulta")
else:
    fallo("el usuario no aparece en /api-queries/users")

# --------------------------------------------------------------- productos
print("\n[4/7] Crear producto")
codigo, producto = pedir("POST", "/api-commands/products", {
    "name": "Camara",
    "description": "Camara de prueba",
    "value": 1500,
    "stock": STOCK_INICIAL,
}, token=token)
if codigo == 200 and isinstance(producto, dict) and producto.get("id"):
    ok("producto creado con id " + str(producto["id"]) + " y stock " + str(producto["stock"]))
else:
    fallo("no se pudo crear el producto (HTTP " + str(codigo) + "): " + str(producto))
    print("\nRESULTADO: FALLO")
    sys.exit(1)

# ------------------------------------------------- replicacion asincrona
# El servicio de ordenes solo acepta la orden cuando el worker ya replico el
# usuario y el producto en su propia BD, asi que reintentamos hasta lograrlo.
print("\n[5/7] Esperar replicacion, crear orden y verificar el descuento de stock")
limite = time.time() + TIMEOUT_ESPERA
orden = None
while time.time() < limite:
    codigo, respuesta = pedir("POST", "/api-commands/orders", {
        "user": usuario["id"],
        "product": producto["id"],
        "quantity": CANTIDAD_ORDEN,
    }, token=token)
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

# El campo 'product' del schema estaba mal escrito ('prodcut') y desaparecia
# de la respuesta. Verificamos que ahora si viaje.
if orden.get("product") == producto["id"]:
    ok("la orden expone correctamente el campo 'product'")
else:
    fallo("la orden no expone 'product' correctamente: " + str(orden))

limite = time.time() + TIMEOUT_ESPERA
estado = orden.get("state")
while time.time() < limite:
    codigo, actual = pedir("GET", "/api-queries/orders/" + str(orden["id"]), token=token)
    estado = actual.get("state") if isinstance(actual, dict) else None
    if estado in ("completed", "failed"):
        break
    time.sleep(1)

if estado == "completed":
    ok("la orden paso a estado 'completed'")
else:
    fallo("se esperaba 'completed' pero la orden quedo en '" + str(estado) + "'")

esperado = STOCK_INICIAL - CANTIDAD_ORDEN
limite = time.time() + TIMEOUT_ESPERA
stock = None
while time.time() < limite:
    codigo, actual = pedir("GET", "/api-queries/products/" + str(producto["id"]), token=token)
    stock = actual.get("stock") if isinstance(actual, dict) else None
    if stock == esperado:
        break
    time.sleep(1)

if stock == esperado:
    ok("el stock bajo de " + str(STOCK_INICIAL) + " a " + str(stock))
else:
    fallo("se esperaba stock " + str(esperado) + " pero quedo en " + str(stock))

# ------------------------------------------- modificacion de producto (PUT)
# El PUT encola put_product, que actualiza la replica del producto en la BD de
# ordenes. Para comprobar que esa replica quedo actualizada creamos una segunda
# orden por una cantidad que solo cabe en el stock nuevo: si la replica no se
# hubiera actualizado, process_order la marcaria como 'failed'.
print("\n[6/7] Modificar producto (PUT) y verificar que la replica se actualiza")
STOCK_NUEVO = 500
CANTIDAD_GRANDE = 200

codigo, modificado = pedir("PUT", "/api-commands/products/" + str(producto["id"]), {
    "name": "Camara",
    "description": "Camara de prueba modificada",
    "value": 1800,
    "stock": STOCK_NUEVO,
}, token=token)
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
    }, token=token)
    if codigo == 200 and isinstance(respuesta, dict) and respuesta.get("id"):
        orden2 = respuesta
        break
    time.sleep(1)

if not orden2:
    fallo("no se pudo crear la segunda orden")
else:
    limite = time.time() + TIMEOUT_ESPERA
    estado2 = None
    while time.time() < limite:
        codigo, actual = pedir("GET", "/api-queries/orders/" + str(orden2["id"]), token=token)
        estado2 = actual.get("state") if isinstance(actual, dict) else None
        if estado2 in ("completed", "failed"):
            break
        time.sleep(1)

    if estado2 == "completed":
        ok("la replica en ordenes recibio el stock nuevo (put_product funciono)")
    elif estado2 == "failed":
        fallo("orden rechazada por stock: put_product no actualizo la replica en ordenes")
    else:
        fallo("la segunda orden quedo en '" + str(estado2) + "'")

# ------------------------------------------------------- orden rechazada
# Verifica la rama 'else' de process_order: si no hay stock suficiente la orden
# debe quedar en 'failed' y el stock no debe moverse.
print("\n[7/7] Verificar que una orden sin stock suficiente queda en 'failed'")
stock_antes = None
codigo, actual = pedir("GET", "/api-queries/products/" + str(producto["id"]), token=token)
if isinstance(actual, dict):
    stock_antes = actual.get("stock")

codigo, orden3 = pedir("POST", "/api-commands/orders", {
    "user": usuario["id"],
    "product": producto["id"],
    "quantity": STOCK_NUEVO * 10,
}, token=token)
if codigo == 200 and isinstance(orden3, dict) and orden3.get("id"):
    limite = time.time() + TIMEOUT_ESPERA
    estado3 = None
    while time.time() < limite:
        codigo, actual = pedir("GET", "/api-queries/orders/" + str(orden3["id"]), token=token)
        estado3 = actual.get("state") if isinstance(actual, dict) else None
        if estado3 in ("completed", "failed"):
            break
        time.sleep(1)

    if estado3 == "failed":
        ok("la orden sin stock quedo correctamente en 'failed'")
    else:
        fallo("se esperaba 'failed' pero la orden quedo en '" + str(estado3) + "'")

    codigo, actual = pedir("GET", "/api-queries/products/" + str(producto["id"]), token=token)
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

print("RESULTADO: TODO OK — el flujo asincrono y la seguridad funcionan")
sys.exit(0)
