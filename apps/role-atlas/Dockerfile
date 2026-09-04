FROM node:22-bookworm-slim

ARG NODE_BUILD_MEMORY_MB=1280

WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
RUN NODE_OPTIONS="--max-old-space-size=${NODE_BUILD_MEMORY_MB}" npm run build

EXPOSE 3000
CMD ["npm", "run", "start", "--", "--hostname", "0.0.0.0", "--port", "3000"]
