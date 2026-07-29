#!/bin/sh
# Instala Docker Engine y el plugin Compose v2 en Ubuntu/Debian.
#
# Solo para Linux. En macOS y Windows instale Docker Desktop, que ya incluye
# Compose v2: https://www.docker.com/products/docker-desktop/
#
# Nota: la version anterior de este script instalaba docker-compose v1, que
# quedo sin soporte. El comando ahora es "docker compose" (sin guion).

set -e

sudo apt-get update
sudo apt-get install -y ca-certificates curl

# Repositorio oficial de Docker
sudo install -m 0755 -d /etc/apt/keyrings
sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
sudo chmod a+r /etc/apt/keyrings/docker.asc

echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "$VERSION_CODENAME") stable" \
  | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null

sudo apt-get update
sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

# Permite usar docker sin sudo
sudo usermod -aG docker "$USER"

echo ""
echo "Instalacion terminada."
echo "Cierre la sesion y vuelva a entrar para que el grupo 'docker' tome efecto."
echo "Luego verifique con:  docker compose version"
