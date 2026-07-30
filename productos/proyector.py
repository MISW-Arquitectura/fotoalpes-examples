import os
import time

from base import app, db, Product, ProductView

# Retraso artificial de la proyeccion, en segundos. Sirve para hacer visible en
# clase la consistencia eventual.
RETRASO = float(os.environ.get('RETRASO_PROYECCION', '0'))


def proyectar_producto(product_id):
    """Actualiza el modelo de lectura a partir del de escritura.

    La ejecuta el worker de RQ, fuera del ciclo de request, por lo que abre su
    propio contexto de aplicacion.
    """
    with app.app_context():
        if RETRASO > 0:
            time.sleep(RETRASO)

        producto = db.session.get(Product, product_id)
        if producto is None:
            print(f"No existe el producto {product_id}; nada que proyectar.", flush=True)
            return

        vista = db.session.get(ProductView, product_id)
        if vista is None:
            vista = ProductView(id=producto.id)
            db.session.add(vista)

        vista.name = producto.name
        vista.description = producto.description
        vista.value = producto.value
        vista.stock = producto.stock
        # Campo derivado: se calcula al proyectar, no al consultar.
        vista.disponible = producto.stock > 0

        db.session.commit()
        print(f"Proyectado el producto {producto.id} al modelo de lectura.", flush=True)
