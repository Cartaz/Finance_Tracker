(() => {
  "use strict";

  const INSET = 5;
  const ACTIVE_MS = 500;
  const states = [];
  let frame = null;

  function scheduleUpdate() {
    if (frame !== null) return;
    frame = window.requestAnimationFrame(() => {
      frame = null;
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

  document.querySelectorAll("[data-scroll-indicator]").forEach(bindRegion);

  if (typeof ResizeObserver !== "undefined") {
    const resizeObserver = new ResizeObserver(scheduleUpdate);
    states.forEach(({ region }) => resizeObserver.observe(region));
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
