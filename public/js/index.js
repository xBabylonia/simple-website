(() => {
  const searchInput = document.getElementById('globalSearch');
  const tabs = [...document.querySelectorAll('#categoryTabs .tab')];
  const cards = [...document.querySelectorAll('#toolGrid .tool-card')];
  const empty = document.getElementById('emptyState');
  const filterSummary = document.getElementById('filterSummary');
  const resetFiltersButton = document.getElementById('resetFilters');
  const validCategories = new Set(tabs.map((tab) => tab.dataset.category));
  const totalTools = cards.length;
  const params = new URLSearchParams(window.location.search);
  let activeCategory = 'all';
  let searchDebounceTimer;

  const updateUrlState = (term) => {
    const nextParams = new URLSearchParams(window.location.search);
    if (term) {
      nextParams.set('q', term);
    } else {
      nextParams.delete('q');
    }

    if (activeCategory && activeCategory !== 'all') {
      nextParams.set('category', activeCategory);
    } else {
      nextParams.delete('category');
    }

    const query = nextParams.toString();
    const nextUrl = query ? `${window.location.pathname}?${query}` : window.location.pathname;
    window.history.replaceState({}, '', nextUrl);
  };

  const setActiveTab = (nextCategory) => {
    tabs.forEach((tab) => {
      const isActive = tab.dataset.category === nextCategory;
      tab.classList.toggle('active', isActive);
    });
  };

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
    if (filterSummary) {
      filterSummary.textContent = `Showing ${shown} of ${totalTools} tools`;
    }
    resetFiltersButton?.classList.toggle('hidden', !term && activeCategory === 'all');
    updateUrlState(term);
  };

  const setCategory = (nextCategory) => {
    activeCategory = validCategories.has(nextCategory) ? nextCategory : 'all';
    setActiveTab(activeCategory);
    applyFilters();
  };

  const resetFilters = () => {
    if (searchInput) {
      searchInput.value = '';
    }
    setCategory('all');
  };

  tabs.forEach((tab) => {
    tab.addEventListener('click', () => {
      setCategory(tab.dataset.category);
    });
  });

  searchInput?.addEventListener('input', () => {
    window.clearTimeout(searchDebounceTimer);
    searchDebounceTimer = window.setTimeout(applyFilters, 120);
  });

  searchInput?.addEventListener('keydown', (event) => {
    if (event.key !== 'Escape') {
      return;
    }
    event.preventDefault();
    searchInput.value = '';
    applyFilters();
  });

  document.addEventListener('keydown', (event) => {
    if (event.key !== '/' || event.ctrlKey || event.metaKey || event.altKey) {
      return;
    }

    const target = event.target;
    const isEditable = target && (
      target.tagName === 'INPUT' ||
      target.tagName === 'TEXTAREA' ||
      target.isContentEditable
    );
    if (isEditable) {
      return;
    }

    event.preventDefault();
    searchInput?.focus();
  });

  resetFiltersButton?.addEventListener('click', resetFilters);

  const initialQuery = (params.get('q') || '').trim();
  if (searchInput && initialQuery) {
    searchInput.value = initialQuery;
  }
  setCategory(params.get('category') || 'all');
})();
