from flask import Flask, request, jsonify
from flask_sqlalchemy import SQLAlchemy
from flask_marshmallow import Marshmallow
from flask_restful import Api, Resource
import requests
from redis import Redis
from rq import Queue
# Se importa el stub local updater.update_product solo para poder encolarlo:
# RQ serializa la referencia como "updater.update_product" y quien la ejecuta
# es worker-products, que resuelve ese nombre contra productos/updater.py.
from updater import update_product


app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:////mnt/ordenes.db'
db = SQLAlchemy(app)
ma = Marshmallow(app)
api = Api(app)
q = Queue(connection=Redis(host='redis', port=6379, db=0))
q2 = Queue(connection=Redis(host='redis', port=6379, db=1))


class Order(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user = db.Column(db.Integer)
    product = db.Column(db.Integer)
    quantity = db.Column(db.Integer)
    state = db.Column(db.String(100))


class Product(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50))
    description = db.Column(db.String(200))
    value = db.Column(db.Integer)
    stock = db.Column(db.Integer)


class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), unique=True)


class OrderSchema(ma.SQLAlchemyAutoSchema):
    class Meta:
        # 'model' es obligatorio: marshmallow 4 ya no crea campos implicitos,
        # asi que sin el los nombres listados en 'fields' no existirian.
        model = Order
        fields = ("id", "user", "product", "quantity", "state")


order_schema = OrderSchema()
orders_schema = OrderSchema(many=True)


def process_order(order_id):
    # Esta funcion la ejecuta el worker de RQ, fuera del ciclo de request,
    # por lo que necesita abrir su propio contexto de aplicacion.
    with app.app_context():
        order = db.session.get(Order, order_id)
        product = db.session.get(Product, order.product)
        if product.stock >= order.quantity:
            product.stock = product.stock - order.quantity
            q2.enqueue(update_product, {
                'id': product.id,
                'quantity': order.quantity
            })
            order.state = "completed"
        else:
            order.state = "failed"
        db.session.commit()
