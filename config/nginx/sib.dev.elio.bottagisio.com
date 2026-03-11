server {
    listen 80;
    listen [::]:80;
    server_name sib.dev.elio.bottagisio.com;

    location ^~ /.well-known/acme-challenge/ {
        root /var/www/sib.shared.elio.dev;
        default_type "text/plain";
        try_files $uri =404;
        auth_basic off;
    }

    return 301 https://$host$request_uri;
}

server {
    listen 443 ssl http2;
    listen [::]:443 ssl http2;
    server_name sib.dev.elio.bottagisio.com;

    root /var/www/sib.shared.elio.dev;
    index index.html;

    ssl_certificate /etc/letsencrypt/live/sib.dev.elio.bottagisio.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/sib.dev.elio.bottagisio.com/privkey.pem;
    ssl_session_cache shared:SSL:10m;
    ssl_session_timeout 10m;
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers HIGH:!aNULL:!MD5;
    limit_req_status 429;

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

    location = /api/v1/runs {
        auth_basic "Restricted";
        auth_basic_user_file /etc/nginx/.htpasswd-sib-copy;
        limit_req zone=sib_api_runs burst=5 nodelay;

        client_max_body_size 50m;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header Connection "";
        proxy_read_timeout 300s;
        proxy_send_timeout 300s;
        proxy_pass http://127.0.0.1:8000;
    }

    location /api/ {
        auth_basic "Restricted";
        auth_basic_user_file /etc/nginx/.htpasswd-sib-copy;
        limit_req zone=sib_api_read burst=30 nodelay;

        client_max_body_size 50m;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header Connection "";
        proxy_read_timeout 300s;
        proxy_send_timeout 300s;
        proxy_pass http://127.0.0.1:8000;
    }

    location ^~ /hazard-maps/ {
        auth_basic "Restricted";
        auth_basic_user_file /etc/nginx/.htpasswd-sib-copy;
        alias /var/www/sib.shared.elio.dev/hazard-maps/;
        add_header Cache-Control "private, max-age=300";
    }

    location / {
        auth_basic "Restricted";
        auth_basic_user_file /etc/nginx/.htpasswd-sib-copy;
        try_files $uri /index.html;
    }

    location ~ /\.ht {
        deny all;
    }
}
