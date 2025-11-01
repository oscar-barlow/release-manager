const nav = document.getElementById("app-nav");

function setActiveNav(tabName) {
  if (!nav) return;
  const buttons = nav.querySelectorAll("[data-nav-link]");
  buttons.forEach((btn) => {
    const isActive = btn.dataset.tab === tabName;
    btn.classList.toggle("active", isActive);
    btn.setAttribute("aria-current", isActive ? "page" : "false");
  });
}

if (nav) {
  nav.addEventListener("click", (event) => {
    const button = event.target.closest("[data-nav-link]");
    if (!button) return;
    setActiveNav(button.dataset.tab);
  });
}

document.addEventListener("htmx:beforeRequest", (event) => {
  const { elt, requestConfig } = event.detail || {};
  if (!elt || !elt.hasAttribute("data-nav-link")) return;
  if (!requestConfig) return;
  const tabName = elt.dataset.tab;
  if (tabName) {
    setActiveNav(tabName);
  }
});

document.addEventListener("htmx:afterSwap", (event) => {
  const target = event.target;
  if (target && target.id === "deployment-status") {
    target.scrollIntoView({ behavior: "smooth", block: "center" });
  }
});
