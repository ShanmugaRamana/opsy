const express = require('express');
const path = require('path');
const app = express();
const port = 3000;

// Set EJS as templating engine
app.set('view engine', 'ejs');
app.set('views', path.join(__dirname, 'views'));

// Serve static files from the 'public' directory
app.use(express.static(path.join(__dirname, 'public')));

// Parse JSON bodies
app.use(express.json());
// Parse URL-encoded bodies
app.use(express.urlencoded({ extended: true }));

// Request logging
app.use((req, res, next) => {
  const start = Date.now();
  res.on('finish', () => {
    const duration = Date.now() - start;
    console.log(`${req.method} ${req.originalUrl} ${res.statusCode} ${duration}ms`);
  });
  next();
});

// Main app route
app.get('/', (req, res) => {
  res.render('index', { title: 'Zyros', page: 'pages/home' });
});

// Onboarding route
app.get('/onboarding', (req, res) => {
  res.render('index', { title: 'Onboarding - Zyros', page: 'pages/onboarding' });
});

// Setup route
app.get('/setup', (req, res) => {
  res.render('index', { title: 'Setup - Zyros', page: 'pages/setup' });
});

// Local-model download progress route
app.get('/download', (req, res) => {
  res.render('index', { title: 'Downloading - Zyros', page: 'pages/download' });
});

// Settings route
app.get('/settings', (req, res) => {
  res.render('index', { title: 'Settings - Zyros', page: 'pages/settings' });
});

// Shutdown route for PC app to close the server
app.post('/shutdown', (req, res) => {
  console.log('Received shutdown request, terminating server...');
  res.send('Server shutting down');
  process.exit(0);
});

// Start the server
app.listen(port, () => {
  console.log(`Frontend app listening at http://localhost:${port}`);
});
