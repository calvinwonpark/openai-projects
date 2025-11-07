FROM node:18-alpine
WORKDIR /app
COPY package.json next.config.js ./
RUN npm i
COPY app ./app
ENV PORT=3000
EXPOSE 3000
CMD ["npm", "run", "dev"]
