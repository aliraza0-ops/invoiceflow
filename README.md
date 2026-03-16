# InvoiceFlow ⚡
AI-powered invoicing system for freelancers and small businesses.
Built with Python + Google Gemini + Flask.

## Features
- AI-generated invoice descriptions (Gemini)
- Auto-email PDF invoices via Gmail
- PKR + USD dual currency
- GST 17% toggle
- EasyPaisa / JazzCash on invoice
- Client database with autocomplete
- Mark Paid / Partial / Overdue
- Revenue dashboard + charts
- Mobile responsive UI

## Quick Setup

### 1. Clone
```bash
https://github.com/aliraza0-ops/invoiceflow.git
cd invoiceflow
```

### 2. Install
```bash
python -m venv venv
source venv/bin/activate
pip install flask flask-cors reportlab google-generativeai python-dotenv
```

### 3. Configure
```bash
cp .env.example .env
# Fill in your real keys in .env
```

### 4. Run
```bash
python invoice_app_v2.py
# Open http://localhost:5001
```

## Get Your Keys
**Gemini:** https://aistudio.google.com/app/apikey (free tier)
**Gmail App Password:** myaccount.google.com → Security → App Passwords

## License
MIT
# invoiceflow
# invoiceflow
