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

# SPA fallback: send all routes to index.html
RUN printf 'server {\n\
  listen 80;\n\
  root /usr/share/nginx/html;\n\
  index index.html;\n\
  location / {\n\
    try_files $uri $uri/ /index.html;\n\
  }\n\
}\n' > /etc/nginx/conf.d/default.conf

EXPOSE 80

CMD ["nginx", "-g", "daemon off;"]
