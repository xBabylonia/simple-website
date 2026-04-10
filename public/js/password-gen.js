(() => {
  const lengthRange = document.getElementById('lengthRange');
  const lengthValue = document.getElementById('lengthValue');
  const batchCountInput = document.getElementById('batchCount');
  const results = document.getElementById('passwordResults');
  const strengthLabel = document.getElementById('strengthLabel');
  const strengthBar = document.getElementById('strengthBar');

  const checks = {
    upper: document.getElementById('useUpper'),
    lower: document.getElementById('useLower'),
    numbers: document.getElementById('useNumbers'),
    symbols: document.getElementById('useSymbols'),
  };

  const pools = {
    upper: 'ABCDEFGHIJKLMNOPQRSTUVWXYZ',
    lower: 'abcdefghijklmnopqrstuvwxyz',
    numbers: '0123456789',
    symbols: '!@#$%^&*()_+-=[]{}|;:,.<>?',
  };

  const randomChar = (pool) => pool[Math.floor(Math.random() * pool.length)];

  const selectedPools = () => Object.keys(checks).filter((key) => checks[key].checked);

  const generateOne = (length) => {
    const selected = selectedPools();
    if (!selected.length) return '';

    const chars = [];
    selected.forEach((key) => chars.push(randomChar(pools[key])));

    const combined = selected.map((key) => pools[key]).join('');
    while (chars.length < length) {
      chars.push(randomChar(combined));
    }

    for (let i = chars.length - 1; i > 0; i -= 1) {
      const j = Math.floor(Math.random() * (i + 1));
      [chars[i], chars[j]] = [chars[j], chars[i]];
    }

    return chars.join('').slice(0, length);
  };

  const scoreStrength = (password) => {
    let score = 0;
    if (password.length >= 12) score += 1;
    if (password.length >= 16) score += 1;
    if (/[A-Z]/.test(password)) score += 1;
    if (/[a-z]/.test(password)) score += 1;
    if (/[0-9]/.test(password)) score += 1;
    if (/[^A-Za-z0-9]/.test(password)) score += 1;

    if (score <= 2) return { label: 'weak', width: '25%', color: '#ef4444' };
    if (score <= 4) return { label: 'fair', width: '50%', color: '#f59e0b' };
    if (score <= 5) return { label: 'strong', width: '75%', color: '#10b981' };
    return { label: 'very strong', width: '100%', color: '#059669' };
  };

  const render = (passwords) => {
    results.innerHTML = '';

    if (!passwords.length || !passwords[0]) {
      strengthLabel.textContent = 'Strength: weak';
      strengthBar.style.width = '25%';
      strengthBar.style.background = '#ef4444';
      results.innerHTML = '<p class="muted">Enable at least one character set.</p>';
      return;
    }

    const topStrength = scoreStrength(passwords[0]);
    strengthLabel.textContent = `Strength: ${topStrength.label}`;
    strengthBar.style.width = topStrength.width;
    strengthBar.style.background = topStrength.color;

    passwords.forEach((pwd, idx) => {
      const row = document.createElement('div');
      row.className = 'password-item';
      row.innerHTML = `<code>${pwd}</code><button class="btn ghost" type="button">Copy</button>`;
      row.querySelector('button').addEventListener('click', async (event) => {
        await navigator.clipboard.writeText(pwd);
        event.currentTarget.textContent = 'Copied';
        setTimeout(() => {
          event.currentTarget.textContent = 'Copy';
        }, 900);
      });
      row.querySelector('code').setAttribute('aria-label', `Generated password ${idx + 1}`);
      results.appendChild(row);
    });
  };

  const generate = () => {
    const length = Number(lengthRange.value);
    const batch = Math.max(1, Math.min(20, Number(batchCountInput.value) || 1));
    batchCountInput.value = String(batch);

    const passwords = Array.from({ length: batch }, () => generateOne(length));
    render(passwords);
  };

  lengthRange.addEventListener('input', () => {
    lengthValue.textContent = lengthRange.value;
    generate();
  });

  Object.values(checks).forEach((el) => el.addEventListener('change', generate));
  document.getElementById('generatePasswords').addEventListener('click', generate);

  generate();
})();
