document.addEventListener("htmx:afterSwap", (event) => {
  const target = event.target;
  if (target && target.id === "deployment-status") {
    target.scrollIntoView({ behavior: "smooth", block: "center" });
  }
});
