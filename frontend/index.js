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

// Basic route
app.get('/', (req, res) => {
  res.render('index', { title: 'Frontend App', message: 'Hello from Node, Express and EJS!' });
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
