const express = require('express');

const tools = [
  {
    slug: 'json-formatter',
    name: 'JSON Formatter & Validator',
    shortDescription: 'Format, minify, and validate JSON with line-aware errors.',
    description: 'Format, validate, and minify JSON',
    category: 'Dev',
    icon: '🧩',
  },
  {
    slug: 'base64',
    name: 'Base64 Encoder / Decoder',
    shortDescription: 'Encode text/files and decode base64 quickly.',
    description: 'Encode and decode Base64 with file support',
    category: 'Dev',
    icon: '🔐',
  },
  {
    slug: 'word-counter',
    name: 'Word & Character Counter',
    shortDescription: 'Live writing statistics and top-word insights.',
    description: 'Count words, characters, and reading stats in real time',
    category: 'Text',
    icon: '📝',
  },
  {
    slug: 'color-picker',
    name: 'Color Picker & Converter',
    shortDescription: 'Convert HEX, RGB, HSL, CMYK and build shades.',
    description: 'Pick colors and convert across popular formats',
    category: 'Colors',
    icon: '🎨',
  },
  {
    slug: 'password-gen',
    name: 'Password Generator',
    shortDescription: 'Generate secure single or batch passwords.',
    description: 'Create strong passwords with strength feedback',
    category: 'Security',
    icon: '🛡️',
  },
];

const router = express.Router();

router.get('/', (req, res) => {
  res.redirect('/');
});

router.get('/:slug', (req, res, next) => {
  const tool = tools.find((item) => item.slug === req.params.slug);
  if (!tool) {
    return next();
  }

  return res.render(`tools/${tool.slug}`, {
    title: tool.name,
    description: tool.description,
    category: tool.category,
    tool,
    tools,
    currentPath: `/tools/${tool.slug}`,
    showSearch: false,
    pageScript: `${tool.slug}.js`,
  });
});

module.exports = { router, tools };
