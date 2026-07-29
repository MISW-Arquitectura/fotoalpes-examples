import os
import time

from base import app, db, User, UserView

# Retraso artificial de la proyeccion, en segundos. Sirve para hacer visible en
# clase la consistencia eventual: con RETRASO_PROYECCION=5, un usuario recien
# creado tarda cinco segundos en aparecer en las consultas.
RETRASO = float(os.environ.get('RETRASO_PROYECCION', '0'))


def proyectar_usuario(user_id):
    """Actualiza el modelo de lectura a partir del de escritura.

    La ejecuta el worker de RQ, fuera del ciclo de request, por lo que abre su
    propio contexto de aplicacion.
    """
    with app.app_context():
        if RETRASO > 0:
            time.sleep(RETRASO)

        usuario = db.session.get(User, user_id)
        if usuario is None:
            print(f"No existe el usuario {user_id}; no hay nada que proyectar.", flush=True)
            return

        vista = db.session.get(UserView, user_id)
        if vista is None:
            vista = UserView(id=usuario.id)
            db.session.add(vista)

        vista.username = usuario.username
        db.session.commit()
        print(f"Proyectado el usuario {usuario.id} al modelo de lectura.", flush=True)
