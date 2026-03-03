# ─── Angular Frontend ───
# Stage 1: Build
FROM node:22-alpine AS build
WORKDIR /app

COPY package.json package-lock.json ./
RUN npm ci

COPY . .
RUN npx ng build --configuration=production

# Stage 2: Serve with nginx
FROM nginx:alpine AS runtime

COPY --from=build /app/dist/web/browser /usr/share/nginx/html

# SPA fallback + gzip + security headers
RUN printf 'server_tokens off;\n\
server {\n\
  listen 80;\n\
  root /usr/share/nginx/html;\n\
  index index.html;\n\
\n\
  # Gzip compression\n\
  gzip on;\n\
  gzip_types text/plain text/css application/json application/javascript text/xml application/xml application/xml+rss text/javascript image/svg+xml;\n\
  gzip_min_length 256;\n\
  gzip_vary on;\n\
\n\
  # Security headers\n\
  add_header X-Content-Type-Options "nosniff" always;\n\
  add_header X-Frame-Options "DENY" always;\n\
  add_header X-XSS-Protection "1; mode=block" always;\n\
  add_header Referrer-Policy "no-referrer" always;\n\
  add_header Permissions-Policy "camera=(), microphone=(), geolocation=()" always;\n\
  add_header Content-Security-Policy "default-src '"'"'self'"'"'; script-src '"'"'self'"'"' '"'"'unsafe-inline'"'"'; style-src '"'"'self'"'"' '"'"'unsafe-inline'"'"'; img-src '"'"'self'"'"' data: blob:; connect-src '"'"'self'"'"'; font-src '"'"'self'"'"';" always;\n\
\n\
  # Cache static assets aggressively\n\
  location ~* \\.(js|css|png|jpg|jpeg|gif|ico|svg|woff|woff2|ttf|eot)$ {\n\
    expires 1y;\n\
    add_header Cache-Control "public, immutable";\n\
  }\n\
\n\
  location / {\n\
    try_files $uri $uri/ /index.html;\n\
  }\n\
\n\
  # Health check endpoint\n\
  location /nginx-health {\n\
    access_log off;\n\
    return 200 "ok";\n\
    add_header Content-Type text/plain;\n\
  }\n\
}\n' > /etc/nginx/conf.d/default.conf

EXPOSE 80

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD wget -q --spider http://localhost/nginx-health || exit 1

CMD ["nginx", "-g", "daemon off;"]
