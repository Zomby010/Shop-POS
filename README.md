# Shop POS

A point of sale for a single minimart. It runs on the shop laptop with no internet needed, sells barcoded goods and loose goods by the kg or litre, prints receipts, and tracks stock, suppliers, deni and profit.

Built with Python and Django on SQLite. The full specification is in [docs/build-prompt.md](docs/build-prompt.md).

## Build stages

| Stage | What it adds | Status |
| --- | --- | --- |
| 1. Foundation | Data model, roles and logins, settings page, products with kg/litre units, bulk price tiers, quick-sale buttons, Excel import and export, admin, demo data | Done |
| 2. Sell screen | Scanning, quick-sale panel, payments, receipts, holds, voids, cash-up, deni customers | Done |
| 3. Stock and suppliers | Purchases, recounts, stock takes, loss tracking, suppliers, invoices and quotations | Done |
| 4. Money and reports | Expenses, profit, reports, backups, Windows launcher | Done |

## Owner's guide: setting up the shop laptop

1. Install **Python 3.12 or newer** from [python.org](https://www.python.org/downloads/). On the first installer screen tick **Add python.exe to PATH**.
2. Copy the Shop POS folder to the laptop (for example `C:\ShopPOS`).
3. Double-click **`start_pos.bat`**. The first time, it needs the internet for a few minutes to install its libraries, then asks you to create the owner's username, password and PIN.
4. The browser opens at http://localhost:8000. Keep the black window open while the shop is open; closing it stops the POS. Put a shortcut to `start_pos.bat` on the desktop.

After that the POS works fully offline.

**First things to do as the owner**

1. **Settings:** business name, logo, phone, KRA PIN and receipt footer. Choose the receipt printer and its paper width (58 or 80 mm), then press **Save and print test receipt**. Set a backup folder on a USB stick or a OneDrive/Google Drive folder.
2. **Settings → Users and PINs:** add a login for each cashier.
3. **Settings → Quick-sale categories:** add Rice, Beans, Cooking oil and so on.
4. **Products → Import from Excel:** download the template, fill in your products, upload, check the preview and import. Loose goods use Sold by = Weight or Volume and list their buttons, e.g. `1/4 kg; 1/2 kg; 1 kg` or `KSh 50; KSh 100; 1/2 L`.
5. Start selling from **Sell**.

**Every day**

- Cashiers sell from **Sell** and do a **Cash-up** at the end of each shift.
- Receive deliveries in **Stock → Receive stock**; record spillage in **Stock → Loss and wastage**.
- Check **Money & reports** for today's profit, and **Products** for the low-stock badge.
- From 6 pm the POS backs itself up automatically. You can also press **Back up now** under Money & reports → Backup.

**Receipt printer connection**

| Printer type | Settings → Connection | Address |
| --- | --- | --- |
| USB thermal printer installed in Windows | Windows printer name | The printer's name as shown in Windows Settings → Printers |
| Network/Wi-Fi printer | Network | Its IP address, e.g. `192.168.1.50` |
| USB printer without a Windows driver | USB | Vendor and product id, e.g. `0x0416:0x5011` |

If a receipt fails to print, the sale is still saved. Use **Print receipt** to try again, or **Print from browser**.

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

Run the tests with `pytest`. `python serve.py` runs the same production server that `start_pos.bat` uses (waitress, on port 8000).

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

### Money and reports

Owner only, under **Money & reports**. Every report has a date range and an **Export to Excel** button.

- **Profit:** net sales (after refunds), cost of goods sold at the cost when each item was sold, gross profit and margin, expenses, stock loss (wastage plus count differences) and net profit, by day and in total.
- **Sales report:** sales per day split into cash, M-Pesa and deni, with refunds and voids.
- **Best and slow sellers:** by revenue for the period, with quantity and gross profit; the Excel file lists every product.
- **Stock value:** stock at cost and at selling price by category.
- **Expenses:** rent, electricity, transport, wages and so on. Cash expenses from the drawer come off the expected cash at cash-up.
- **Backup:** run a backup now, download past ones, and restore instructions. Backups are zip files with the database and logo; the last 30 (configurable) are kept.

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
