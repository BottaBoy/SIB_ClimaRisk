server {
    listen 80;
    listen [::]:80;
    server_name sib-copy.dev.elio.bottagisio.com;

    location ^~ /.well-known/acme-challenge/ {
        root /var/www/sib-copy.dev.elio.bottagisio.com;
        default_type "text/plain";
        try_files $uri =404;
        auth_basic off;
    }

    return 301 https://$host$request_uri;
}

server {
    listen 443 ssl http2;
    listen [::]:443 ssl http2;
    server_name sib-copy.dev.elio.bottagisio.com;

    root /var/www/sib-copy.dev.elio.bottagisio.com;
    index index.html;

    ssl_certificate /etc/letsencrypt/live/sib-copy.dev.elio.bottagisio.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/sib-copy.dev.elio.bottagisio.com/privkey.pem;
    ssl_session_cache shared:SSL:10m;
    ssl_session_timeout 10m;
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers HIGH:!aNULL:!MD5;

    add_header Strict-Transport-Security "max-age=31536000; includeSubDomains" always;

    location ^~ /.well-known/acme-challenge/ {
        root /var/www/sib-copy.dev.elio.bottagisio.com;
        default_type "text/plain";
        try_files $uri =404;
        auth_basic off;
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
