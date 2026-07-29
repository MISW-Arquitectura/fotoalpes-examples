from base import app, api, ma, db, User, user_schema, users_schema, q, Resource, Flask, request
from flask_jwt_extended import jwt_required


class UserListResource(Resource):
    @jwt_required()
    def get(self):
        users = db.session.scalars(db.select(User)).all()
        return users_schema.dump(users)


class UserResource(Resource):
    @jwt_required()
    def get(self, user_id):
        user = db.get_or_404(User, user_id)
        return user_schema.dump(user)


api.add_resource(UserListResource, '/api-queries/users')
api.add_resource(UserResource, '/api-queries/users/<int:user_id>')


if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', ssl_context='adhoc')
