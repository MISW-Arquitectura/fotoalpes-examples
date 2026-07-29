"""Regenera el modelo de lectura a partir del de escritura.

En CQRS la proyeccion es desechable: si se corrompe, si cambia su forma o si
simplemente se quiere empezar de cero, se borra y se reconstruye desde la
fuente de verdad. Es una de las propiedades mas utiles del patron.

Uso:

    docker compose exec users-commands python reconstruir_proyeccion.py
"""

from base import app, db, User, UserView

with app.app_context():
    borrados = db.session.query(UserView).delete()
    db.session.commit()

    usuarios = db.session.scalars(db.select(User)).all()
    for usuario in usuarios:
        db.session.add(UserView(id=usuario.id, username=usuario.username))
    db.session.commit()

    print(f"Proyeccion de usuarios reconstruida: se borraron {borrados} fila(s) "
          f"y se generaron {len(usuarios)}.")
