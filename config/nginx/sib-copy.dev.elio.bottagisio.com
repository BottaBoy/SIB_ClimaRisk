server {
    listen 80;
    listen [::]:80;
    server_name sib-copy.dev.elio.bottagisio.com;

    location ^~ /.well-known/acme-challenge/ {
        root /var/www/sib.shared.elio.dev;
        default_type "text/plain";
        try_files $uri =404;
        auth_basic off;
    }

    location / {
        return 301 https://visu.sib.dev.elio.bottagisio.com$request_uri;
    }
}

server {
    listen 443 ssl http2;
    listen [::]:443 ssl http2;
    server_name sib-copy.dev.elio.bottagisio.com;

    ssl_certificate /etc/letsencrypt/live/sib-copy.dev.elio.bottagisio.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/sib-copy.dev.elio.bottagisio.com/privkey.pem;
    ssl_session_cache shared:SSL:10m;
    ssl_session_timeout 10m;
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers HIGH:!aNULL:!MD5;

    add_header Strict-Transport-Security "max-age=31536000; includeSubDomains" always;
    add_header X-Content-Type-Options "nosniff" always;
    add_header X-Frame-Options "DENY" always;
    add_header Referrer-Policy "strict-origin-when-cross-origin" always;
    add_header Permissions-Policy "geolocation=(), microphone=(), camera=()" always;
    add_header Content-Security-Policy "default-src 'self'; base-uri 'self'; object-src 'none'; frame-ancestors 'none'; img-src 'self' data: https://*.tile.openstreetmap.org; style-src 'self' 'unsafe-inline' https://unpkg.com; script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net https://unpkg.com; connect-src 'self'; font-src 'self' data:; worker-src 'self' blob:;" always;

    location ^~ /.well-known/acme-challenge/ {
        root /var/www/sib.shared.elio.dev;
        default_type "text/plain";
        try_files $uri =404;
        auth_basic off;
    }

    location / {
        return 301 https://visu.sib.dev.elio.bottagisio.com$request_uri;
    }

    location ~ /\.ht {
        deny all;
    }
}
