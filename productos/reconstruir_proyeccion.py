"""Regenera el modelo de lectura a partir del de escritura.

En CQRS la proyeccion es desechable: si se corrompe, si cambia su forma o si
simplemente se quiere empezar de cero, se borra y se reconstruye desde la
fuente de verdad.

Uso:

    docker compose exec products-commands python reconstruir_proyeccion.py
"""

from base import app, db, Product, ProductView

with app.app_context():
    borrados = db.session.query(ProductView).delete()
    db.session.commit()

    productos = db.session.scalars(db.select(Product)).all()
    for producto in productos:
        db.session.add(ProductView(
            id=producto.id,
            name=producto.name,
            description=producto.description,
            value=producto.value,
            stock=producto.stock,
            disponible=producto.stock > 0,
        ))
    db.session.commit()

    print(f"Proyeccion de productos reconstruida: se borraron {borrados} fila(s) "
          f"y se generaron {len(productos)}.")
