FROM node:20-alpine

ENV NEXT_TELEMETRY_DISABLED=1 \
    npm_config_update_notifier=false

WORKDIR /app

COPY package*.json ./
RUN npm ci

ARG NEXT_PUBLIC_API_URL
ENV NEXT_PUBLIC_API_URL=$NEXT_PUBLIC_API_URL

COPY . .

RUN mkdir -p /app/.next && chown -R node:node /app

USER node

EXPOSE 3000

CMD ["npm", "run", "dev"]
