FROM node:22-alpine

WORKDIR /app

# Install the dependencies first, so a source change does not reinstall them.
COPY frontend/package*.json ./
RUN npm ci

# Build the app, and serve the built output.
#
# The image bakes the source in, so a Vite *dev* server here has nothing to hot-reload: editing
# the source on the host does not reach the container, and the only way to see a change is to
# rebuild the image. All that buys is the transform pipeline and the dev server's memory -
# around 650 MB on a machine that is already short of it, and a slower first paint.
#
# The built output is what a reviewer should be looking at anyway: it is the bundle that ships.
COPY frontend/ ./
RUN npm run build

EXPOSE 5173

# `vite preview` serves the built output and proxies /api to the backend, the same as the dev
# server did. The port is the same so the compose mapping does not change.
CMD ["npm", "run", "preview", "--", "--host", "0.0.0.0", "--port", "5173"]
