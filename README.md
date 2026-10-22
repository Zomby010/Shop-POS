# Shop POS

A point of sale for a single minimart. It runs on the shop laptop with no internet needed, sells barcoded goods and loose goods by the kg or litre, prints receipts, and tracks stock, suppliers, deni and profit.

Built with Python and Django on SQLite. The full specification is in [docs/build-prompt.md](docs/build-prompt.md).

## Build stages

| Stage | What it adds | Status |
| --- | --- | --- |
| 1. Foundation | Data model, roles and logins, settings page, products with kg/litre units, bulk price tiers, quick-sale buttons, Excel import and export, admin, demo data | Done |
| 2. Sell screen | Scanning, quick-sale panel, payments, receipts, holds, voids, cash-up, deni customers | Done |
| 3. Stock and suppliers | Purchases, recounts, stock takes, loss tracking, suppliers, invoices and quotations | Done |
| 4. Money and reports | Expenses, profit, reports, backups, Windows launcher | Next |

## Run it for development

```bash
python -m venv .venv
.venv/bin/pip install -r requirements-dev.txt     # Windows: .venv\Scripts\pip
python manage.py migrate
python manage.py seed_demo --users                # example products and logins
python manage.py runserver
```

Open http://localhost:8000 and log in. `seed_demo --users` creates:

| Username | Password | Role |
| --- | --- | --- |
| owner | owner123 | Owner (approval PIN 1234) |
| cashier | cashier123 | Cashier |
| stock | stock123 | Stock clerk |

Change these passwords in Settings → Users before real use. For a clean shop without demo data, run `python manage.py createsuperuser` instead.

Shop data (database, logo, secret key) lives in the `data/` folder, which is not part of the code. Set `SHOPPOS_DATA_DIR` to keep it elsewhere.

Run the tests with `pytest`.

## How things work

### Products and units

Every product is sold by **Piece**, **Weight** (priced per kg) or **Volume** (priced per litre). Loose stock is kept to 3 decimals, so 0.250 kg of rice comes off stock exactly.

- **Bulk price tiers:** a product can get a lower unit price from a quantity upwards, for example sugar 180/kg but 170/kg from 10 kg.
- **Quick-sale buttons:** put a product in a quick-sale category (Rice, Beans, Cooking oil) and give it buttons such as `1/4 kg`, `500 g`, `1/2 L` or `KSh 50`. These appear on the sell screen. Categories are managed in Settings → Quick-sale categories.
- **Stock never changes directly.** Every change is a stock movement (opening, purchase, sale, refund, recount, stock take, loss) that records the cost at that moment, so profit stays right when cost prices change. Purchases update the weighted average cost.

### Excel import

Products → Import from Excel. Download the template, fill one row per product, upload it, and check the preview. Rows with problems are listed and skipped; nothing is saved until you confirm. Existing products are matched by barcode, then by name. Opening stock is only used for new products.

### Roles

| Role | Can do |
| --- | --- |
| Owner | Everything: settings, users, prices, reports, profit; their PIN approves voids and refunds |
| Cashier | Sell, hold and resume sales, print receipts, record deni, do their own cash-up |
| Stock clerk | Receive purchases, recount, stock takes, view low stock |

Every void and refund is written to the audit log (Settings → Audit log).

### Selling

The sell screen (Sell in the top bar) is built for speed and works with the keyboard alone.

| Key | Does |
| --- | --- |
| Scan or type, then Enter | Adds the item. `12*barcode` adds 12 pieces. Typing part of a name finds products without barcodes. |
| F1 to F8 | Opens a quick-sale category (Rice, Beans, Cooking oil...) |
| F9 | Pay |
| F10 | Hold the sale (park it under a name and serve the next customer) |
| Esc | Back to the scan box |

- **Loose goods:** tap a preset button (1/4 kg, KSh 50) or Custom to type any quantity or amount. Buying by amount works out the quantity: KSh 50 of oil at 300/L is 0.167 L.
- **Bulk prices** apply automatically when a line reaches a tier and show as "bulk" on the cart and receipt.
- **Payment:** all cash, all M-Pesa, a split by amount, or deni (credit) for a customer. Cash shows the change. Split amounts must cover the total.
- **Removing or reducing a line** needs the owner's PIN unless the owner is logged in. Refunds and voids (Sell → Today's sales → Refund or void) also need the PIN and a reason, and are written to the audit log.
- **Receipts** print to the thermal printer set in Settings (USB, network or Windows printer name; 58 or 80 mm). If the printer fails, the sale is still saved and the receipt can be printed again or from the browser.
- **Cash-up** (Sell → Cash-up) compares the drawer and M-Pesa with what was recorded since the cashier's last cash-up: cash sales, minus cash refunds, plus deni repaid in cash, minus expenses paid from the drawer.

### Stock

Stock in the top bar (owners and stock clerks).

- **Receive stock:** pick the supplier and add items in packs. "2 sacks × 50 kg at KSh 9,000" adds 100 kg at KSh 180/kg and updates the average cost.
- **Recount:** search a few products and type what you counted.
- **Stock take:** start one for the whole shop or one category. The system notes what it expects; you type counts as you go and save often. Selling can continue. When the owner approves, only the differences found are posted, so sales made during counting are kept.
- **Loss and wastage:** record spillage, scooping loss, expiry or damage with a reason.
- **Loose-goods loss report** (owner): for rice, beans, oil and other weighed goods, expected against counted kg/L over approved stock takes, plus recorded losses, as a share of what was sold.
- **Low stock:** products at or below their alert level show on the dashboard, the Stock page and as a badge on Products.

### Suppliers, invoices and quotations

- **Suppliers** (Customers & suppliers → Suppliers): add, edit and deactivate suppliers, and see each one's purchase history.
- **Invoices and quotations** (owner): prepare them for a customer, a supplier or a one-off name. Tick **Bulk order** and product lines with a blank price take the bulk tier price for their quantity. Lines can also be free text (delivery, services).
- Each document is numbered (INV-0001, QUO-0001) and opens as a PDF with the business name and logo from Settings, ready to print, save or send. A quotation converts into an invoice in one click, and invoices track payments (draft, sent, partly paid, paid).

## Project layout

```
apps/core        settings, roles, users, audit log, dashboard, money helpers
apps/catalog     products, units, price tiers, quick-sale presets, stock movements, Excel
apps/sales       carts, sales, payments, receipts, refunds, cash-ups
apps/inventory   purchases and stock takes
apps/partners    suppliers and customers (deni)
apps/documents   invoices and quotations
apps/finance     expenses, reports, backups
```
