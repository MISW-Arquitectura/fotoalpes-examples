from base import app, api, ma, db, ProductView, product_view_schema, products_view_schema, Resource, Flask, request
from flask_jwt_extended import jwt_required


class ProductListResource(Resource):
    @jwt_required()
    def get(self):
        # El lado de consultas lee UNICAMENTE del modelo de lectura.
        products = db.session.scalars(db.select(ProductView)).all()
        return products_view_schema.dump(products)


class ProductResource(Resource):
    @jwt_required()
    def get(self, product_id):
        product = db.get_or_404(ProductView, product_id)
        return product_view_schema.dump(product)


api.add_resource(ProductListResource, '/api-queries/products')
api.add_resource(ProductResource, '/api-queries/products/<int:product_id>')


if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', ssl_context='adhoc')
