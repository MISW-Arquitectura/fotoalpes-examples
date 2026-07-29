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
    respuesta = requests.get("https://jwt:5000/jwt", verify=False, timeout=10)
    respuesta.raise_for_status()
    return respuesta.json()['access_token']


def encabezados_con_token():
    return {'Authorization': f"Bearer {obtener_token()}"}


def obtener_cola(intentos=30, espera=2):
    """Consulta al ACL que cola puede usar este servicio.

    Se reintenta porque esta consulta ocurre al importar el modulo: si jwt o
    acl todavia no estan listos, el contenedor moriria al arrancar.
    """
    ultimo_error = None
    for _ in range(intentos):
        try:
            respuesta = requests.get(
                "https://acl:5000/acl/orders/orders",
                verify=False,
                headers=encabezados_con_token(),
                timeout=10,
            )
            respuesta.raise_for_status()
            return respuesta.json()['id']
        except Exception as error:
            ultimo_error = error
            time.sleep(espera)

    print(f"Queue not in ACL for this Service: {ultimo_error}", file=sys.stderr)
    sys.exit(1)


queue_name = obtener_cola()

q = Queue(connection=Redis(host='redis', port=6379, db=queue_name))


class Order(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user = db.Column(db.Integer)
    product = db.Column(db.Integer)
    quantity = db.Column(db.Integer)
    state = db.Column(db.String(100))


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
        headers = encabezados_con_token()
        product = requests.get(
            f"https://products:5000/products/{order.product}",
            verify=False,
            headers=headers,
            timeout=10,
        )
        product = product.json()
        if product['stock'] >= order.quantity:
            requests.put(
                f"https://products:5000/products/{order.product}",
                json={'stock': product['stock'] - order.quantity},
                verify=False,
                headers=headers,
                timeout=10,
            )
            order.state = "completed"
        else:
            order.state = "failed"
        db.session.commit()
