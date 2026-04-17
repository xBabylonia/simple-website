const navToggle = document.querySelector('.nav-toggle');
const navLinksWrap = document.querySelector('.nav-links');
const navLinks = document.querySelectorAll('.nav-link');
const header = document.querySelector('.topbar');
const counters = document.querySelectorAll('[data-counter]');
const revealables = document.querySelectorAll('.reveal');

const closeNav = () => navLinksWrap?.classList.remove('open');

navToggle?.addEventListener('click', () => {
  navLinksWrap?.classList.toggle('open');
});

navLinks.forEach((link) => {
  link.addEventListener('click', () => {
    closeNav();
  });
});

window.addEventListener('resize', () => {
  if (window.innerWidth > 1080) closeNav();
});

window.addEventListener('keydown', (evt) => {
  if (evt.key === 'Escape') closeNav();
});

window.addEventListener('scroll', () => {
  if (!header) return;
  header.classList.toggle('is-scrolled', window.scrollY > 12);
});

const sectionObserver = new IntersectionObserver(
  (entries) => {
    entries.forEach((entry) => {
      const id = entry.target.getAttribute('id');
      const link = document.querySelector(`.nav-link[href="#${id}"]`);
      if (entry.isIntersecting) {
        link?.classList.add('active');
      } else {
        link?.classList.remove('active');
      }
    });
  },
  { threshold: 0.45 }
);

document.querySelectorAll('main section[id]').forEach((section) => {
  sectionObserver.observe(section);
});

const animateCounter = (el) => {
  if (el.dataset.started) return;
  el.dataset.started = 'true';
  const target = Number(el.dataset.target || 0);
  const duration = 900;
  const start = performance.now();
  const easeOut = (t) => 1 - Math.pow(1 - t, 3);

  const tick = (now) => {
    const progress = Math.min((now - start) / duration, 1);
    const value = Math.floor(easeOut(progress) * target);
    el.textContent = value;
    if (progress < 1) requestAnimationFrame(tick);
  };

  requestAnimationFrame(tick);
};

const revealObserver = new IntersectionObserver(
  (entries) => {
    entries.forEach((entry) => {
      if (entry.isIntersecting) {
        entry.target.classList.add('visible');
        entry.target.querySelectorAll('[data-counter]').forEach(animateCounter);
      }
    });
  },
  { threshold: 0.2 }
);

revealables.forEach((node) => revealObserver.observe(node));
counters.forEach((counter) => {
  if (counter.closest('.reveal')) return;
  animateCounter(counter);
});
