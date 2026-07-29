from base import app, api, ma, db, Product, product_schema, products_schema, q, Resource, Flask, request
from flask_jwt_extended import jwt_required


class ProductListResource(Resource):
    @jwt_required()
    def get(self):
        products = db.session.scalars(db.select(Product)).all()
        return products_schema.dump(products)


class ProductResource(Resource):
    @jwt_required()
    def get(self, product_id):
        product = db.get_or_404(Product, product_id)
        return product_schema.dump(product)


api.add_resource(ProductListResource, '/api-queries/products')
api.add_resource(ProductResource, '/api-queries/products/<int:product_id>')


if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', ssl_context='adhoc')
