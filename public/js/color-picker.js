(() => {
  const colorInput = document.getElementById('colorInput');
  const hexRef = document.getElementById('hexValue');
  const rgbRef = document.getElementById('rgbValue');
  const hslRef = document.getElementById('hslValue');
  const cmykRef = document.getElementById('cmykValue');
  const palette = document.getElementById('palette');

  const hexToRgb = (hex) => {
    const clean = hex.replace('#', '');
    const val = parseInt(clean, 16);
    return {
      r: (val >> 16) & 255,
      g: (val >> 8) & 255,
      b: val & 255,
    };
  };

  const rgbToHsl = ({ r, g, b }) => {
    const rn = r / 255;
    const gn = g / 255;
    const bn = b / 255;
    const max = Math.max(rn, gn, bn);
    const min = Math.min(rn, gn, bn);
    const d = max - min;
    let h = 0;

    if (d !== 0) {
      if (max === rn) h = ((gn - bn) / d) % 6;
      else if (max === gn) h = (bn - rn) / d + 2;
      else h = (rn - gn) / d + 4;
      h = Math.round(h * 60);
      if (h < 0) h += 360;
    }

    const l = (max + min) / 2;
    const s = d === 0 ? 0 : d / (1 - Math.abs(2 * l - 1));

    return {
      h,
      s: Math.round(s * 100),
      l: Math.round(l * 100),
    };
  };

  const rgbToCmyk = ({ r, g, b }) => {
    if (r === 0 && g === 0 && b === 0) {
      return { c: 0, m: 0, y: 0, k: 100 };
    }

    const rn = r / 255;
    const gn = g / 255;
    const bn = b / 255;
    const k = 1 - Math.max(rn, gn, bn);
    const c = (1 - rn - k) / (1 - k);
    const m = (1 - gn - k) / (1 - k);
    const y = (1 - bn - k) / (1 - k);

    return {
      c: Math.round(c * 100),
      m: Math.round(m * 100),
      y: Math.round(y * 100),
      k: Math.round(k * 100),
    };
  };

  const clamp = (n) => Math.min(255, Math.max(0, n));
  const toHex = (n) => clamp(n).toString(16).padStart(2, '0').toUpperCase();

  const tint = ({ r, g, b }, factor) => ({
    r: Math.round(r + (255 - r) * factor),
    g: Math.round(g + (255 - g) * factor),
    b: Math.round(b + (255 - b) * factor),
  });

  const shade = ({ r, g, b }, factor) => ({
    r: Math.round(r * (1 - factor)),
    g: Math.round(g * (1 - factor)),
    b: Math.round(b * (1 - factor)),
  });

  const rgbToHex = ({ r, g, b }) => `#${toHex(r)}${toHex(g)}${toHex(b)}`;

  const renderPalette = (rgb) => {
    palette.innerHTML = '';
    const shades = [];

    for (let i = 5; i >= 1; i -= 1) shades.push(tint(rgb, i * 0.12));
    shades.push(rgb);
    for (let i = 1; i <= 5; i += 1) shades.push(shade(rgb, i * 0.12));

    shades.forEach((item) => {
      const hex = rgbToHex(item);
      const swatch = document.createElement('button');
      swatch.type = 'button';
      swatch.className = 'swatch';
      swatch.style.background = hex;
      swatch.innerHTML = `<span>${hex}</span>`;
      swatch.addEventListener('click', async () => {
        await navigator.clipboard.writeText(hex);
      });
      palette.appendChild(swatch);
    });
  };

  const update = () => {
    const hex = colorInput.value.toUpperCase();
    const rgb = hexToRgb(hex);
    const hsl = rgbToHsl(rgb);
    const cmyk = rgbToCmyk(rgb);

    hexRef.textContent = hex;
    rgbRef.textContent = `rgb(${rgb.r}, ${rgb.g}, ${rgb.b})`;
    hslRef.textContent = `hsl(${hsl.h}, ${hsl.s}%, ${hsl.l}%)`;
    cmykRef.textContent = `cmyk(${cmyk.c}%, ${cmyk.m}%, ${cmyk.y}%, ${cmyk.k}%)`;

    renderPalette(rgb);
  };

  document.querySelectorAll('.copy-btn').forEach((btn) => {
    btn.addEventListener('click', async () => {
      const target = document.getElementById(btn.dataset.copyTarget);
      await navigator.clipboard.writeText(target.textContent);
      btn.textContent = 'Copied';
      setTimeout(() => {
        btn.textContent = 'Copy';
      }, 800);
    });
  });

  colorInput.addEventListener('input', update);
  update();
})();
