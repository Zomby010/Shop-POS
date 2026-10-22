# Shop POS

A point of sale for a single minimart. It runs on the shop laptop with no internet needed, sells barcoded goods and loose goods by the kg or litre, prints receipts, and tracks stock, suppliers, deni and profit.

Built with Python and Django on SQLite. The full specification is in [docs/build-prompt.md](docs/build-prompt.md).

## Build stages

| Stage | What it adds | Status |
| --- | --- | --- |
| 1. Foundation | Data model, roles and logins, settings page, products with kg/litre units, bulk price tiers, quick-sale buttons, Excel import and export, admin, demo data | Done |
| 2. Sell screen | Scanning, quick-sale panel, payments, receipts, holds, voids, cash-up | Next |
| 3. Stock and suppliers | Purchases, recounts, stock takes, loss tracking, suppliers, invoices and quotations | |
| 4. Money and reports | Expenses, profit, reports, backups, Windows launcher | |

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
