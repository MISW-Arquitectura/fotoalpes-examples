from base import app, api, ma, db, Order, User, Product, order_schema, orders_schema, q, process_order, Resource, Flask, request, jsonify
from flask_jwt_extended import jwt_required


class OrderListResource(Resource):
    @jwt_required()
    def post(self):
        user = db.session.get(User, request.json['user'])
        product = db.session.get(Product, request.json['product'])
        if user is not None and product is not None:
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
            # Se indica cual de los dos falta: el mensaje generico anterior
            # obligaba a adivinar, y en esta rama la causa mas comun no es que
            # el dato no exista sino que la replicacion aun no ha llegado.
            faltantes = []
            if user is None:
                faltantes.append("el usuario " + str(request.json['user']))
            if product is None:
                faltantes.append("el producto " + str(request.json['product']))

            return {
                "error": "No se encontro " + " ni ".join(faltantes)
                         + " en la base de datos del servicio de ordenes.",
                "sugerencia": "Los usuarios y productos llegan a este servicio por "
                              "replicacion asincrona. Si acaba de crearlos, espere "
                              "unos segundos y reintente. Si el problema persiste, "
                              "revise que el worker este corriendo con "
                              "'docker compose ps'.",
            }, 400


api.add_resource(OrderListResource, '/api-commands/orders')


if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', ssl_context='adhoc')
