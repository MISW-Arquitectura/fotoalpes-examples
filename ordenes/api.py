import requests
from worker import app, api, ma, db, Order, order_schema, orders_schema, q, process_order, Resource, Flask, request, jsonify


class OrderListResource(Resource):
    def get(self):
        orders = db.session.scalars(db.select(Order)).all()
        return orders_schema.dump(orders)

    def post(self):
        # Comunicacion sincrona: se consulta a los otros servicios por HTTP
        # antes de aceptar la orden.
        user = requests.get(f"http://users:5000/users/{request.json['user']}")
        product = requests.get(f"http://products:5000/products/{request.json['product']}")
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
    def get(self, order_id):
        order = db.get_or_404(Order, order_id)
        return order_schema.dump(order)


api.add_resource(OrderListResource, '/orders')
api.add_resource(OrderResource, '/orders/<int:order_id>')


if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0')
