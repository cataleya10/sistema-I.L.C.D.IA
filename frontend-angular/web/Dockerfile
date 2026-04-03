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

# Entrypoint: genera nginx config en runtime (HTTP o HTTPS según TLS_ENABLED)
COPY docker-entrypoint.sh /docker-entrypoint.sh
RUN chmod +x /docker-entrypoint.sh

EXPOSE 80 443

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD wget -q --spider http://localhost/nginx-health || exit 1

CMD ["/docker-entrypoint.sh"]
