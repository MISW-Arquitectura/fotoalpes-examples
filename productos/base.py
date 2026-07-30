import sys
import time

from flask import Flask, request
from flask_sqlalchemy import SQLAlchemy
from flask_marshmallow import Marshmallow
from flask_restful import Api, Resource
from redis import Redis
from rq import Queue
import requests
import urllib3
from sender import send_product
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
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:////mnt/productos-escritura.db'
app.config['SQLALCHEMY_BINDS'] = {
    'lectura': 'sqlite:////mnt/productos-lectura.db',
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


# Replica el producto hacia el servicio de ordenes. La atiende worker-orders.
q = Queue(connection=Redis(host='redis', port=6379, db=obtener_cola("products", "q")))

# Proyecta el producto hacia el modelo de lectura de este servicio. La atiende
# worker-products, que corre esta misma imagen.
q_proyeccion = Queue(
    connection=Redis(host='redis', port=6379, db=obtener_cola("products", "proyeccion"))
)


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
        # 'model' es obligatorio: marshmallow 4 ya no crea campos implicitos,
        # asi que sin el los nombres listados en 'fields' no existirian.
        model = Product
        fields = ("id", "name", "description", "value", "stock")


class ProductViewSchema(ma.SQLAlchemyAutoSchema):
    class Meta:
        model = ProductView
        fields = ("id", "name", "description", "value", "stock", "disponible")


product_schema = ProductSchema()
product_view_schema = ProductViewSchema()
products_view_schema = ProductViewSchema(many=True)
