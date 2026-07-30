"""Regenera el modelo de lectura a partir del de escritura.

En CQRS la proyeccion es desechable: si se corrompe, si cambia su forma o si
simplemente se quiere empezar de cero, se borra y se reconstruye desde la
fuente de verdad.

Uso:

    docker compose exec orders-commands python reconstruir_proyeccion.py
"""

from base import app, db, Order, OrderView, Product, User

with app.app_context():
    borrados = db.session.query(OrderView).delete()
    db.session.commit()

    ordenes = db.session.scalars(db.select(Order)).all()
    for orden in ordenes:
        usuario = db.session.get(User, orden.user)
        producto = db.session.get(Product, orden.product)
        db.session.add(OrderView(
            id=orden.id,
            user_id=orden.user,
            user_username=usuario.username if usuario else None,
            product_id=orden.product,
            product_name=producto.name if producto else None,
            product_value=producto.value if producto else None,
            quantity=orden.quantity,
            total=producto.value * orden.quantity if producto else None,
            state=orden.state,
        ))
    db.session.commit()

    print(f"Proyeccion de ordenes reconstruida: se borraron {borrados} fila(s) "
          f"y se generaron {len(ordenes)}.")
