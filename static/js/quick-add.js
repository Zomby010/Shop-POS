// "+ New" at the bottom of dropdowns: <select data-quick-add="supplier"> gets an option that opens a small
// pop-up, saves the new record, and selects it. Every dropdown of the same kind on the page gets the new option.
(function () {
  const allowed = (document.body.dataset.quickAdd || "").split(" ").filter(Boolean);
  const NEW = "__new__";
  const titles = {
    category: "New category", quick_category: "New quick-sale category", expense_category: "New expense category",
    supplier: "New supplier", customer: "New customer", product: "New product",
  };
  const csrf = () => (document.cookie.match(/csrftoken=([^;]+)/) || [])[1] ||
    JSON.parse(document.body.getAttribute("hx-headers") || "{}")["X-CSRFToken"];

  const dialog = document.createElement("dialog");
  dialog.className = "quick-add-dialog";
  dialog.innerHTML = '<form class="stacked"><h2 style="margin-top:0"></h2><div class="qa-fields"></div>' +
    '<div class="toolbar"><button class="btn primary" type="submit">Save</button>' +
    '<button class="btn" type="button" data-qa-cancel>Cancel</button></div></form>';
  document.body.appendChild(dialog);
  const form = dialog.querySelector("form");
  const fields = dialog.querySelector(".qa-fields");
  let current = null; // {select, kind, previous}

  function enhance(select) {
    const kind = select.dataset.quickAdd;
    if (!allowed.includes(kind) || select.querySelector(`option[value="${NEW}"]`)) return;
    const opt = new Option(`+ New ${titles[kind].replace(/^New /, "")}…`, NEW);
    opt.className = "quick-add-option";
    select.appendChild(opt);
    select.dataset.previous = select.value;
    select.addEventListener("focus", () => { if (select.value !== NEW) select.dataset.previous = select.value; });
    select.addEventListener("change", (e) => {
      if (select.value !== NEW) { select.dataset.previous = select.value; return; }
      e.stopImmediatePropagation();
      open(select, kind);
    }, true);
  }

  async function open(select, kind) {
    current = { select, kind };
    select.value = select.dataset.previous || "";
    const res = await fetch(`/quick-add/${kind}/`, { headers: { "X-Requested-With": "fetch" } });
    if (!res.ok) { alert("You can't add that here. Ask the owner."); return; }
    dialog.querySelector("h2").textContent = titles[kind];
    fields.innerHTML = await res.text();
    dialog.showModal();
    fields.querySelector("input, select")?.focus();
  }

  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const { select, kind } = current;
    const res = await fetch(`/quick-add/${kind}/`, {
      method: "POST", body: new FormData(form), headers: { "X-CSRFToken": csrf() },
    });
    if (res.status === 400) { fields.innerHTML = await res.text(); fields.querySelector("input")?.focus(); return; }
    if (!res.ok) { alert("Could not save. Please try again."); return; }
    const item = await res.json();
    document.querySelectorAll(`select[data-quick-add="${kind}"]`).forEach((s) => {
      s.insertBefore(new Option(item.label, item.id), s.querySelector(`option[value="${NEW}"]`));
    });
    select.value = String(item.id);
    select.dataset.previous = select.value;
    dialog.close();
    document.dispatchEvent(new CustomEvent("quickadd:created", { detail: { kind, ...item } }));
    select.dispatchEvent(new Event("change", { bubbles: true }));
    select.focus();
  });
  dialog.querySelector("[data-qa-cancel]").addEventListener("click", () => { dialog.close(); current?.select.focus(); });

  const scan = (root) => root.querySelectorAll?.("select[data-quick-add]").forEach(enhance);
  scan(document);
  // Rows added later (formsets, HTMX swaps) get the option too.
  new MutationObserver((records) => records.forEach((r) => r.addedNodes.forEach((n) => {
    if (n.nodeType !== 1 || dialog.contains(n)) return;
    if (n.matches("select[data-quick-add]")) enhance(n); else scan(n);
  }))).observe(document.body, { childList: true, subtree: true });
})();
