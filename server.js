const express = require('express');
const { router: toolsRouter, tools } = require('./routes/tools');

const app = express();

app.set('view engine', 'ejs');
app.set('views', './views');
app.use(express.static('public'));
app.use(express.json());
app.use(express.urlencoded({ extended: true }));

app.get('/', (req, res) => {
  res.render('index', {
    title: 'Simple Multi-Tool Utility',
    description: 'Fast, free tools for text, dev, colors, and security workflows.',
    tools,
    currentPath: '/',
    showSearch: true,
    pageScript: 'index.js',
  });
});

app.use('/tools', toolsRouter);

const PORT = process.env.PORT || 3000;
app.listen(PORT, () => console.log(`Running on http://localhost:${PORT}`));
