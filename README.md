# Satzone

A strong and reliable platform for learning.

## Repository structure

This is a monorepo containing two sub-projects:

| Directory    | Description                                      |
|--------------|--------------------------------------------------|
| [`frontend/`](./frontend) | React web application (user interface) |
| [`backend/`](./backend)   | Node.js / Express REST API             |

## Quick start

### Backend

```bash
cd backend
npm install
cp .env.example .env   # edit variables as needed
npm run dev            # http://localhost:5000
```

### Frontend

```bash
cd frontend
npm install
npm run dev            # http://localhost:3000
```

## Contributing

1. Fork the repository.
2. Create a feature branch: `git checkout -b feature/my-feature`.
3. Commit your changes and open a pull request.
