(() => {
  const searchInput = document.getElementById('globalSearch');
  const tabs = [...document.querySelectorAll('#categoryTabs .tab')];
  const cards = [...document.querySelectorAll('#toolGrid .tool-card')];
  const empty = document.getElementById('emptyState');
  let activeCategory = 'all';

  const applyFilters = () => {
    const term = (searchInput?.value || '').toLowerCase().trim();
    let shown = 0;

    cards.forEach((card) => {
      const category = card.dataset.category;
      const hay = `${card.dataset.name} ${card.dataset.desc}`;
      const categoryOk = activeCategory === 'all' || category === activeCategory;
      const searchOk = !term || hay.includes(term);
      const visible = categoryOk && searchOk;
      card.classList.toggle('hidden', !visible);
      if (visible) shown += 1;
    });

    empty.classList.toggle('hidden', shown !== 0);
  };

  tabs.forEach((tab) => {
    tab.addEventListener('click', () => {
      tabs.forEach((x) => x.classList.remove('active'));
      tab.classList.add('active');
      activeCategory = tab.dataset.category;
      applyFilters();
    });
  });

  searchInput?.addEventListener('input', applyFilters);
  applyFilters();
})();
