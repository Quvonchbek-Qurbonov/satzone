require('dotenv').config();
const express = require('express');
const cors = require('cors');

const app = express();
const PORT = process.env.PORT || 5000;

app.use(cors());
app.use(express.json());

// Health-check route
app.get('/api/health', (req, res) => {
  res.json({ status: 'ok', message: 'Satzone backend is running' });
});

// TODO: register additional route modules here
// e.g. app.use('/api/courses', require('./routes/courses'));

const server = app.listen(PORT, () => {
  console.log(`Backend server running on port ${PORT}`);
});

module.exports = { app, server };
