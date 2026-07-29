from api import app, db, ACL


def agregar_acl(service, queue, value):
    """Autoriza a un servicio a usar una cola, si no estaba ya autorizado."""
    existe = db.session.scalars(
        db.select(ACL).filter_by(service=service, queue=queue)
    ).first()

    if existe is None:
        db.session.add(ACL(service=service, queue=queue, value=value))
        db.session.commit()


# Flask-SQLAlchemy 3.x exige un contexto de aplicacion explicito.
with app.app_context():
    db.create_all()

    # 'value' es el numero de base de datos de redis. La cola 0 la atiende
    # worker-orders y la cola 1 worker-products (ver docker-compose.yaml).
    agregar_acl("orders", "q", 0)
    agregar_acl("orders", "q2", 1)
    agregar_acl("products", "q", 0)
    agregar_acl("users", "q", 0)
