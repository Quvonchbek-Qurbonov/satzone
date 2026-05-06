# Satzone – Frontend

This directory contains the **frontend** application for the Satzone learning platform, built with [React](https://react.dev/).

## Project structure

```
frontend/
├── public/          # Static assets & HTML template
├── src/
│   ├── components/  # Reusable UI components
│   ├── pages/       # Page-level components / routes
│   ├── App.js       # Root component
│   └── index.js     # Entry point
└── package.json
```

## Getting started

```bash
# Install dependencies
npm install

# Start the development server (http://localhost:3000)
npm run dev

# Create a production build
npm run build

# Run tests
npm test
```

## Environment variables

Create a `.env` file in this directory and add the variables below:

| Variable              | Description                          | Default                       |
|-----------------------|--------------------------------------|-------------------------------|
| `REACT_APP_API_URL`   | Base URL of the backend API          | `http://localhost:5000/api`   |
