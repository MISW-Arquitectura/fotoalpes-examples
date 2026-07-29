from flask import Flask, request
from flask_sqlalchemy import SQLAlchemy
from flask_marshmallow import Marshmallow
from flask_restful import Api, Resource
from redis import Redis
from rq import Queue
from sender import send_user

app = Flask(__name__)

# CQRS: dos almacenes distintos.
#
#   - escritura: fuente de verdad. Solo lo toca api_commands.py.
#   - lectura:   proyeccion derivada. Solo la lee api_queries.py.
#
# La proyeccion es desechable: se puede borrar y regenerar en cualquier momento
# a partir del almacen de escritura (ver reconstruir_proyeccion.py).
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:////mnt/usuarios-escritura.db'
app.config['SQLALCHEMY_BINDS'] = {
    'lectura': 'sqlite:////mnt/usuarios-lectura.db',
}

db = SQLAlchemy(app)
ma = Marshmallow(app)
api = Api(app)

# Cola 0: la atiende worker-orders. Replica el usuario hacia el servicio de
# ordenes, que necesita conocerlo para validar.
q = Queue(connection=Redis(host='redis', port=6379, db=0))

# Cola 2: la atiende worker-users, que corre esta misma imagen. Proyecta el
# usuario hacia el modelo de lectura de este servicio.
q_proyeccion = Queue(connection=Redis(host='redis', port=6379, db=2))


class User(db.Model):
    """Modelo de ESCRITURA. Es la fuente de verdad."""

    __tablename__ = 'user'

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), unique=True)


class UserView(db.Model):
    """Modelo de LECTURA. Proyeccion derivada del modelo de escritura.

    Para usuarios la forma es casi identica a la de escritura, porque la
    consulta no necesita nada mas. La diferencia se aprecia en el servicio de
    ordenes, donde el modelo de lectura si tiene otra forma.
    """

    __bind_key__ = 'lectura'
    __tablename__ = 'user_view'

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50))


class UserSchema(ma.SQLAlchemyAutoSchema):
    class Meta:
        model = User
        fields = ("id", "username")


class UserViewSchema(ma.SQLAlchemyAutoSchema):
    class Meta:
        model = UserView
        fields = ("id", "username")


user_schema = UserSchema()
user_view_schema = UserViewSchema()
users_view_schema = UserViewSchema(many=True)
