FROM node:20-alpine

WORKDIR /app

ENV NODE_ENV=production \
    PORT=5004 \
    FRONTEND_ROOT=/app/dist \
    BACKEND_URL=http://backend:5000

COPY --chown=node:node dist ./dist
COPY --chown=node:node server.mjs ./server.mjs

USER node
EXPOSE 5004

HEALTHCHECK --interval=30s --timeout=5s --retries=3 CMD node -e "fetch('http://127.0.0.1:5004/__health').then(r => process.exit(r.ok ? 0 : 1)).catch(() => process.exit(1))"

CMD ["node", "server.mjs"]
