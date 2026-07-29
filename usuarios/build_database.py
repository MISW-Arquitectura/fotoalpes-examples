from base import app, db

# Flask-SQLAlchemy 3.x exige un contexto de aplicacion explicito.
# create_all() crea las tablas de todos los binds, es decir tanto el almacen de
# escritura como el de lectura.
with app.app_context():
    db.create_all()
