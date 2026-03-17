# InvoiceFlow

AI-powered invoicing system for freelancers and small businesses in Pakistan.
Built with Python, Groq AI (Llama 3.3), Flask, and ReportLab.

---

## What it does

- Generates professional PDF invoices automatically
- Writes AI-enhanced service descriptions using Llama 3.3
- Emails the invoice to your client via Gmail with a professional cover email
- Saves every client to a database with autocomplete for repeat invoices
- Tracks paid, unpaid, and overdue invoices in a dashboard
- Supports PKR and USD with optional GST 17% toggle
- Adds EasyPaisa and JazzCash payment info directly on the invoice
- Password-protected dashboard so only you can access it
- Fully mobile responsive

---

## Tech Stack

- Python + Flask
- Groq API — Llama 3.3 70b (free tier)
- ReportLab — PDF generation
- SQLite — client and invoice database
- Gmail SMTP — email delivery
- Vanilla JS — frontend dashboard

---

## Setup

### 1. Clone the repo

```bash
git clone https://github.com/aliraza0-ops/invoiceflow.git
cd invoiceflow
```

### 2. Create virtual environment

```bash
python -m venv venv
source venv/bin/activate
# Windows: venv\Scripts\activate
```

### 3. Install dependencies

```bash
pip install flask flask-cors reportlab groq python-dotenv
```

### 4. Configure your environment

```bash
cp .env.example .env
```

Open `.env` and fill in your real values. See below for how to get each key.

### 5. Run

```bash
python invoice_app_v3.py
```

Open `http://localhost:5001` and log in with your dashboard password.

---

## Getting Your Keys

**Groq API Key (free):**
1. Go to https://console.groq.com
2. Sign up and go to API Keys
3. Create a new key and paste it as `GROQ_API_KEY`

**Gmail App Password:**
1. Enable 2-Step Verification on your Google account
2. Go to https://myaccount.google.com/apppasswords
3. Create a password named InvoiceFlow
4. Paste the 16-character password as `GMAIL_APP_PASSWORD`

**Dashboard Password:**
Set `DASHBOARD_PASSWORD` to any password you want in your `.env` file.

---

## Project Structure

```
invoiceflow/
├── invoice_app_v3.py     # Flask backend — all API routes and PDF logic
├── inv_static/
│   ├── index.html        # Dashboard
│   ├── invoice.html      # New invoice form with AI enhance button
│   └── login.html        # Login page
├── invoices/             # Generated PDFs (auto-created, not tracked by git)
├── .env.example          # Template — copy to .env and fill in your keys
├── .gitignore
└── README.md
```

---

## Features in Detail

**AI Enhance Button**
On the invoice form, each line item has a small AI button next to the description field. Type your rough description, click the button, and Llama 3.3 rewrites it into professional invoice language instantly.

**Dashboard**
Tracks all invoices with status badges — Sent, Paid, Partial, Overdue. One click to mark an invoice as paid. Revenue chart shows monthly PKR earnings. Client list with full invoice history per client.

**PDF Invoice**
Branded PDF with your business name, client details, itemized services, subtotal, GST if enabled, total due, payment due date, EasyPaisa and JazzCash numbers, and a footer with your contact info.

**Email**
Groq writes a professional cover email for each invoice. The PDF is attached automatically. A BCC copy is sent to your own inbox so you always have a record.

---

## License

MIT — free to use, modify, and distribute.

---

Built by [@aliraza0-ops](https://github.com/aliraza0-ops) --Linkedin [ www.linkedin.com/in/ali-raza-9816213a4 ]
