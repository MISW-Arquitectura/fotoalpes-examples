#!/usr/bin/env python3
"""Prueba de humo end-to-end del ejemplo Foto Alpes (rama sync-sec).

Ademas del flujo funcional, verifica la parte de seguridad: que el componente
jwt entregue un token, que los servicios rechacen las peticiones sin token y
que el ACL responda que cola puede usar el servicio de ordenes.

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


def esperar_estado(order_id, token):
    """Espera a que el worker deje la orden en 'completed' o 'failed'."""
    limite = time.time() + TIMEOUT_ESPERA
    estado = None
    while time.time() < limite:
        codigo, actual = pedir("GET", "/orders/" + str(order_id), token=token)
        estado = actual.get("state") if isinstance(actual, dict) else None
        if estado in ("completed", "failed"):
            return estado
        time.sleep(1)
    return estado


def ok(mensaje):
    print("  OK   " + mensaje)


def fallo(mensaje):
    print("  FALLA " + mensaje)
    fallos.append(mensaje)


print("Probando " + BASE)

# ------------------------------------------------------------------- jwt
print("\n[1/6] Obtener token del componente jwt")
codigo, respuesta = pedir("GET", "/jwt")
token = respuesta.get("access_token") if isinstance(respuesta, dict) else None
if codigo == 200 and token:
    ok("token obtenido")
else:
    fallo("no se pudo obtener el token (HTTP " + str(codigo) + "): " + str(respuesta))
    print("\nRESULTADO: FALLO")
    sys.exit(1)

# ------------------------------------------------------------- seguridad
print("\n[2/6] Verificar que los servicios exigen token")
codigo, _ = pedir("GET", "/users")
if codigo == 401:
    ok("sin token, /users responde 401 como se espera")
else:
    fallo("sin token se esperaba 401 pero /users respondio " + str(codigo))

codigo, acl = pedir("GET", "/acl/orders/orders", token=token)
if codigo == 200 and isinstance(acl, dict) and acl.get("id"):
    ok("el ACL asigna la cola numero " + str(acl["id"]) + " al servicio de ordenes")
else:
    fallo("el ACL no respondio correctamente (HTTP " + str(codigo) + "): " + str(acl))

# ---------------------------------------------------------------- usuarios
print("\n[3/6] Crear usuario")
nombre = "estudiante_" + str(int(time.time()))
codigo, usuario = pedir("POST", "/users", {"username": nombre}, token=token)
if codigo == 200 and isinstance(usuario, dict) and usuario.get("id"):
    ok("usuario creado con id " + str(usuario["id"]))
else:
    fallo("no se pudo crear el usuario (HTTP " + str(codigo) + "): " + str(usuario))
    print("\nRESULTADO: FALLO")
    sys.exit(1)

# --------------------------------------------------------------- productos
print("\n[4/6] Crear producto")
codigo, producto = pedir("POST", "/products", {
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

# ------------------------------------------------------------ crear orden
print("\n[5/6] Crear orden y verificar el descuento de stock")
codigo, orden = pedir("POST", "/orders", {
    "user": usuario["id"],
    "product": producto["id"],
    "quantity": CANTIDAD_ORDEN,
}, token=token)
if codigo == 200 and isinstance(orden, dict) and orden.get("id"):
    ok("orden creada con id " + str(orden["id"]))
else:
    fallo("no se pudo crear la orden (HTTP " + str(codigo) + "): " + str(orden))
    print("\nRESULTADO: FALLO")
    sys.exit(1)

# El campo 'product' del schema estaba mal escrito ('prodcut') y desaparecia
# de la respuesta. Verificamos que ahora si viaje.
if orden.get("product") == producto["id"]:
    ok("la orden expone correctamente el campo 'product'")
else:
    fallo("la orden no expone 'product' correctamente: " + str(orden))

estado = esperar_estado(orden["id"], token)
if estado == "completed":
    ok("la orden paso a estado 'completed'")
else:
    fallo("se esperaba 'completed' pero la orden quedo en '" + str(estado) + "'")

esperado = STOCK_INICIAL - CANTIDAD_ORDEN
limite = time.time() + TIMEOUT_ESPERA
stock = None
while time.time() < limite:
    codigo, actual = pedir("GET", "/products/" + str(producto["id"]), token=token)
    stock = actual.get("stock") if isinstance(actual, dict) else None
    if stock == esperado:
        break
    time.sleep(1)

if stock == esperado:
    ok("el stock bajo de " + str(STOCK_INICIAL) + " a " + str(stock))
else:
    fallo("se esperaba stock " + str(esperado) + " pero quedo en " + str(stock))

# ------------------------------------------------------- orden rechazada
print("\n[6/6] Verificar que una orden sin stock suficiente queda en 'failed'")
codigo, orden_grande = pedir("POST", "/orders", {
    "user": usuario["id"],
    "product": producto["id"],
    "quantity": STOCK_INICIAL * 10,
}, token=token)
if codigo == 200 and isinstance(orden_grande, dict) and orden_grande.get("id"):
    estado_grande = esperar_estado(orden_grande["id"], token)
    if estado_grande == "failed":
        ok("la orden sin stock quedo correctamente en 'failed'")
    else:
        fallo("se esperaba 'failed' pero la orden quedo en '" + str(estado_grande) + "'")

    codigo, actual = pedir("GET", "/products/" + str(producto["id"]), token=token)
    stock_final = actual.get("stock") if isinstance(actual, dict) else None
    if stock_final == esperado:
        ok("el stock no se modifico por la orden rechazada")
    else:
        fallo("el stock cambio a " + str(stock_final) + " tras una orden rechazada")
else:
    fallo("no se pudo crear la orden de prueba (HTTP " + str(codigo) + ")")

# ------------------------------------------------------------- resultado
print("")
if fallos:
    print("RESULTADO: FALLO (" + str(len(fallos)) + " verificacion(es))")
    for f in fallos:
        print("  - " + f)
    sys.exit(1)

print("RESULTADO: TODO OK — el flujo completo y la seguridad funcionan")
sys.exit(0)
