(() => {
  "use strict";

  function tabsFor(tabList) {
    return [...tabList.querySelectorAll(':scope > [role="tab"][data-tab-target]')];
  }

  function activateTab(tab, { focus = false } = {}) {
    const tabList = tab.closest('[role="tablist"]');
    if (!tabList) return;

    const tabs = tabsFor(tabList);
    for (const item of tabs) {
      const selected = item === tab;
      item.classList.toggle("active", selected);
      item.setAttribute("aria-selected", selected ? "true" : "false");
      item.tabIndex = selected ? 0 : -1;
      const panel = document.getElementById(item.dataset.tabTarget);
      if (panel) panel.classList.toggle("hidden", !selected);
    }

    if (focus) tab.focus();
  }

  function moveFocus(tab, direction) {
    const tabList = tab.closest('[role="tablist"]');
    if (!tabList) return;
    const tabs = tabsFor(tabList);
    const index = tabs.indexOf(tab);
    if (index < 0) return;

    let targetIndex = index;
    if (direction === "next") targetIndex = (index + 1) % tabs.length;
    if (direction === "previous") targetIndex = (index - 1 + tabs.length) % tabs.length;
    if (direction === "first") targetIndex = 0;
    if (direction === "last") targetIndex = tabs.length - 1;
    activateTab(tabs[targetIndex], { focus: true });
  }

  document.querySelectorAll('[role="tablist"][data-tab-group]').forEach((tabList) => {
    tabsFor(tabList).forEach((tab) => {
      tab.addEventListener("click", () => activateTab(tab));
      tab.addEventListener("keydown", (event) => {
        const directions = {
          ArrowRight: "next",
          ArrowLeft: "previous",
          Home: "first",
          End: "last",
        };
        const direction = directions[event.key];
        if (!direction) return;
        event.preventDefault();
        moveFocus(tab, direction);
      });
    });

    const initial = tabsFor(tabList).find((tab) => tab.getAttribute("aria-selected") === "true")
      || tabsFor(tabList)[0];
    if (initial) activateTab(initial);
  });
})();
