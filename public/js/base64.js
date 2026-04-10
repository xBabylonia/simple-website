(() => {
  const plain = document.getElementById('plainText');
  const b64 = document.getElementById('base64Text');
  const auto = document.getElementById('autoDetect');
  const fileInput = document.getElementById('fileInput');
  const status = document.getElementById('base64Status');

  const encode = (text) => btoa(unescape(encodeURIComponent(text)));
  const decode = (value) => decodeURIComponent(escape(atob(value)));

  const isLikelyBase64 = (str) => {
    const clean = str.trim();
    if (!clean || clean.length % 4 !== 0) return false;
    return /^[A-Za-z0-9+/=\r\n]+$/.test(clean);
  };

  const runEncode = () => {
    try {
      b64.value = encode(plain.value);
      status.textContent = 'Encoded successfully.';
    } catch {
      status.textContent = 'Unable to encode input.';
    }
  };

  const runDecode = () => {
    try {
      plain.value = decode(b64.value.replace(/\s+/g, ''));
      status.textContent = 'Decoded successfully.';
    } catch {
      status.textContent = 'Invalid Base64 value.';
    }
  };

  document.getElementById('encodeBtn').addEventListener('click', runEncode);
  document.getElementById('decodeBtn').addEventListener('click', runDecode);

  plain.addEventListener('input', () => {
    if (!auto.checked) return;
    runEncode();
  });

  b64.addEventListener('input', () => {
    if (!auto.checked || !isLikelyBase64(b64.value)) return;
    runDecode();
  });

  fileInput.addEventListener('change', () => {
    const [file] = fileInput.files;
    if (!file) return;
    const reader = new FileReader();
    reader.onload = () => {
      const result = String(reader.result || '');
      const base64Part = result.includes(',') ? result.split(',')[1] : result;
      b64.value = base64Part;
      status.textContent = `Loaded and encoded file: ${file.name}`;
    };
    reader.readAsDataURL(file);
  });

  document.getElementById('copyBase64').addEventListener('click', async () => {
    await navigator.clipboard.writeText(b64.value);
    status.textContent = 'Base64 copied.';
  });

  document.getElementById('copyPlain').addEventListener('click', async () => {
    await navigator.clipboard.writeText(plain.value);
    status.textContent = 'Plain text copied.';
  });

  document.getElementById('downloadBase64').addEventListener('click', () => {
    const blob = new Blob([b64.value], { type: 'text/plain;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = 'base64-output.txt';
    link.click();
    URL.revokeObjectURL(url);
  });
})();
