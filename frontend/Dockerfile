FROM node:20-alpine

ENV NEXT_TELEMETRY_DISABLED=1 \
    npm_config_update_notifier=false

WORKDIR /app

COPY package*.json ./
RUN npm install

COPY . .

EXPOSE 3000

CMD ["npm", "run", "dev"]
