from base import app, api, ma, db, OrderView, order_view_schema, orders_view_schema, Resource, Flask, request, jsonify


class OrderListResource(Resource):
    def get(self):
        # El lado de consultas lee UNICAMENTE del modelo de lectura, que ya
        # trae los nombres y el total resueltos.
        orders = db.session.scalars(db.select(OrderView)).all()
        return orders_view_schema.dump(orders)


class OrderResource(Resource):
    def get(self, order_id):
        order = db.get_or_404(OrderView, order_id)
        return order_view_schema.dump(order)


api.add_resource(OrderListResource, '/api-queries/orders')
api.add_resource(OrderResource, '/api-queries/orders/<int:order_id>')


if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0')
