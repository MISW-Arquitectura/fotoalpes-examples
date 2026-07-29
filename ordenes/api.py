import requests
from worker import app, api, ma, db, Order, order_schema, orders_schema, q, process_order, Resource, Flask, request, jsonify
from flask_jwt_extended import jwt_required


class OrderListResource(Resource):
    @jwt_required()
    def get(self):
        orders = db.session.scalars(db.select(Order)).all()
        return orders_schema.dump(orders)

    @jwt_required()
    def post(self):
        # Comunicacion sincrona: se reenvia el token del cliente para consultar
        # a los otros servicios, que tambien exigen autenticacion.
        headers = {'Authorization': request.headers['Authorization']}
        user = requests.get(
            f"https://users:5000/users/{request.json['user']}",
            verify=False, headers=headers, timeout=10,
        )
        product = requests.get(
            f"https://products:5000/products/{request.json['product']}",
            verify=False, headers=headers, timeout=10,
        )
        if user.status_code == 200 and product.status_code == 200:
            new_order = Order(
                user=request.json['user'],
                product=request.json['product'],
                quantity=request.json['quantity'],
                state="processing",
            )
            db.session.add(new_order)
            db.session.commit()
            # add to queue to process order
            q.enqueue(process_order, new_order.id)
            return order_schema.dump(new_order)
        else:
            # Si los otros servicios rechazan el token, el problema es de
            # autenticacion y no de datos inexistentes. Distinguirlo evita un
            # diagnostico equivocado. Flask-JWT-Extended responde 401 cuando
            # falta el token y 422 cuando la firma no valida, que es lo que
            # ocurre si los servicios no comparten el mismo JWT_SECRET_KEY.
            if user.status_code in (401, 422) or product.status_code in (401, 422):
                return {
                    "error": "Los servicios de usuarios o productos rechazaron el token.",
                    "sugerencia": "Verifique que todos los servicios usen el mismo "
                                  "JWT_SECRET_KEY y que el token provenga de /jwt.",
                }, 502

            # Se indica cual de los dos falta: el mensaje generico anterior
            # obligaba a adivinar.
            faltantes = []
            if user.status_code != 200:
                faltantes.append("el usuario " + str(request.json['user']))
            if product.status_code != 200:
                faltantes.append("el producto " + str(request.json['product']))

            return {
                "error": "No existe " + " ni ".join(faltantes) + ".",
                "sugerencia": "Cree primero el usuario y el producto, y use los ids "
                              "que devuelven esas operaciones.",
            }, 400


class OrderResource(Resource):
    @jwt_required()
    def get(self, order_id):
        order = db.get_or_404(Order, order_id)
        return order_schema.dump(order)


api.add_resource(OrderListResource, '/orders')
api.add_resource(OrderResource, '/orders/<int:order_id>')


if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', ssl_context='adhoc')
