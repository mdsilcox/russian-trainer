// htmx ignores 4xx responses by default. The shelf answers a bad "Log time" with 422
// and a short message, so let those swap in.
document.addEventListener("htmx:beforeSwap", (event) => {
  if (event.detail.xhr.status === 422) {
    event.detail.shouldSwap = true;
    event.detail.isError = false;
  }
});
