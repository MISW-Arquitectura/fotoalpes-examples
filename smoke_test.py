#!/usr/bin/env python3
"""Prueba de humo end-to-end del ejemplo Foto Alpes (rama sync).

Verifica el camino completo: crear usuario y producto, crear una orden (que el
servicio de ordenes valida consultando por HTTP a los otros dos servicios),
comprobar que el worker la completo y descontó el stock, y que una orden por
encima del stock disponible queda en estado 'failed'.

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
TIMEOUT_ESPERA = 30  # segundos que esperamos por el procesamiento asincrono

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
        return e.code, json.loads(e.read() or "null")


def esperar_estado(order_id):
    """Espera a que el worker deje la orden en 'completed' o 'failed'."""
    limite = time.time() + TIMEOUT_ESPERA
    while time.time() < limite:
        codigo, actual = pedir("GET", "/orders/" + str(order_id))
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

# ---------------------------------------------------------------- usuarios
print("\n[1/6] Crear usuario")
nombre = "estudiante_" + str(int(time.time()))
codigo, usuario = pedir("POST", "/users", {"username": nombre})
if codigo == 200 and isinstance(usuario, dict) and usuario.get("id"):
    ok("usuario creado con id " + str(usuario["id"]))
else:
    fallo("no se pudo crear el usuario (HTTP " + str(codigo) + "): " + str(usuario))
    print("\nRESULTADO: FALLO")
    sys.exit(1)

codigo, listado = pedir("GET", "/users")
if codigo == 200 and any(u.get("id") == usuario["id"] for u in listado):
    ok("el usuario aparece en la consulta")
else:
    fallo("el usuario no aparece en /users")

# --------------------------------------------------------------- productos
print("\n[2/6] Crear producto")
codigo, producto = pedir("POST", "/products", {
    "name": "Camara",
    "description": "Camara de prueba",
    "value": 1500,
    "stock": STOCK_INICIAL,
})
if codigo == 200 and isinstance(producto, dict) and producto.get("id"):
    ok("producto creado con id " + str(producto["id"]) + " y stock " + str(producto["stock"]))
else:
    fallo("no se pudo crear el producto (HTTP " + str(codigo) + "): " + str(producto))
    print("\nRESULTADO: FALLO")
    sys.exit(1)

# ------------------------------------------------------------ crear orden
# La validacion es sincrona: el servicio de ordenes consulta por HTTP a los
# servicios de usuarios y productos antes de aceptar la orden.
print("\n[3/6] Crear orden (validacion sincrona contra usuarios y productos)")
codigo, orden = pedir("POST", "/orders", {
    "user": usuario["id"],
    "product": producto["id"],
    "quantity": CANTIDAD_ORDEN,
})
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

# ----------------------------------------------- procesamiento de la orden
print("\n[4/6] Esperar procesamiento asincrono de la orden")
estado = esperar_estado(orden["id"])
if estado == "completed":
    ok("la orden paso a estado 'completed'")
elif estado == "failed":
    fallo("la orden quedo en 'failed' (stock insuficiente?)")
else:
    fallo("la orden sigue en '" + str(estado) + "': el worker no la proceso")

# ------------------------------------------------------ descuento de stock
print("\n[5/6] Verificar descuento de stock en el servicio de productos")
esperado = STOCK_INICIAL - CANTIDAD_ORDEN
limite = time.time() + TIMEOUT_ESPERA
stock = None
while time.time() < limite:
    codigo, actual = pedir("GET", "/products/" + str(producto["id"]))
    stock = actual.get("stock") if isinstance(actual, dict) else None
    if stock == esperado:
        break
    time.sleep(1)

if stock == esperado:
    ok("el stock bajo de " + str(STOCK_INICIAL) + " a " + str(stock))
else:
    fallo("se esperaba stock " + str(esperado) + " pero quedo en " + str(stock))

# ------------------------------------------------------- orden rechazada
# Verifica la rama 'else' de process_order: si no hay stock suficiente la
# orden debe quedar en 'failed' y el stock no debe moverse.
print("\n[6/6] Verificar que una orden sin stock suficiente queda en 'failed'")
codigo, orden_grande = pedir("POST", "/orders", {
    "user": usuario["id"],
    "product": producto["id"],
    "quantity": STOCK_INICIAL * 10,
})
if codigo == 200 and isinstance(orden_grande, dict) and orden_grande.get("id"):
    estado_grande = esperar_estado(orden_grande["id"])
    if estado_grande == "failed":
        ok("la orden sin stock quedo correctamente en 'failed'")
    else:
        fallo("se esperaba 'failed' pero la orden quedo en '" + str(estado_grande) + "'")

    codigo, actual = pedir("GET", "/products/" + str(producto["id"]))
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

print("RESULTADO: TODO OK — el flujo completo funciona")
sys.exit(0)
