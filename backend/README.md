# Satzone – Backend

This directory contains the **backend** API for the Satzone learning platform, built with [Node.js](https://nodejs.org/) and [Express](https://expressjs.com/).

## Project structure

```
backend/
├── src/
│   ├── routes/      # Express route handlers
│   ├── controllers/ # Business logic
│   ├── models/      # Data models
│   ├── middleware/  # Custom middleware
│   └── index.js     # Entry point / server setup
├── package.json
└── .env.example     # Example environment variables
```

## Getting started

```bash
# Install dependencies
npm install

# Copy and edit environment variables
cp .env.example .env

# Start the development server with hot-reload (http://localhost:5000)
npm run dev

# Start in production mode
npm start

# Run tests
npm test
```

## Environment variables

| Variable      | Description                         | Default       |
|---------------|-------------------------------------|---------------|
| `PORT`        | Port the server listens on          | `5000`        |
| `NODE_ENV`    | Runtime environment                 | `development` |
| `DATABASE_URL`| Connection string for the database  | –             |

## API

| Method | Path         | Description        |
|--------|--------------|--------------------|
| GET    | `/api/health`| Health-check probe |
