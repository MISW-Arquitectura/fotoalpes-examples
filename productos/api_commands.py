from base import app, api, ma, db, Product, product_schema, q, q_proyeccion, Resource, Flask, request
from sender import send_product
from putter import put_product
from proyector import proyectar_producto
from flask_jwt_extended import jwt_required


class ProductListResource(Resource):
    @jwt_required()
    def post(self):
        # El lado de comandos escribe UNICAMENTE en el modelo de escritura.
        new_product = Product(
            name=request.json['name'],
            description=request.json['description'],
            value=request.json['value'],
            stock=request.json['stock'],
        )
        db.session.add(new_product)
        db.session.commit()

        # Replica hacia el servicio de ordenes.
        q.enqueue(send_product, product_schema.dump(new_product))
        # Proyeccion hacia el modelo de lectura de este servicio (CQRS).
        q_proyeccion.enqueue(proyectar_producto, new_product.id)

        return product_schema.dump(new_product)


class ProductResource(Resource):
    @jwt_required()
    def put(self, product_id):
        product = db.get_or_404(Product, product_id)
        if 'name' in request.json:
            product.name = request.json['name']
        if 'description' in request.json:
            product.description = request.json['description']
        if 'value' in request.json:
            product.value = request.json['value']
        if 'stock' in request.json:
            product.stock = request.json['stock']
        db.session.commit()

        q.enqueue(put_product, product_schema.dump(product))
        # Toda escritura encola su proyeccion: tambien las modificaciones.
        q_proyeccion.enqueue(proyectar_producto, product.id)

        return product_schema.dump(product)


api.add_resource(ProductListResource, '/api-commands/products')
api.add_resource(ProductResource, '/api-commands/products/<int:product_id>')


if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', ssl_context='adhoc')
