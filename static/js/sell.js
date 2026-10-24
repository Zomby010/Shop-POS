// Sell screen: keyboard shortcuts, quick-sale tabs, custom amounts, owner PIN prompts and the payment dialog.
(function () {
  const root = document.querySelector(".sell");
  const isOwner = root.dataset.owner === "1";
  const scan = document.getElementById("scan");
  const customDialog = document.getElementById("custom-dialog");
  const payDialog = document.getElementById("pay-dialog");
  const money = (n) => (Math.round(n * 100) / 100).toLocaleString("en-KE", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  const num = (el) => parseFloat((el.value || "0").replace(/,/g, "")) || 0;
  const cartTotal = () => parseFloat(document.querySelector("#cart .cart")?.dataset.total || "0");

  // Quick-sale tabs (click or F1..F8)
  function showTab(index) {
    document.querySelectorAll(".quick-tab").forEach((t) => t.classList.toggle("active", t.dataset.tab === String(index)));
    document.querySelectorAll(".quick-panel").forEach((p) => p.classList.toggle("active", p.dataset.panel === String(index)));
  }
  document.querySelectorAll(".quick-tab").forEach((t) => t.addEventListener("click", () => showTab(t.dataset.tab)));

  // Custom quantity / amount
  document.addEventListener("click", (e) => {
    const btn = e.target.closest(".custom");
    if (!btn) return;
    document.getElementById("custom-title").textContent = btn.dataset.name;
    document.getElementById("custom-product").value = btn.dataset.product;
    document.getElementById("custom-unit").textContent = btn.dataset.unit;
    document.getElementById("custom-amount-mode").hidden = btn.dataset.loose !== "1";
    document.getElementById("custom-value").setAttribute("inputmode", btn.dataset.loose === "1" ? "decimal" : "numeric");
    customDialog.querySelector('input[value="qty"]').checked = true;
    customDialog.dataset.price = btn.dataset.price;
    customDialog.dataset.unit = btn.dataset.unit;
    const value = document.getElementById("custom-value");
    value.value = "";
    document.getElementById("custom-preview").textContent = "";
    customDialog.showModal();
    value.focus();
  });
  customDialog.addEventListener("input", () => {
    const price = parseFloat(customDialog.dataset.price);
    const v = num(document.getElementById("custom-value"));
    const byAmount = customDialog.querySelector('input[value="amount"]').checked;
    const unit = customDialog.dataset.unit;
    document.getElementById("custom-preview").textContent = !v ? "" : byAmount
      ? `About ${(v / price).toFixed(3)} ${unit} (bulk prices may give more)`
      : `About KSh ${money(v * price)}`;
  });

  // Owner PIN when lowering or removing a cart line
  document.body.addEventListener("htmx:configRequest", (e) => {
    const el = e.detail.elt;
    const lowering = el.dataset.remove === "1" ||
      (el.classList.contains("qty-input") && parseFloat(el.value) < parseFloat(el.dataset.old));
    if (!lowering || isOwner) return;
    const pin = window.prompt("Owner PIN to reduce or remove this item:");
    if (pin === null) { e.preventDefault(); el.value = el.dataset.old || el.value; return; }
    e.detail.parameters.pin = pin;
  });

  // Hold
  function hold() {
    const btn = document.getElementById("hold-btn");
    if (!btn || btn.disabled) return;
    const label = window.prompt("Name for this held sale (e.g. customer's name):", "");
    if (label === null) return;
    htmx.ajax("POST", "/sell/cart/hold/", { target: "#cart", values: { label } });
  }

  // Payment dialog
  const mpesa = document.getElementById("pay-mpesa");
  const credit = document.getElementById("pay-credit");
  const cash = document.getElementById("pay-cash");
  function updatePay() {
    const total = cartTotal();
    const due = Math.max(total - num(mpesa) - num(credit), 0);
    document.getElementById("pay-total").textContent = "KSh " + money(total);
    document.getElementById("pay-cash-due").textContent = money(due);
    const given = cash.value === "" ? due : num(cash);
    document.getElementById("pay-change").textContent = money(Math.max(given - due, 0));
    document.getElementById("pay-customer").hidden = num(credit) <= 0;
    document.getElementById("pay-mpesa-code-row").hidden = num(mpesa) <= 0;
  }
  function setMode(mode) {
    const total = cartTotal();
    mpesa.value = mode === "mpesa" ? total : "";
    credit.value = mode === "credit" ? total : "";
    cash.value = "";
    document.getElementById("pay-mpesa-code").value = "";
    updatePay();
    ({ cash, mpesa: cash, split: mpesa, credit: credit })[mode].focus();
  }
  function openPay() {
    const btn = document.getElementById("pay-btn");
    if (!btn || btn.disabled) return;
    document.getElementById("pay-error").innerHTML = "";
    payDialog.showModal();
    setMode("cash");
  }
  payDialog.addEventListener("input", updatePay);
  payDialog.querySelectorAll("[data-pay-mode]").forEach((b) => b.addEventListener("click", () => setMode(b.dataset.payMode)));

  document.addEventListener("click", (e) => {
    if (e.target.closest("#pay-btn")) openPay();
    if (e.target.closest("#hold-btn")) hold();
    if (e.target.closest("[data-close]")) { e.target.closest("dialog").close(); scan.focus(); }
  });

  // After the cart changes, keep the scanner ready
  document.body.addEventListener("htmx:afterSwap", (e) => {
    if (e.detail.target.id === "cart" && !payDialog.open && !customDialog.open) scan.focus();
  });

  document.addEventListener("keydown", (e) => {
    const f = /^F([1-8])$/.exec(e.key);
    if (f) { e.preventDefault(); showTab(Number(f[1]) - 1); return; }
    if (e.key === "F9") { e.preventDefault(); openPay(); }
    if (e.key === "F10") { e.preventDefault(); hold(); }
    if (e.key === "Escape" && !payDialog.open && !customDialog.open) scan.focus();
  });
})();
