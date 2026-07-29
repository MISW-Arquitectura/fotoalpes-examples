import os
import time

from base import app, db, Order, OrderView, Product, User

# Retraso artificial de la proyeccion, en segundos. Sirve para hacer visible en
# clase la consistencia eventual.
RETRASO = float(os.environ.get('RETRASO_PROYECCION', '0'))


def proyectar_orden(order_id):
    """Construye la vista denormalizada de una orden.

    Lee del modelo de escritura (la orden y las replicas de usuario y producto)
    y escribe una unica fila en el modelo de lectura, con los nombres ya
    resueltos y el total ya calculado.

    La ejecuta el worker de RQ, fuera del ciclo de request, por lo que abre su
    propio contexto de aplicacion.
    """
    with app.app_context():
        if RETRASO > 0:
            time.sleep(RETRASO)

        orden = db.session.get(Order, order_id)
        if orden is None:
            print(f"No existe la orden {order_id}; nada que proyectar.", flush=True)
            return

        usuario = db.session.get(User, orden.user)
        producto = db.session.get(Product, orden.product)

        vista = db.session.get(OrderView, order_id)
        if vista is None:
            vista = OrderView(id=orden.id)
            db.session.add(vista)

        vista.user_id = orden.user
        vista.user_username = usuario.username if usuario else None
        vista.product_id = orden.product
        vista.product_name = producto.name if producto else None
        vista.product_value = producto.value if producto else None
        vista.quantity = orden.quantity
        # Campo derivado: se calcula al proyectar, no al consultar.
        vista.total = producto.value * orden.quantity if producto else None
        vista.state = orden.state

        db.session.commit()
        print(f"Proyectada la orden {orden.id} en estado '{orden.state}'.", flush=True)
