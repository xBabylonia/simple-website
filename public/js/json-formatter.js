(() => {
  const input = document.getElementById('jsonInput');
  const output = document.getElementById('jsonOutput');
  const status = document.getElementById('jsonStatus');

  const setOutput = (value) => {
    output.textContent = value;
    if (window.hljs) {
      window.hljs.highlightElement(output);
    }
  };

  const parseJson = () => {
    try {
      return { data: JSON.parse(input.value) };
    } catch (error) {
      const msg = error.message || 'Invalid JSON';
      const match = msg.match(/position\s(\d+)/i);
      if (!match) {
        throw new Error(msg);
      }
      const pos = Number(match[1]);
      const before = input.value.slice(0, pos);
      const line = before.split('\n').length;
      throw new Error(`${msg} (line ${line})`);
    }
  };

  document.getElementById('formatJson').addEventListener('click', () => {
    try {
      const { data } = parseJson();
      setOutput(JSON.stringify(data, null, 2));
      status.textContent = 'JSON formatted successfully.';
    } catch (error) {
      status.textContent = error.message;
    }
  });

  document.getElementById('minifyJson').addEventListener('click', () => {
    try {
      const { data } = parseJson();
      setOutput(JSON.stringify(data));
      status.textContent = 'JSON minified successfully.';
    } catch (error) {
      status.textContent = error.message;
    }
  });

  document.getElementById('validateJson').addEventListener('click', () => {
    try {
      parseJson();
      status.textContent = 'Valid JSON ✅';
    } catch (error) {
      status.textContent = `Invalid JSON ❌ ${error.message}`;
    }
  });

  document.getElementById('copyJson').addEventListener('click', async () => {
    if (!output.textContent) return;
    await navigator.clipboard.writeText(output.textContent);
    status.textContent = 'Output copied to clipboard.';
  });
})();
