from flask import Flask, request
from flask_sqlalchemy import SQLAlchemy
from flask_marshmallow import Marshmallow
from flask_restful import Api, Resource
from redis import Redis
from rq import Queue
from sender import send_product

app = Flask(__name__)

# CQRS: dos almacenes distintos.
#
#   - escritura: fuente de verdad. Solo lo toca api_commands.py.
#   - lectura:   proyeccion derivada. Solo la lee api_queries.py.
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:////mnt/productos-escritura.db'
app.config['SQLALCHEMY_BINDS'] = {
    'lectura': 'sqlite:////mnt/productos-lectura.db',
}

db = SQLAlchemy(app)
ma = Marshmallow(app)
api = Api(app)

# Cola 0: la atiende worker-orders. Replica el producto hacia el servicio de
# ordenes, que necesita conocerlo para validar y descontar stock.
q = Queue(connection=Redis(host='redis', port=6379, db=0))

# Cola 1: la atiende worker-products, que corre esta misma imagen. Proyecta el
# producto hacia el modelo de lectura de este servicio.
q_proyeccion = Queue(connection=Redis(host='redis', port=6379, db=1))


class Product(db.Model):
    """Modelo de ESCRITURA. Es la fuente de verdad."""

    __tablename__ = 'product'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50))
    description = db.Column(db.String(200))
    value = db.Column(db.Integer)
    stock = db.Column(db.Integer)


class ProductView(db.Model):
    """Modelo de LECTURA. Proyeccion derivada del modelo de escritura.

    Agrega 'disponible', que no existe en el modelo de escritura: se calcula al
    proyectar para que la consulta no tenga que derivarlo cada vez. Es una
    denormalizacion pequena, pero ilustra la idea: el modelo de lectura guarda
    lo que la consulta necesita, no lo que la escritura necesita.
    """

    __bind_key__ = 'lectura'
    __tablename__ = 'product_view'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50))
    description = db.Column(db.String(200))
    value = db.Column(db.Integer)
    stock = db.Column(db.Integer)
    disponible = db.Column(db.Boolean)


class ProductSchema(ma.SQLAlchemyAutoSchema):
    class Meta:
        model = Product
        fields = ("id", "name", "description", "value", "stock")


class ProductViewSchema(ma.SQLAlchemyAutoSchema):
    class Meta:
        model = ProductView
        fields = ("id", "name", "description", "value", "stock", "disponible")


product_schema = ProductSchema()
product_view_schema = ProductViewSchema()
products_view_schema = ProductViewSchema(many=True)
