export const environment = {
  production: true,
  // nginx proxies /api/* → backend:5000 en producción (ver docker-compose.production.yml)
  apiUrl: '/api'
};
