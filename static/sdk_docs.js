(() => {
  // Filter the docs sidebar based on the search input.
  const searchEl = document.getElementById("sdk-docs-search");
  const sidebarEl = document.getElementById("sdk-docs-sidebar");

  if (!searchEl || !sidebarEl) return;

  const applyFilter = () => {
    const q = (searchEl.value || "").trim().toLowerCase();
    const moduleEls = sidebarEl.querySelectorAll(".docs-sidebar-module");

    moduleEls.forEach((moduleEl) => {
      const moduleLabel = (moduleEl.dataset.moduleLabel || "").toLowerCase();
      const items = moduleEl.querySelectorAll(".docs-sidebar-item");

      if (!q) {
        moduleEl.style.display = "";
        items.forEach((it) => (it.style.display = ""));
        return;
      }

      let moduleMatches = moduleLabel.includes(q);
      let anyChildMatches = false;

      items.forEach((itemEl) => {
        const childLabel = (itemEl.dataset.symbolLabel || "").toLowerCase();
        const childMatches = childLabel.includes(q);
        if (childMatches) anyChildMatches = true;

        // If the module matches, keep all children visible; otherwise hide non-matching children.
        itemEl.style.display = moduleMatches || childMatches ? "" : "none";
      });

      moduleEl.style.display = moduleMatches || anyChildMatches ? "" : "none";
    });
  };

  searchEl.addEventListener("input", applyFilter);
  applyFilter();
})();

