from base import app, db, Product


def put_product(data):
    # Esta funcion la ejecuta el worker de RQ, fuera del ciclo de request,
    # por lo que necesita abrir su propio contexto de aplicacion.
    with app.app_context():
        product = db.session.get(Product, data['id'])
        product.stock = data['stock']
        product.description = data['description']
        product.value = data['value']
        db.session.commit()
