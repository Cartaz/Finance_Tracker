(() => {
  "use strict";

  const INSET = 5;
  const ACTIVE_MS = 500;
  const states = [];
  const heightStates = [];
  let frame = null;

  const AUTO_SCROLL_REGIONS = [
    ["transactions-list", "Transazioni"],
    ["accounts-list", "Conti e debiti"],
    ["categories-list", "Categorie"],
    ["budget-list", "Budget del mese"],
    ["loan-list", "Prestiti"],
    ["loan-detail", "Piano e pagamenti"],
  ];

  const HEIGHT_BINDINGS = [
    {
      sourceId: "transaction-create-heading",
      sourceClosest: ".card",
      targetId: "transactions-list",
      targetClosest: ".card",
      targetClass: "bounded-scroll-card",
    },
    {
      sourceId: "account-create-heading",
      sourceClosest: ".card",
      targetId: "account-overview-heading",
      targetClosest: ".card",
      targetClass: "bounded-scroll-card",
    },
    {
      sourceId: "budget-form",
      targetId: "budget-list",
      targetClosest: ".card",
      targetClass: "bounded-scroll-card",
    },
    {
      sourceId: "loan-form",
      targetId: "loan-list",
      targetClosest: ".stack",
      targetClass: "loan-output-bound",
    },
  ];

  function ensureRegionStylesheet() {
    if (document.querySelector('link[data-scroll-region-styles]')) return;
    const link = document.createElement("link");
    link.rel = "stylesheet";
    link.href = "scroll-regions.css";
    link.dataset.scrollRegionStyles = "";
    document.head.appendChild(link);
  }

  function configureAutoRegions() {
    AUTO_SCROLL_REGIONS.forEach(([id, label]) => {
      const region = document.getElementById(id);
      if (!region) return;
      region.dataset.scrollIndicator = "";
      if (!region.hasAttribute("tabindex")) region.tabIndex = 0;
      if (!region.hasAttribute("role")) region.setAttribute("role", "region");
      if (!region.hasAttribute("aria-label")) region.setAttribute("aria-label", label);
    });
  }

  function resolveConfiguredElement(config, prefix) {
    const element = document.getElementById(config[`${prefix}Id`]);
    const closest = config[`${prefix}Closest`];
    return element && closest ? element.closest(closest) : element;
  }

  function bindHeight(config) {
    const source = resolveConfiguredElement(config, "source");
    const target = resolveConfiguredElement(config, "target");
    if (!source || !target) return;
    source.classList.add("logic-height-source");
    target.classList.add(config.targetClass);
    heightStates.push({ source, target });
  }

  function updateHeightState(state) {
    const height = state.source.getBoundingClientRect().height;
    if (height > 0) state.target.style.setProperty("--logic-height", `${Math.round(height)}px`);
  }

  function scheduleUpdate() {
    if (frame !== null) return;
    frame = window.requestAnimationFrame(() => {
      frame = null;
      heightStates.forEach(updateHeightState);
      states.forEach(updateState);
    });
  }

  function setActive(state) {
    window.clearTimeout(state.activeTimer);
    state.pill.classList.add("active");
    state.activeTimer = window.setTimeout(() => {
      if (!state.dragging) state.pill.classList.remove("active");
    }, ACTIVE_MS);
  }

  function updateState(state) {
    const { region, pill } = state;
    const rect = region.getBoundingClientRect();
    const maxScroll = Math.max(0, region.scrollHeight - region.clientHeight);
    const pillHeight = pill.offsetHeight;
    const pillWidth = pill.offsetWidth;
    const trackTop = Math.max(rect.top, 0) + INSET;
    const trackBottom = Math.min(rect.bottom, window.innerHeight) - INSET;
    const trackHeight = trackBottom - trackTop;
    const visible = (
      maxScroll > 1
      && rect.width > 0
      && rect.right > 0
      && rect.left < window.innerWidth
      && trackHeight > pillHeight
    );

    pill.classList.toggle("visible", visible);
    if (!visible) {
      state.maxScroll = 0;
      state.travel = 0;
      return;
    }

    const travel = trackHeight - pillHeight;
    const progress = Math.min(1, Math.max(0, region.scrollTop / maxScroll));
    const left = Math.min(
      window.innerWidth - pillWidth - INSET,
      rect.right - pillWidth - INSET,
    );

    pill.style.left = `${Math.max(INSET, left)}px`;
    pill.style.top = `${trackTop + (travel * progress)}px`;
    state.maxScroll = maxScroll;
    state.travel = travel;
  }

  function beginDrag(state, event) {
    if (state.maxScroll <= 0 || state.travel <= 0) return;
    event.preventDefault();
    state.dragging = true;
    state.dragStartY = event.clientY;
    state.dragStartScroll = state.region.scrollTop;
    state.pill.classList.add("dragging", "active");
    state.pill.setPointerCapture(event.pointerId);
  }

  function moveDrag(state, event) {
    if (!state.dragging || state.travel <= 0) return;
    const delta = event.clientY - state.dragStartY;
    state.region.scrollTop = state.dragStartScroll + (
      delta * state.maxScroll / state.travel
    );
  }

  function endDrag(state) {
    if (!state.dragging) return;
    state.dragging = false;
    state.pill.classList.remove("dragging");
    setActive(state);
  }

  function bindRegion(region) {
    const pill = document.createElement("div");
    pill.className = "scroll-pill-indicator";
    pill.setAttribute("aria-hidden", "true");
    document.body.appendChild(pill);

    const state = {
      region,
      pill,
      maxScroll: 0,
      travel: 0,
      dragging: false,
      dragStartY: 0,
      dragStartScroll: 0,
      activeTimer: null,
    };
    states.push(state);

    region.addEventListener("scroll", () => {
      setActive(state);
      scheduleUpdate();
    }, { passive: true });
    pill.addEventListener("pointerdown", (event) => beginDrag(state, event));
    pill.addEventListener("pointermove", (event) => moveDrag(state, event));
    pill.addEventListener("pointerup", () => endDrag(state));
    pill.addEventListener("pointercancel", () => endDrag(state));
    pill.addEventListener("lostpointercapture", () => endDrag(state));

    const contentObserver = new MutationObserver(scheduleUpdate);
    contentObserver.observe(region, {
      childList: true,
      subtree: true,
      characterData: true,
    });

    return state;
  }

  ensureRegionStylesheet();
  configureAutoRegions();
  HEIGHT_BINDINGS.forEach(bindHeight);
  document.querySelectorAll("[data-scroll-indicator]").forEach(bindRegion);

  if (typeof ResizeObserver !== "undefined") {
    const resizeObserver = new ResizeObserver(scheduleUpdate);
    states.forEach(({ region }) => resizeObserver.observe(region));
    heightStates.forEach(({ source, target }) => {
      resizeObserver.observe(source);
      resizeObserver.observe(target);
    });
  }

  const visibilityObserver = new MutationObserver(scheduleUpdate);
  document.querySelectorAll("#setup,#app").forEach((element) => {
    visibilityObserver.observe(element, {
      attributes: true,
      subtree: true,
      attributeFilter: ["class"],
    });
  });

  window.addEventListener("resize", scheduleUpdate, { passive: true });
  window.addEventListener("load", scheduleUpdate, { once: true });
  scheduleUpdate();
})();
