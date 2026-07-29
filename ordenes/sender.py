from base import app, db, Product, User


# Estas funciones las ejecuta el worker de RQ, fuera del ciclo de request,
# por lo que necesitan abrir su propio contexto de aplicacion.

def send_product(product_data):
    with app.app_context():
        product = Product(
            id=product_data['id'],
            name=product_data['name'],
            description=product_data['description'],
            value=product_data['value'],
            stock=product_data['stock'],
        )
        db.session.add(product)
        db.session.commit()


def send_user(user_data):
    with app.app_context():
        user = User(
            id=user_data['id'],
            username=user_data['username'],
        )
        db.session.add(user)
        db.session.commit()
