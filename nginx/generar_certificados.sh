#!/bin/sh
# Regenera el certificado autofirmado que usa nginx como API Gateway.
#
# Los certificados versionados en el repositorio son de PRUEBA: la llave
# privada es publica a proposito para que el ejemplo funcione sin pasos
# adicionales. Nunca los use fuera del aula.
#
# Se generan con una validez muy larga para que el ejemplo no deje de
# funcionar a mitad de un semestre. Si aun asi vencieron, o si quiere cambiar
# los nombres del certificado, ejecute este script desde el directorio nginx/:
#
#     sh generar_certificados.sh
#
# Luego reconstruya y levante de nuevo:  docker compose up -d --build --wait

set -e

cd "$(dirname "$0")"

DIAS=7300  # ~20 anios

openssl req -x509 -nodes \
  -days "$DIAS" \
  -newkey rsa:2048 \
  -keyout localhost.key \
  -out localhost.crt \
  -config open_ssl.conf

chmod 644 localhost.crt localhost.key

echo ""
echo "Certificado regenerado. Vigencia:"
openssl x509 -in localhost.crt -noout -subject -dates
