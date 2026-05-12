#!/bin/bash
# Corre este script no servidor Hetzner (Ubuntu 24.04) como root:
#   bash setup_server.sh

set -e

APP_DIR="/opt/structural_ai"
SERVICE_USER="structural"
PORT=8501

echo "=== [1/6] Atualizar sistema ==="
apt-get update -qq && apt-get upgrade -y -qq

echo "=== [2/6] Instalar dependências ==="
apt-get install -y -qq python3 python3-pip python3-venv nginx git ufw

echo "=== [3/6] Criar utilizador de serviço ==="
id -u $SERVICE_USER &>/dev/null || useradd -m -s /bin/bash $SERVICE_USER

echo "=== [4/6] Preparar directório da app ==="
mkdir -p "$APP_DIR"
cp -r . "$APP_DIR/"
chown -R $SERVICE_USER:$SERVICE_USER "$APP_DIR"

echo "=== [5/6] Instalar dependências Python ==="
python3 -m venv "$APP_DIR/venv"
"$APP_DIR/venv/bin/pip" install --upgrade pip -q
"$APP_DIR/venv/bin/pip" install -r "$APP_DIR/requirements.txt" -q

echo "=== [6/6] Criar serviço systemd ==="
cat > /etc/systemd/system/structural_ai.service << EOF
[Unit]
Description=Structural AI — Streamlit
After=network.target

[Service]
User=$SERVICE_USER
WorkingDirectory=$APP_DIR
ExecStart=$APP_DIR/venv/bin/streamlit run app/streamlit_app.py \
    --server.port $PORT \
    --server.headless true \
    --server.address 127.0.0.1
Restart=always
RestartSec=5
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable structural_ai
systemctl start structural_ai

echo "=== Configurar nginx ==="
cat > /etc/nginx/sites-available/structural_ai << 'NGINX'
server {
    listen 80;
    server_name _;

    location / {
        proxy_pass http://127.0.0.1:8501;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_read_timeout 86400;
    }
}
NGINX

ln -sf /etc/nginx/sites-available/structural_ai /etc/nginx/sites-enabled/structural_ai
rm -f /etc/nginx/sites-enabled/default
nginx -t && systemctl restart nginx

echo "=== Firewall ==="
ufw allow OpenSSH
ufw allow 'Nginx Full'
ufw --force enable

echo ""
echo "=============================="
echo " Deploy concluído!"
echo " Acede em: http://$(curl -s ifconfig.me)"
echo "=============================="
