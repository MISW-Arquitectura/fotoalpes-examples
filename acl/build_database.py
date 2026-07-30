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

    # 'value' es el numero de base de datos de redis que se autoriza.
    #
    #   db 0 -> worker-orders   (imagen de ordenes)
    #   db 1 -> worker-products (imagen de productos)
    #   db 2 -> worker-users    (imagen de usuarios)
    #
    # Colas de comunicacion entre servicios:
    agregar_acl("orders", "q", 0)
    agregar_acl("orders", "q2", 1)
    agregar_acl("products", "q", 0)
    agregar_acl("users", "q", 0)

    # Colas de proyeccion (CQRS). Cada servicio proyecta su propio modelo de
    # lectura usando el worker que corre su misma imagen, porque el proyector
    # necesita los modelos de ese servicio.
    agregar_acl("orders", "proyeccion", 0)
    agregar_acl("products", "proyeccion", 1)
    agregar_acl("users", "proyeccion", 2)
