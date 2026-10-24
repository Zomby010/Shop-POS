// Small layout helpers: the phone menu and side-scrolling for wide tables.
(function () {
  var toggle = document.querySelector(".nav-toggle");
  if (toggle) {
    toggle.addEventListener("click", function () {
      var open = document.body.classList.toggle("nav-open");
      toggle.setAttribute("aria-expanded", open ? "true" : "false");
    });
  }

  // Wrap tables so a wide one scrolls sideways inside its box instead of stretching the page.
  function wrapTables(root) {
    root.querySelectorAll("main table").forEach(function (table) {
      if (table.closest(".table-wrap, .doc-paper, .receipt-paper")) return;
      var wrap = document.createElement("div");
      wrap.className = "table-wrap";
      table.parentNode.insertBefore(wrap, table);
      wrap.appendChild(table);
    });
  }
  wrapTables(document);
  document.body.addEventListener("htmx:afterSettle", function () { wrapTables(document); });
})();
