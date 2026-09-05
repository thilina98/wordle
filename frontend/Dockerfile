# syntax=docker/dockerfile:1.7

# Static files and a web server. No build step, no Node, nothing to compile.
#
# nginx-unprivileged rather than the standard nginx image: the standard one
# starts its master process as root to bind port 80. This one runs entirely as
# an unprivileged user on port 8080, which is all we need.
FROM nginxinc/nginx-unprivileged:1.27-alpine

USER root
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY index.html style.css app.js api.js config.js /usr/share/nginx/html/
COPY docker-entrypoint.d-10-api-base.sh /docker-entrypoint.d/10-api-base.sh
RUN chmod 0755 /docker-entrypoint.d/10-api-base.sh \
    && chown -R nginx:nginx /usr/share/nginx/html

USER 101:101

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
  CMD ["/bin/sh", "-c", "wget -qO- http://127.0.0.1:8080/ >/dev/null || exit 1"]
