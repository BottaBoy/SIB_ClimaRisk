server {
    listen 80;
    listen [::]:80;
    server_name sib.mc2-sarl.com;

    location ^~ /.well-known/acme-challenge/ {
        root /var/www/sib.mc2-sarl.com;
        default_type "text/plain";
        try_files $uri =404;
    }

    return 301 https://$host$request_uri;
}

server {
    listen 443 ssl http2;
    listen [::]:443 ssl http2;
    server_name sib.mc2-sarl.com;

    root /var/www/sib.mc2-sarl.com;
    index index.html;

    ssl_certificate /etc/letsencrypt/live/sib.mc2-sarl.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/sib.mc2-sarl.com/privkey.pem;
    ssl_session_cache shared:SSL:10m;
    ssl_session_timeout 10m;
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers HIGH:!aNULL:!MD5;

    add_header Strict-Transport-Security "max-age=31536000; includeSubDomains" always;

    location ^~ /.well-known/acme-challenge/ {
        root /var/www/sib.mc2-sarl.com;
        default_type "text/plain";
        try_files $uri =404;
    }

    location / {
        try_files $uri /index.html;
    }

    location ~ /\.ht {
        deny all;
    }
}
