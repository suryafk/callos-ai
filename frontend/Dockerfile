# Build the static dashboard, then serve it with nginx, which also proxies /api to the backend
# so the browser talks to a single origin.
FROM node:22-alpine AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
# Empty = same origin (nginx proxy). Set it only when the API lives on another host.
ARG VITE_API_BASE_URL=""
ENV VITE_API_BASE_URL=$VITE_API_BASE_URL
RUN npm run build

FROM nginx:1.27-alpine
COPY nginx.conf.template /etc/nginx/templates/default.conf.template
COPY --from=build /app/dist /usr/share/nginx/html
# Where nginx forwards /api and /health.
ENV BACKEND_URL=http://backend:8000
EXPOSE 80
