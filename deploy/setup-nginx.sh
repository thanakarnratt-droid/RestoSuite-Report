#!/bin/sh
# Publish the dashboard at https://report.spicycatgroups.com via nginx + Let's Encrypt.
# Run on the VPS from the repository folder:  sudo sh deploy/setup-nginx.sh
# Needs a DNS record for the domain pointing at this server first.
set -eu
DOMAIN=report.spicycatgroups.com
SITE=/etc/nginx/sites-available/restosuite-dashboard
cd "$(dirname "$0")/.."

if [ "$(id -u)" -ne 0 ]; then
    echo "ต้องรันด้วย sudo: sudo sh deploy/setup-nginx.sh" >&2
    exit 1
fi
if [ -e "$SITE" ]; then
    echo "มี $SITE อยู่แล้ว ไม่เขียนทับ (ถ้าต้องการติดตั้งใหม่ ให้ลบไฟล์นั้นก่อน)" >&2
    exit 1
fi

cp deploy/nginx-dashboard.conf "$SITE"
ln -sf "$SITE" /etc/nginx/sites-enabled/restosuite-dashboard
if ! nginx -t; then
    # Leave nginx exactly as it was if the new site breaks the config.
    rm -f /etc/nginx/sites-enabled/restosuite-dashboard "$SITE"
    echo "nginx config ไม่ผ่าน ยกเลิกการติดตั้งแล้ว" >&2
    exit 1
fi
systemctl reload nginx

# Adds the 443 server block with the certificate and redirects http to https.
certbot --nginx -d "$DOMAIN" --redirect --non-interactive
echo "เสร็จแล้ว: https://$DOMAIN"
