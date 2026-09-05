# The frontend is static files and a web server. No build step, no Node.
FROM nginx:1.27-alpine

COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY index.html style.css app.js api.js config.js /usr/share/nginx/html/

# The nginx image runs everything in this directory before starting.
COPY docker-entrypoint.d-10-api-base.sh /docker-entrypoint.d/10-api-base.sh
RUN chmod +x /docker-entrypoint.d/10-api-base.sh

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
  CMD wget -qO- http://127.0.0.1:8080/ >/dev/null || exit 1
