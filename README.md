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

   If another program already uses port 8000, create a text file called `port.txt` next to `start_pos.bat` containing just a free port number, such as `8001`. The POS then opens at http://localhost:8001.

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

## Running online (Vercel)

The laptop stays the till: it prints receipts and works without internet. An online copy on Vercel is for checking sales and reports from anywhere.

1. Merge the code into `main`, then on vercel.com: Add New → Project → **Shop-POS** → Deploy (the first deploy may fail; that's fine).
2. Storage → Create Database → **Neon** → Free, region Frankfurt → connect it to Shop-POS for all environments, with no prefix. This adds `DATABASE_URL`.
3. Settings → Environment Variables: `SHOPPOS_SECRET_KEY` = a long random string (50+ characters, keep it private). Optional: `SHOPPOS_ALLOWED_HOSTS` and `SHOPPOS_CSRF_ORIGINS` if you add your own domain (defaults allow any `*.vercel.app` address).
4. Deployments → Redeploy.
5. On the laptop, in this folder, with the `DATABASE_URL` value from Vercel: `set DATABASE_URL=...`, then `python manage.py migrate` and `python manage.py setup_owner`. Run `migrate` the same way whenever a change includes database migrations.

Online, the logo is stored in the database, the shop printer is off (print receipts from the browser) and folder backups are off (Neon keeps restore points). Every merge into `main` redeploys automatically.

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

Run the tests with `pytest`. `python serve.py` runs the same production server that `start_pos.bat` uses (waitress, on port 8000, or the port in the `SHOPPOS_PORT` environment variable).

## How things work

### Products and units

Every product is sold by **Piece**, **Weight** (priced per kg) or **Volume** (priced per litre). Loose stock is kept to 3 decimals, so 0.250 kg of rice comes off stock exactly.

- **Bulk price tiers:** a product can get a lower unit price from a quantity upwards, for example sugar 180/kg but 170/kg from 10 kg.
- **Quick-sale buttons:** put a product in a quick-sale category (Rice, Beans, Cooking oil) and give it buttons such as `1/4 kg`, `500 g`, `1/2 L` or `KSh 50`. These appear on the sell screen. Categories are managed in Settings → Quick-sale categories.
- **Stock never changes directly.** Every change is a stock movement (opening, purchase, sale, refund, recount, stock take, loss) that records the cost at that moment, so profit stays right when cost prices change. Purchases update the weighted average cost.

### Adding as you go

Dropdowns for a category, quick-sale category, supplier, customer, product or expense category end with **+ New…**. Pick it to add one in a small pop-up without leaving the form; it is then selected for you. Owners can add all of these; stock clerks can add suppliers and cashiers can add customers. Loss reasons can be picked from the list or typed.

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

- **All items list:** the first tab on the right lists every product, with a search box and a category filter. Tap a product to add one piece; loose goods and the **Qty** button ask for a quantity or amount. Useful before a scanner is connected and for items without barcodes.
- **Loose goods:** tap a preset button (1/4 kg, KSh 50) or Custom to type any quantity or amount. Buying by amount works out the quantity: KSh 50 of oil at 300/L is 0.167 L.
- **Bulk prices** apply automatically when a line reaches a tier and show as "bulk" on the cart and receipt.
- **Payment:** all cash, all M-Pesa, a split by amount, or deni (credit) for a customer. Cash shows the change. Split amounts must cover the total.
- **Removing or reducing a line** needs the owner's PIN unless the owner is logged in. Refunds and voids (Sell → Today's sales → Refund or void) also need the PIN and a reason, and are written to the audit log.
- **Receipts** print to the thermal printer set in Settings (USB, network or Windows printer name; 58 or 80 mm). If the printer fails, the sale is still saved and the receipt can be printed again or from the browser.
- **Cash-up** (Sell → Cash-up) compares the drawer and M-Pesa with what was recorded since the cashier's last cash-up: cash sales, minus cash refunds, plus deni repaid in cash, minus expenses paid from the drawer.

### Stock

Stock in the top bar (owners and stock clerks).

- **Receive stock:** pick the supplier and add items in packs. "2 sacks × 50 kg at KSh 9,000" adds 100 kg at KSh 180/kg and updates the average cost. Type a new selling price on a line if the shelf price is changing. Leave **Paid now** blank if you paid in full; anything less is recorded as owed to the supplier.
- **Purchases:** each one shows Paid, Partly paid or Unpaid. Open it to record a later payment (cash, M-Pesa or bank). The owner can cancel a purchase entered by mistake: its stock comes off again (refused if some was already sold).
- **Convert:** turn some of one product into another, such as a 50 kg sack into 1 kg packets or a crate into single bottles. Stock comes off the first and goes onto the second with its cost, and nothing is recorded as bought or sold.
- **Recount:** search a few products and type what you counted. Every difference needs a reason: shortage reasons (normal loss, damaged, theft…) for less, and surplus reasons (delivery not recorded, returned…) for more, so extra stock is never filed as a loss. Pick the type (spot, opening, closing), check the summary, then confirm. Each recount gets a number (RC0001).
- **Stock take:** start one for the whole shop or one category. The system notes what it expects; you type counts as you go and save often. Selling can continue. When the owner approves, only the differences found are posted, so sales made during counting are kept.
- **Loss and wastage:** record spillage, scooping loss, expiry or damage with a reason.
- **Product history:** every movement of a product with the quantity before and after, plus each cost and selling price change and why. Filter by type and date and download it to Excel.
- **Loose-goods loss report** (owner): for rice, beans, oil and other weighed goods, expected against counted kg/L over approved stock takes, plus recorded losses, as a share of what was sold.
- **Low stock:** a reorder list of products at or below their alert level, with the reorder quantity set on each product, the estimated cost and the last supplier, downloadable to Excel. Out-of-stock and low badges also show on Products and the sell screen.

### Suppliers, invoices and quotations

- **Suppliers** (Customers & suppliers → Suppliers): add, edit and deactivate suppliers, and see each one's purchase history and what the shop still owes them.
- **Invoices and quotations** (owner): prepare them for a customer, a supplier or a one-off name. Tick **Bulk order** and product lines with a blank price take the bulk tier price for their quantity. Lines can also be free text (delivery, services).
- Each document is numbered (INV-0001, QUO-0001) and opens as a PDF with the business name and logo from Settings, ready to print, save or send. A quotation converts into an invoice in one click, and invoices track payments (draft, sent, partly paid, paid).

### Sales

**Sales** in the top bar. Every completed or voided sale with its time, number of items, total, how it was paid (cash, M-Pesa with its code, deni), refunds, customer, cashier and status (Paid, On deni, Part refunded, Voided). Pick Today, Yesterday, this or last week, month or year, or any dates. Filter by payment (cash only, M-Pesa only, on deni, split) and status, and the owner can filter by cashier. Search by receipt number (any date), customer or M-Pesa code. Totals for cash, M-Pesa and deni sit above the list, and **Download Excel** saves the filtered list. Open a sale to refund items or void it. Cashiers see only their own sales.

At checkout, an optional **M-Pesa code** box appears when part of the sale is paid by M-Pesa. The code prints on the receipt so sales can be matched to the M-Pesa statement.

### Reports

Owner only, under **Reports**. Every report shares the same period buttons (Today, Yesterday, This/Last week, This/Last month, This/Last year) or dates, and a **Download Excel** button.

- **Summary:** net sales, number of sales, average sale and gross profit; how customers paid (cash, M-Pesa, deni); money collected (from sales after refunds plus deni repaid, split into cash and M-Pesa); deni given, repaid and owed now; cost of goods, expenses, stock loss and net profit; bought from, paid to and owed to suppliers.
- **Profit and loss:** net sales (after refunds), cost of goods sold at the cost when each item was sold, gross profit and margin, expenses, stock loss (wastage plus count differences) and net profit, by day and in total.
- **Sales by day:** sales per day split into cash, M-Pesa and deni, with refunds and voids.
- **Sold items:** each item sold with quantity, cost, revenue, margin and margin %, sortable and by category. The margins add up to the Summary's gross profit.
- **Fast and slow:** every product as fast, slow or not selling, with total sold, average per day over every day of the period, revenue, margin and how many days current stock will last.
- **Stock movement:** per item, opening, new stock, purchased, converted in and out, sold, returned, losses, count changes and closing, with unit cost and value. Opening covers everything before the start date, so each row always adds up.
- **Purchased items:** what was bought from suppliers, with quantity, cost, average unit cost and suppliers. Cancelled purchases, conversions and opening stock are left out.
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
