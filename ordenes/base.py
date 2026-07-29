import sys
import time

from flask import Flask, request, jsonify
from flask_sqlalchemy import SQLAlchemy
from flask_marshmallow import Marshmallow
from flask_restful import Api, Resource
import requests
import urllib3
from redis import Redis
from rq import Queue
# Se importa el stub local updater.update_product solo para poder encolarlo:
# RQ serializa la referencia como "updater.update_product" y quien la ejecuta
# es worker-products, que resuelve ese nombre contra productos/updater.py.
from updater import update_product
from flask_jwt_extended import JWTManager

# Los servicios usan certificados autofirmados, por lo que las llamadas entre
# ellos van con verify=False. Silenciamos la advertencia para que no inunde los
# logs. Esto es aceptable SOLO porque es un ejemplo de aula con certificados de
# prueba; en un sistema real habria que validar la cadena de certificacion.
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:////mnt/ordenes.db'
db = SQLAlchemy(app)
ma = Marshmallow(app)
app.config["JWT_SECRET_KEY"] = "secret-jwt"  # Change this!
app.config["JWT_ACCESS_TOKEN_EXPIRES"] = False

jwt = JWTManager(app)
api = Api(app)


def obtener_token():
    """Pide un token al componente jwt."""
    respuesta = requests.get(
        "https://jwt-queries:5000/api-queries/jwt", verify=False, timeout=10
    )
    respuesta.raise_for_status()
    return respuesta.json()['access_token']


def obtener_cola(servicio, cola, intentos=30, espera=2):
    """Consulta al ACL que cola tiene autorizada este servicio.

    Se reintenta porque esta consulta ocurre al importar el modulo: si jwt o
    acl todavia no estan listos, el contenedor moriria al arrancar.
    """
    ultimo_error = None
    for _ in range(intentos):
        try:
            respuesta = requests.get(
                f"https://acl-queries:5000/api-queries/acl/{servicio}/{cola}",
                verify=False,
                headers={'Authorization': f"Bearer {obtener_token()}"},
                timeout=10,
            )
            respuesta.raise_for_status()
            return respuesta.json()['value']
        except Exception as error:
            ultimo_error = error
            time.sleep(espera)

    print(
        f"Queue {cola} not in ACL for Service {servicio}: {ultimo_error}",
        file=sys.stderr,
    )
    sys.exit(1)


# q  -> cola donde se publican las ordenes por procesar y las replicas
# q2 -> cola donde se pide al servicio de productos que descuente el stock
q = Queue(connection=Redis(host='redis', port=6379, db=obtener_cola("orders", "q")))
q2 = Queue(connection=Redis(host='redis', port=6379, db=obtener_cola("orders", "q2")))


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
