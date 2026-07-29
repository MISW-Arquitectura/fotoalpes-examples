from base import app, api, ma, db, User, user_schema, q, q_proyeccion, Resource, Flask, request
from sender import send_user
from proyector import proyectar_usuario


class UserListResource(Resource):
    def post(self):
        # El lado de comandos escribe UNICAMENTE en el modelo de escritura.
        new_user = User(
            username=request.json['username'],
        )
        db.session.add(new_user)
        db.session.commit()

        # Replica hacia el servicio de ordenes (comunicacion entre servicios).
        q.enqueue(send_user, user_schema.dump(new_user))

        # Proyeccion hacia el modelo de lectura de este servicio (CQRS). Es
        # asincrona: por eso la consulta puede no reflejar el cambio de
        # inmediato. Eso es consistencia eventual, y es lo esperado.
        q_proyeccion.enqueue(proyectar_usuario, new_user.id)

        return user_schema.dump(new_user)


api.add_resource(UserListResource, '/api-commands/users')


if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0')
