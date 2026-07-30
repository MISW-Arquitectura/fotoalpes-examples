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

# CQRS: dos almacenes distintos.
#
#   - escritura: fuente de verdad. Solo lo toca api_commands.py.
#   - lectura:   proyeccion derivada. Solo la lee api_queries.py.
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:////mnt/ordenes-escritura.db'
app.config['SQLALCHEMY_BINDS'] = {
    'lectura': 'sqlite:////mnt/ordenes-lectura.db',
}

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


# q  -> ordenes por procesar y replicas que llegan de los otros servicios
# q2 -> se pide al servicio de productos que descuente el stock
# q_proyeccion -> proyecta las ordenes hacia el modelo de lectura
q = Queue(connection=Redis(host='redis', port=6379, db=obtener_cola("orders", "q")))
q2 = Queue(connection=Redis(host='redis', port=6379, db=obtener_cola("orders", "q2")))
q_proyeccion = Queue(
    connection=Redis(host='redis', port=6379, db=obtener_cola("orders", "proyeccion"))
)


# --------------------------------------------------------------- escritura

class Order(db.Model):
    """Modelo de ESCRITURA. Normalizado y minimo: solo lo necesario para
    decidir si la orden es valida y en que estado esta."""

    __tablename__ = 'order'

    id = db.Column(db.Integer, primary_key=True)
    user = db.Column(db.Integer)
    product = db.Column(db.Integer)
    quantity = db.Column(db.Integer)
    state = db.Column(db.String(100))


class Product(db.Model):
    """Replica local del producto, mantenida por la cola. El lado de escritura
    la necesita para validar la orden y verificar el stock."""

    __tablename__ = 'product'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50))
    description = db.Column(db.String(200))
    value = db.Column(db.Integer)
    stock = db.Column(db.Integer)


class User(db.Model):
    """Replica local del usuario, mantenida por la cola."""

    __tablename__ = 'user'

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), unique=True)


# ----------------------------------------------------------------- lectura

class OrderView(db.Model):
    """Modelo de LECTURA, denormalizado.

    Aqui se ve por que existe CQRS. El modelo de escritura guarda solo los ids
    del usuario y del producto, que es lo que necesita para decidir. El de
    lectura guarda ademas sus nombres, el valor unitario y el total ya
    calculado, porque eso es lo que la consulta necesita responder.

    Consecuencia: GET /api-queries/orders/<id> se resuelve leyendo UNA fila,
    sin joins y sin llamar a ningun otro servicio.
    """

    __bind_key__ = 'lectura'
    __tablename__ = 'order_view'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer)
    user_username = db.Column(db.String(50))
    product_id = db.Column(db.Integer)
    product_name = db.Column(db.String(50))
    product_value = db.Column(db.Integer)
    quantity = db.Column(db.Integer)
    total = db.Column(db.Integer)
    state = db.Column(db.String(100))


class OrderSchema(ma.SQLAlchemyAutoSchema):
    class Meta:
        # 'model' es obligatorio: marshmallow 4 ya no crea campos implicitos,
        # asi que sin el los nombres listados en 'fields' no existirian.
        model = Order
        fields = ("id", "user", "product", "quantity", "state")


class OrderViewSchema(ma.SQLAlchemyAutoSchema):
    class Meta:
        model = OrderView
        fields = ("id", "user_id", "user_username", "product_id",
                  "product_name", "product_value", "quantity", "total", "state")


order_schema = OrderSchema()
order_view_schema = OrderViewSchema()
orders_view_schema = OrderViewSchema(many=True)


def process_order(order_id):
    # Esta funcion la ejecuta el worker de RQ, fuera del ciclo de request,
    # por lo que necesita abrir su propio contexto de aplicacion.
    #
    # El import es tardio a proposito: proyector.py importa este modulo, asi
    # que importarlo arriba crearia un ciclo.
    from proyector import proyectar_orden

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

        # El estado cambio en el modelo de escritura: hay que volver a
        # proyectar para que las consultas lo reflejen.
        q_proyeccion.enqueue(proyectar_orden, order.id)
