from base import app, api, ma, db, UserView, user_view_schema, users_view_schema, Resource, Flask, request


class UserListResource(Resource):
    def get(self):
        # El lado de consultas lee UNICAMENTE del modelo de lectura. Nunca
        # toca el de escritura: esa es la segregacion que da nombre a CQRS.
        users = db.session.scalars(db.select(UserView)).all()
        return users_view_schema.dump(users)


class UserResource(Resource):
    def get(self, user_id):
        user = db.get_or_404(UserView, user_id)
        return user_view_schema.dump(user)


api.add_resource(UserListResource, '/api-queries/users')
api.add_resource(UserResource, '/api-queries/users/<int:user_id>')


if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0')
