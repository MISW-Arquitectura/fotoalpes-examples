from api import app, db

# Flask-SQLAlchemy 3.x exige un contexto de aplicacion explicito.
with app.app_context():
    db.create_all()
