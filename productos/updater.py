from base import app, db, Product, q_proyeccion
from proyector import proyectar_producto


def update_product(data):
    # Esta funcion la ejecuta el worker de RQ, fuera del ciclo de request,
    # por lo que necesita abrir su propio contexto de aplicacion.
    with app.app_context():
        product = db.session.get(Product, data['id'])
        product.stock = product.stock - data['quantity']
        db.session.commit()

        # El stock cambio en el modelo de escritura, asi que hay que volver a
        # proyectar para que las consultas lo reflejen.
        q_proyeccion.enqueue(proyectar_producto, product.id)
