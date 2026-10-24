// "+ Add line" for Django formsets, so a list never runs out of empty rows.
// Markup: <div data-formset="PREFIX"> with the management form, a [data-formset-body] holding the rows,
// a <template data-formset-template> holding formset.empty_form as a row, and a [data-formset-add] button.
// New rows carry a [data-formset-remove] button that simply takes them away again.
(function () {
  function addRow(container) {
    const prefix = container.dataset.formset;
    const total = container.querySelector(`[name="${prefix}-TOTAL_FORMS"]`);
    const index = Number(total.value);
    const html = container.querySelector("template[data-formset-template]").innerHTML.replace(/__prefix__/g, index);
    const body = container.querySelector("[data-formset-body]");
    const holder = document.createElement(body.tagName === "TBODY" ? "tbody" : "div");
    holder.innerHTML = html.trim();
    const row = holder.firstElementChild;
    body.appendChild(row);
    total.value = index + 1;
    row.querySelector("input:not([type=hidden]), select, textarea")?.focus();
    row.dispatchEvent(new Event("formset:added", { bubbles: true }));
    return row;
  }

  document.addEventListener("click", (e) => {
    const add = e.target.closest("[data-formset-add]");
    if (add) { e.preventDefault(); addRow(add.closest("[data-formset]")); return; }
    const remove = e.target.closest("[data-formset-remove]");
    if (remove) {
      e.preventDefault();
      const row = remove.closest("[data-formset-row]");
      // Blank the row instead of renumbering: an empty row is skipped when the form is saved.
      row.querySelectorAll("input, select, textarea").forEach((el) => {
        if (el.type === "checkbox") el.checked = false; else if (el.type !== "hidden") el.value = "";
      });
      row.hidden = true;
      row.dispatchEvent(new Event("input", { bubbles: true }));
    }
  });
})();
