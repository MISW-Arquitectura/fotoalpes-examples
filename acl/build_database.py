from api import app, db, ACL

# Flask-SQLAlchemy 3.x exige un contexto de aplicacion explicito.
with app.app_context():
    db.create_all()

    # El ACL define que cola puede usar cada servicio. El id de esta fila es
    # el numero de base de datos de redis que recibe el servicio de ordenes
    # cuando consulta /acl/orders/orders.
    existe = db.session.scalars(
        db.select(ACL).filter_by(service="orders", queue="orders")
    ).first()

    if existe is None:
        db.session.add(ACL(service="orders", queue="orders"))
        db.session.commit()
