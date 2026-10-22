# Build prompt: Shop POS for a minimart

You are building **Shop POS**, a point of sale system for one small minimart in Kenya. Build it in the repository `Zomby010/Shop-POS`, which is empty. Read this whole prompt before writing code. Build in the four stages under "Build order". Finish one stage, with tests passing and a short README update, before starting the next.

## 1. The business

- A single minimart with a high number of sales each day. Some customers buy large quantities at once.
- It sells two kinds of goods:
  - **Barcoded goods** (soap, soda, bread), scanned with a USB barcode scanner.
  - **Loose goods without barcodes**, sold by weight or volume: rice (Pishori, Basmati, Kamande), beans, sugar, flour, cooking oil, paraffin. Customers ask for a quantity ("1/4 kg Pishori") or an amount of money ("KSh 50 of oil").
- It runs on **one Windows laptop** with a barcode scanner and a thermal receipt printer.
- Mostly one person (the owner) uses it, but it must support separate logins and permissions.
- Currency is Kenyan shillings (KSh). Payments are cash or M-Pesa.

## 2. Technology

- **Python 3.12+ and Django 5.x**, server-rendered templates. Use HTMX and a little vanilla JavaScript for the fast sell screen. No heavy front-end framework.
- **SQLite** as the database, so the app works fully **offline** on the laptop at `http://localhost`. Keep the code database-agnostic (Django ORM only, no raw SQLite features) so it can be hosted online with PostgreSQL later. Online versus offline will be chosen later, so do not build sync now.
- **Money:** use `Decimal` for all money and quantities, never floats. Money to 2 decimals. Quantities to 3 decimals.
- **Libraries:** `openpyxl` for Excel import and export, `python-escpos` for receipt printing, and `WeasyPrint` or `ReportLab` for PDFs (pick the one that installs cleanly on Windows, ReportLab preferred).
- **Barcode scanner:** treat it as a keyboard. The scan field keeps focus, and Enter submits. No drivers or special APIs.
- **Tests:** pytest with pytest-django. Every model rule and money calculation has tests.
- **Windows start:** a `start_pos.bat` (or small launcher) that runs the server and opens the browser, so the owner never types commands.

## 3. Users and permissions

Use Django's built-in auth with groups.

| Role | Can do |
| --- | --- |
| Owner/Admin | Everything, including settings, users, prices, reports, profit, voids and refunds |
| Cashier | Sell, hold and resume sales, print receipts, record deni, do their own cash-up |
| Stock clerk (optional) | Receive purchases, do recounts and stock takes, view low stock |

- Cashiers **cannot** change prices, delete sales, or see profit.
- Voiding a cart line after it is added, voiding a completed sale, or a refund needs the **owner's PIN**. Every void and refund is written to an audit log (who, when, what, why).

## 4. Settings (one page)

A single settings page for the owner:

- Business name, logo upload, address, phone, KRA PIN (optional), receipt footer text.
- Receipt printer: connection (USB, network IP, or Windows printer name) and **paper width, 58 mm or 80 mm, default 80 mm**. Include a "Print test receipt" button.
- Low-stock default threshold.
- Backup folder path (USB stick or cloud-synced folder).

The business name and logo appear on receipts, invoices and quotations automatically.

## 5. Products and stock units

Every product has a **Sold by** unit:

| Sold by | Price is per | Stock kept in | Examples |
| --- | --- | --- | --- |
| Piece | item | whole numbers | soap, soda, bread |
| Weight | kg | kg, 3 decimals | rice, beans, sugar |
| Volume | litre | litres, 3 decimals | cooking oil, paraffin |

Product fields: name, barcode (optional, unique when set), category, sold by unit, selling price, cost price (per unit), current stock, low-stock threshold, active flag, quick-sale category (optional), and **bulk price tiers** (see 6.4).

- Stock never changes directly. Every change is a **stock movement** row (sale, purchase, recount adjustment, loss or wastage, refund) with quantity, unit cost, user, time and reason. Current stock equals the sum of movements, cached on the product.
- Cost of goods uses the cost price at the time of the movement, so profit stays correct when cost prices change. Weighted average cost is fine.

### Excel import

- Downloadable `.xlsx` template with columns: Name, Barcode, Category, Sold by (Piece/Weight/Volume), Selling price, Cost price, Opening stock, Low-stock threshold, Quick-sale category, Preset buttons (e.g. `1/4 kg; 1/2 kg; 1 kg; KSh 50`).
- Upload shows a **preview** with row-by-row errors (bad unit, duplicate barcode, missing price) before anything is saved. The owner confirms, then products are created or updated (matched by barcode, then by name).
- Product list can also be exported to Excel.

## 6. Sell screen (most important screen, must be fast)

Layout: scan box and cart on the left, quick-sale panel on the right, totals and payment at the bottom. Usable with keyboard only.

### 6.1 Barcoded items
- Scan adds one piece. Scanning the same item again increases its quantity.
- Quantity can be typed (e.g. `12 *` then scan, or edit the line) for bulk buyers.
- Unknown barcode shows a clear message and, for the owner, a shortcut to add the product.

### 6.2 Loose items by kg or litre
- Enter by **quantity** (0.5 kg) **or by amount** (KSh 50). The POS calculates the other: quantity = amount / price per unit, rounded to 3 decimals; line total rounded to the nearest shilling.
- Receipt line shows quantity, unit and price, e.g. `Pishori 0.250 kg x 200 = 50`.

### 6.3 Quick-sale panel
- Shows the owner's **quick-sale categories** (Rice, Beans, Cooking oil...) as tabs or a dropdown. Categories map to keys **F1 to F8**.
- Opening a category shows its products, each with its **preset buttons**. A preset is either a quantity (`1/4 kg`, `1/2 kg`, `1 kg`, `1/2 L`) or an amount (`KSh 20`, `KSh 50`). One tap adds that line to the cart.
- Every product also has a **Custom** button for odd quantities or amounts.
- Presets are set in product add/edit (and via Excel). The owner can reorder categories and hide presets.

Example setup:

| Category | Product | Presets |
| --- | --- | --- |
| Rice | Pishori | 1/4 kg, 1/2 kg, 1 kg, 2 kg |
| Rice | Basmati | 1/4 kg, 1/2 kg, 1 kg |
| Rice | Kamande | 1/2 kg, 1 kg |
| Beans | Rosecoco | 1/4 kg, 1/2 kg, 1 kg |
| Cooking oil | Loose oil | KSh 20, KSh 50, KSh 100, 1/2 L, 1 L |

### 6.4 Bulk price tiers
- A product can have tiers: a lower unit price once the line quantity reaches a threshold (e.g. sugar 180/kg, but 170/kg from 10 kg).
- The tier price applies automatically and shows on the cart line and receipt.

### 6.5 Hold and resume
- **Hold** parks the current cart with an optional label (e.g. "Mama Wanjiku"), and a new empty cart opens.
- A held-sales list lets the cashier resume any held cart. Held carts do not reduce stock until completed.

### 6.6 Payment
- When completing a sale, the cashier records how it was paid: **Cash**, **M-Pesa**, or a **split by amount** (e.g. KSh 1,000 cash + KSh 2,500 M-Pesa). No M-Pesa transaction code and no Daraja API in v1.
- Cash payments take the amount tendered and show change due.
- Split payments must add up to the sale total before the sale can complete.
- **Deni (credit):** a sale, or part of one, can be put on a customer's credit account. Customers exist only for credit tracking: name, phone, balance, optional credit limit, and a list of credit sales and repayments. Repayments are recorded as cash or M-Pesa.

### 6.7 Receipt
- Printed via ESC/POS at the configured width (58 or 80 mm), with logo, business name, receipt number, date/time, cashier, lines, tier prices, totals, payment breakdown, change, and footer.
- Reprint any past receipt. If printing fails, the sale still saves and the user sees the error.

### 6.8 Voids and refunds
- Need the owner's PIN, record a reason, return stock through stock movements, and appear in the audit log.

### 6.9 End-of-shift cash-up
- The cashier enters cash counted in the drawer and the M-Pesa total received.
- The system shows expected cash and expected M-Pesa from recorded sales (minus refunds, plus deni repayments), and the difference for each.
- Cash-ups are saved and viewable by the owner.

## 7. Stock control

- **Purchases (receiving stock):** pick a supplier, add items with quantity and cost. Loose goods can be received as packs: "1 sack of 50 kg at KSh 9,000" becomes +50 kg at KSh 180/kg.
- **Recounts:** count one or a few products quickly and adjust stock.
- **Stock takes:** a full count session listing every product. It shows expected against counted quantity and the variance in quantity and KSh. On approval, adjustments are posted as stock movements with reason "stock take".
- **Loss and wastage:** record spillage, expiry or damage with a reason.
- **Loose-goods loss report:** per weighed or measured product, expected against counted kg/L across stock takes, so heavy scooping or spillage loss is visible.
- **Low-stock alerts:** a badge and list of products at or below their threshold, shown on the dashboard and sell screen header.

## 8. Suppliers, invoices and quotations

- **Supplier list:** add, edit and deactivate suppliers (name, contact person, phone, email, address, KRA PIN optional, notes). Each supplier shows its purchase history.
- **Invoices and quotations** can be prepared for **suppliers or customers** (choose the party type, then the party, or type a one-off name). Both support a **bulk option**: large-quantity line items with bulk tier prices applied.
- Line items come from products or free text, with quantity, unit, price and line total, then subtotal, optional discount, and total.
- Documents are numbered (INV-0001, QUO-0001), have a date and, for quotations, a validity date.
- Output a clean **PDF with the business name and logo** from settings, to print, save or share. A quotation can be converted into an invoice.
- Invoices track status: draft, sent, paid, partly paid.

## 9. Money and reports

- **Expenses:** record date, category (rent, electricity, transport, wages, other), amount, payment method, note.
- **Daily profit view:** for a chosen day or date range: sales, minus cost of goods sold, equals gross profit; minus expenses equals net profit. Also show loss and wastage value.
- **Three reports**, each exportable to Excel:
  1. **Sales report:** totals by day and period, split by **cash, M-Pesa and deni**, with number of sales.
  2. **Best and slow sellers:** by quantity and by revenue for a period.
  3. **Stock value:** current stock at cost and at selling price, by category.
- Profit and cost figures are visible to the owner only.

## 10. Reliability

- **Daily backup:** each evening (and from a button), copy the SQLite database to the configured backup folder with a dated filename, keeping the last 30.
- Every sale saves in one database transaction. Stock, payments and receipt number are consistent even if the printer fails.
- Pages load fast with a few thousand products and many sales per day. Index barcode and product name.

## 11. Build order

Each stage ends with passing tests, a README update, and a pull request the owner can try.

1. **Foundation:** Django project, all models above (products with sold-by unit, categories, quick-sale categories and presets, bulk price tiers, stock movements, suppliers, customers for deni, sales, payments, users and roles, settings, audit log), Django admin for everything, settings page, login, Excel import with preview and template download, and seed data with the example rice, beans and oil setup.
2. **Sell screen:** scanning, quick-sale panel with F-keys, kg/litre and amount entry, bulk tiers, hold and resume, cash/M-Pesa/split payment, deni, receipt printing and reprint, voids and refunds with PIN, end-of-shift cash-up.
3. **Stock and suppliers:** purchases with pack conversion, recounts, stock takes with variance, loss and wastage, loose-goods loss report, low-stock alerts, supplier list, invoices and quotations as PDFs with the logo.
4. **Money, reports and handover:** expenses, daily profit view, the three reports with Excel export, daily backup, `start_pos.bat` Windows launcher, and a short owner's guide in the README.

## 12. Out of scope for v1

Raw materials, multiple branches, stock transfers, full accounting (journals, chart of accounts), M-Pesa transaction codes and Daraja API, online sync, integrations, per-user billing. Weighing-scale integration is a later add-on: keep the quantity entry separate enough that a scale could feed it later.

## 13. Assumptions to confirm

- Loose quantities show to 3 decimals on receipts (0.250 kg).
- Line totals for loose goods round to the nearest shilling.
- Receipt printer defaults to 80 mm until the owner sets the model and width.
