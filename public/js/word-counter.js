(() => {
  const input = document.getElementById('wordInput');
  const freqWords = document.getElementById('freqWords');

  const refs = {
    words: document.getElementById('statWords'),
    chars: document.getElementById('statChars'),
    charsNoSpaces: document.getElementById('statCharsNoSpaces'),
    sentences: document.getElementById('statSentences'),
    paragraphs: document.getElementById('statParagraphs'),
    readingTime: document.getElementById('statReadingTime'),
  };

  const tokenize = (text) => (text.toLowerCase().match(/[a-z0-9']+/g) || []);

  const update = () => {
    const text = input.value;
    const words = tokenize(text);
    const chars = text.length;
    const charsNoSpaces = text.replace(/\s/g, '').length;
    const sentences = (text.match(/[.!?]+/g) || []).length;
    const paragraphs = text.trim() ? text.trim().split(/\n\s*\n/).length : 0;
    const readingMins = Math.max(0, Math.ceil(words.length / 200));

    refs.words.textContent = words.length;
    refs.chars.textContent = chars;
    refs.charsNoSpaces.textContent = charsNoSpaces;
    refs.sentences.textContent = sentences;
    refs.paragraphs.textContent = paragraphs;
    refs.readingTime.textContent = `${readingMins} min`;

    const counts = words.reduce((acc, word) => {
      if (word.length < 2) return acc;
      acc[word] = (acc[word] || 0) + 1;
      return acc;
    }, {});

    const top = Object.entries(counts)
      .sort((a, b) => b[1] - a[1])
      .slice(0, 8);

    freqWords.innerHTML = '';
    if (!top.length) {
      const li = document.createElement('li');
      li.textContent = 'No frequent words yet.';
      freqWords.appendChild(li);
      return;
    }

    top.forEach(([word, count]) => {
      const li = document.createElement('li');
      li.textContent = `${word} (${count})`;
      freqWords.appendChild(li);
    });
  };

  input.addEventListener('input', update);

  document.getElementById('exportStats').addEventListener('click', () => {
    const lines = [
      `Words: ${refs.words.textContent}`,
      `Characters: ${refs.chars.textContent}`,
      `Characters (no spaces): ${refs.charsNoSpaces.textContent}`,
      `Sentences: ${refs.sentences.textContent}`,
      `Paragraphs: ${refs.paragraphs.textContent}`,
      `Reading time: ${refs.readingTime.textContent}`,
      '',
      'Top words:',
      ...Array.from(freqWords.querySelectorAll('li')).map((li) => `- ${li.textContent}`),
    ];

    const blob = new Blob([lines.join('\n')], { type: 'text/plain;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = 'word-counter-stats.txt';
    link.click();
    URL.revokeObjectURL(url);
  });

  update();
})();
