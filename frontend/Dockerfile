# syntax=docker/dockerfile:1.7

FROM node:20-alpine

WORKDIR /app

ENV PATH=/app/node_modules/.bin:$PATH

COPY package.json package-lock.json ./
RUN --mount=type=cache,target=/root/.npm,sharing=locked npm ci

COPY . .

EXPOSE 5173

CMD ["npm", "run", "dev"]
