import os, io, json, smtplib, datetime, sqlite3, logging
from pathlib import Path
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders
from flask import Flask, request, jsonify, send_from_directory, g
from flask_cors import CORS
from dotenv import load_dotenv
import google.generativeai as genai
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.units import mm
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, HRFlowable
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_RIGHT, TA_LEFT, TA_CENTER

# ─────────────────────────────────────────────
# SETUP
# ─────────────────────────────────────────────
load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.FileHandler('invoiceflow.log'),
        logging.StreamHandler()
    ]
)
log = logging.getLogger(__name__)

GEMINI_API_KEY   = os.getenv("GEMINI_API_KEY")
GMAIL_USER       = os.getenv("GMAIL_USER")
GMAIL_PASSWORD   = os.getenv("GMAIL_APP_PASSWORD")
BUSINESS_NAME    = os.getenv("BUSINESS_NAME",    "My Business")
BUSINESS_EMAIL   = os.getenv("BUSINESS_EMAIL",   GMAIL_USER or "")
BUSINESS_PHONE   = os.getenv("BUSINESS_PHONE",   "")
BUSINESS_ADDRESS = os.getenv("BUSINESS_ADDRESS", "")
BUSINESS_NTN     = os.getenv("BUSINESS_NTN",     "")
WEBHOOK_SECRET   = os.getenv("WEBHOOK_SECRET",   "invoiceflow2026")
EASYPAISA_NUM    = os.getenv("EASYPAISA_NUM",    "")
JAZZCASH_NUM     = os.getenv("JAZZCASH_NUM",     "")

INVOICES_DIR = Path("./invoices")
INVOICES_DIR.mkdir(exist_ok=True)
DB_PATH = Path("./invoiceflow.db")

genai.configure(api_key=GEMINI_API_KEY)
gemini = genai.GenerativeModel("gemini-2.0-flash")

app = Flask(__name__, static_folder="inv_static")
CORS(app)

# ─────────────────────────────────────────────
# DATABASE
# ─────────────────────────────────────────────
def get_db():
    if 'db' not in g:
        g.db = sqlite3.connect(DB_PATH, detect_types=sqlite3.PARSE_DECLTYPES)
        g.db.row_factory = sqlite3.Row
    return g.db

@app.teardown_appcontext
def close_db(e=None):
    db = g.pop('db', None)
    if db: db.close()

def init_db():
    with sqlite3.connect(DB_PATH) as db:
        db.execute("""
        CREATE TABLE IF NOT EXISTS clients (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            name        TEXT NOT NULL,
            email       TEXT NOT NULL UNIQUE,
            phone       TEXT,
            address     TEXT,
            currency    TEXT DEFAULT 'PKR',
            created_at  TEXT DEFAULT (datetime('now'))
        )""")
        db.execute("""
        CREATE TABLE IF NOT EXISTS invoices (
            id             INTEGER PRIMARY KEY AUTOINCREMENT,
            invoice_number TEXT UNIQUE NOT NULL,
            client_id      INTEGER REFERENCES clients(id),
            client_name    TEXT NOT NULL,
            client_email   TEXT NOT NULL,
            status         TEXT DEFAULT 'SENT',
            currency       TEXT DEFAULT 'PKR',
            subtotal       REAL NOT NULL,
            tax_percent    REAL DEFAULT 0,
            tax_amount     REAL DEFAULT 0,
            total          REAL NOT NULL,
            amount_paid    REAL DEFAULT 0,
            due_date       TEXT,
            invoice_date   TEXT,
            notes          TEXT,
            email_sent     INTEGER DEFAULT 0,
            pdf_path       TEXT,
            created_at     TEXT DEFAULT (datetime('now'))
        )""")
        db.execute("""
        CREATE TABLE IF NOT EXISTS invoice_items (
            id             INTEGER PRIMARY KEY AUTOINCREMENT,
            invoice_id     INTEGER REFERENCES invoices(id),
            description    TEXT NOT NULL,
            qty            REAL DEFAULT 1,
            unit_price     REAL NOT NULL,
            amount         REAL NOT NULL
        )""")
        db.execute("""
        CREATE TABLE IF NOT EXISTS invoice_counter (
            year  INTEGER PRIMARY KEY,
            count INTEGER DEFAULT 0
        )""")
        db.commit()
    log.info("Database initialized")

# ─────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────
def get_next_invoice_number():
    year = datetime.datetime.now().year
    with sqlite3.connect(DB_PATH) as db:
        db.execute("INSERT INTO invoice_counter(year,count) VALUES(?,1) ON CONFLICT(year) DO UPDATE SET count=count+1", (year,))
        db.commit()
        row = db.execute("SELECT count FROM invoice_counter WHERE year=?", (year,)).fetchone()
        return f"INV-{year}-{str(row[0]).zfill(3)}"

def fmt(amount, currency="PKR"):
    if currency == "USD":
        return f"${amount:,.2f}"
    return f"PKR {amount:,.0f}"

def enhance_description(service, amount, currency):
    try:
        r = gemini.generate_content(
            f'Write a professional 1-2 sentence invoice service description for: "{service}" '
            f'(value: {fmt(amount, currency)}). Plain text only, max 120 chars, no price mention.'
        )
        return r.text.strip()
    except:
        return service

def generate_email_body(client_name, inv_num, service, total, due_date, biz_name, currency):
    try:
        r = gemini.generate_content(
            f'Write a short professional invoice email (3-4 sentences, plain text).\n'
            f'Client: {client_name}, Invoice: {inv_num}, Service: {service}, '
            f'Total: {fmt(total, currency)}, Due: {due_date}, From: {biz_name}.\n'
            f'Warm but professional. Include greeting, what it is, amount, due date, closing.'
        )
        return r.text.strip()
    except:
        return (f"Dear {client_name},\n\nPlease find attached invoice {inv_num} for {service}.\n"
                f"Amount due: {fmt(total, currency)} by {due_date}.\n\nBest regards,\n{biz_name}")

# ─────────────────────────────────────────────
# PDF GENERATOR
# ─────────────────────────────────────────────
def generate_pdf(data):
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4,
                            rightMargin=14*mm, leftMargin=14*mm,
                            topMargin=14*mm, bottomMargin=14*mm)

    ACCENT  = colors.HexColor('#1a1a2e')
    ACCENT2 = colors.HexColor('#5b4fff')
    PINK    = colors.HexColor('#ff4f9e')
    LIGHT   = colors.HexColor('#f5f4ff')
    GRAY    = colors.HexColor('#ddddee')
    currency = data.get("currency", "PKR")

    sN = ParagraphStyle('N',  fontName='Helvetica',      fontSize=9,  leading=14, textColor=colors.HexColor('#444'))
    sS = ParagraphStyle('S',  fontName='Helvetica',      fontSize=8,  leading=12, textColor=colors.HexColor('#888'))
    sB = ParagraphStyle('B',  fontName='Helvetica-Bold', fontSize=9,  leading=14, textColor=colors.HexColor('#222'))
    sR = ParagraphStyle('R',  fontName='Helvetica',      fontSize=9,  leading=14, textColor=colors.HexColor('#444'), alignment=TA_RIGHT)
    sL = ParagraphStyle('L',  fontName='Helvetica',      fontSize=7,  leading=11, textColor=colors.HexColor('#999'))
    sC = ParagraphStyle('C',  fontName='Helvetica',      fontSize=8,  leading=12, textColor=colors.HexColor('#666'), alignment=TA_CENTER)

    story = []

    # Header
    hdr = Table([[
        Paragraph(f'<font color="#1a1a2e"><b>{data["business_name"]}</b></font>',
                  ParagraphStyle('BN', fontName='Helvetica-Bold', fontSize=15, textColor=ACCENT)),
        Paragraph('INVOICE', ParagraphStyle('IT', fontName='Helvetica-Bold', fontSize=32,
                                             textColor=ACCENT2, alignment=TA_RIGHT)),
    ]], colWidths=[93*mm, 87*mm])
    hdr.setStyle(TableStyle([('VALIGN',(0,0),(-1,-1),'MIDDLE'),('BOTTOMPADDING',(0,0),(-1,-1),4)]))
    story.append(hdr)
    story.append(HRFlowable(width="100%", thickness=2, color=ACCENT2, spaceAfter=5))

    # Biz info + meta
    biz_lines = [l for l in [data.get("business_email",""), data.get("business_phone",""),
                               data.get("business_address",""), 
                               f'NTN: {data["business_ntn"]}' if data.get("business_ntn") else ""] if l]
    meta = Table([[
        Paragraph("<br/>".join(biz_lines), sS),
        Table([
            [Paragraph('Invoice No.', sL), Paragraph(f'<b>{data["invoice_number"]}</b>', sB)],
            [Paragraph('Date',        sL), Paragraph(data["invoice_date"], sN)],
            [Paragraph('Due Date',    sL), Paragraph(f'<b>{data["due_date"]}</b>', sB)],
            [Paragraph('Currency',    sL), Paragraph(data.get("currency","PKR"), sN)],
        ], colWidths=[25*mm, 60*mm],
           style=TableStyle([('ALIGN',(1,0),(1,-1),'RIGHT'),('BOTTOMPADDING',(0,0),(-1,-1),3)]))
    ]], colWidths=[93*mm, 87*mm])
    meta.setStyle(TableStyle([('VALIGN',(0,0),(-1,-1),'TOP'),('BOTTOMPADDING',(0,0),(-1,-1),3)]))
    story.append(meta)
    story.append(Spacer(1, 8*mm))

    # Bill To
    billhdr = Table([[Paragraph('BILL TO',
        ParagraphStyle('BL', fontName='Helvetica-Bold', fontSize=7, textColor=colors.white))
    ]], colWidths=[180*mm])
    billhdr.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,-1),ACCENT2),
        ('TOPPADDING',(0,0),(-1,-1),5),('BOTTOMPADDING',(0,0),(-1,-1),5),('LEFTPADDING',(0,0),(-1,-1),8)]))
    story.append(billhdr)

    client_row = Table([[
        Paragraph(f'<b>{data["client_name"]}</b>',
                  ParagraphStyle('CN', fontName='Helvetica-Bold', fontSize=11, textColor=ACCENT)),
        Paragraph(data["client_email"], sN),
    ]], colWidths=[93*mm, 87*mm])
    client_row.setStyle(TableStyle([
        ('BACKGROUND',(0,0),(-1,-1),LIGHT),
        ('TOPPADDING',(0,0),(-1,-1),8),('BOTTOMPADDING',(0,0),(-1,-1),8),
        ('LEFTPADDING',(0,0),(-1,-1),8),('VALIGN',(0,0),(-1,-1),'MIDDLE')]))
    story.append(client_row)
    story.append(Spacer(1, 7*mm))

    # Items table
    rows = [['#','Description','Qty','Unit Price','Amount']]
    for i, item in enumerate(data["items"], 1):
        rows.append([
            str(i),
            Paragraph(item["description"], sN),
            str(item.get("qty",1)),
            fmt(item["unit_price"], currency),
            fmt(item["amount"], currency),
        ])
    items_t = Table(rows, colWidths=[10*mm, 88*mm, 15*mm, 37*mm, 30*mm])
    items_t.setStyle(TableStyle([
        ('BACKGROUND',(0,0),(-1,0),ACCENT),('TEXTCOLOR',(0,0),(-1,0),colors.white),
        ('FONTNAME',(0,0),(-1,0),'Helvetica-Bold'),('FONTSIZE',(0,0),(-1,0),8),
        ('ALIGN',(0,0),(-1,0),'CENTER'),('TOPPADDING',(0,0),(-1,0),8),('BOTTOMPADDING',(0,0),(-1,0),8),
        ('FONTNAME',(0,1),(-1,-1),'Helvetica'),('FONTSIZE',(0,1),(-1,-1),9),
        ('ALIGN',(0,1),(0,-1),'CENTER'),('ALIGN',(2,1),(-1,-1),'RIGHT'),
        ('VALIGN',(0,0),(-1,-1),'MIDDLE'),
        ('TOPPADDING',(0,1),(-1,-1),8),('BOTTOMPADDING',(0,1),(-1,-1),8),
        ('LEFTPADDING',(1,0),(1,-1),8),
        ('ROWBACKGROUNDS',(0,1),(-1,-1),[colors.white, LIGHT]),
        ('LINEBELOW',(0,0),(-1,0),0.5,ACCENT2),
        ('LINEBELOW',(0,-1),(-1,-1),0.5,GRAY),
        ('LINEAFTER',(0,0),(-2,-1),0.3,GRAY),
    ]))
    story.append(items_t)
    story.append(Spacer(1,5*mm))

    # Totals
    subtotal = sum(i["amount"] for i in data["items"])
    tax_pct  = data.get("tax_percent", 0)
    tax_amt  = subtotal * tax_pct / 100
    total    = subtotal + tax_amt
    tot_rows = [['', 'Subtotal:', fmt(subtotal, currency)]]
    if tax_pct > 0:
        tot_rows.append(['', f'GST ({tax_pct:.0f}%):', fmt(tax_amt, currency)])
    tot_rows.append(['', 'TOTAL DUE:', fmt(total, currency)])
    tot_t = Table(tot_rows, colWidths=[113*mm, 42*mm, 25*mm])
    ts = TableStyle([
        ('ALIGN',(1,0),(-1,-1),'RIGHT'),
        ('FONTNAME',(0,0),(-1,-2),'Helvetica'),('FONTSIZE',(0,0),(-1,-2),9),
        ('TEXTCOLOR',(1,0),(-1,-2),colors.HexColor('#666')),
        ('TOPPADDING',(0,0),(-1,-1),4),('BOTTOMPADDING',(0,0),(-1,-1),4),
        ('FONTNAME',(1,-1),(-1,-1),'Helvetica-Bold'),('FONTSIZE',(1,-1),(-1,-1),13),
        ('TEXTCOLOR',(1,-1),(-1,-1),ACCENT2),
        ('LINEABOVE',(1,-1),(-1,-1),1.5,ACCENT2),('TOPPADDING',(1,-1),(-1,-1),8),
    ])
    tot_t.setStyle(ts)
    story.append(tot_t)
    story.append(Spacer(1, 8*mm))

    # Payment info
    pay_lines = ['<b>Payment Methods:</b>']
    if data.get("easypaisa"): pay_lines.append(f'EasyPaisa: <b>{data["easypaisa"]}</b>')
    if data.get("jazzcash"):  pay_lines.append(f'JazzCash: <b>{data["jazzcash"]}</b>')
    if currency == "USD":     pay_lines.append('Bank transfer details available on request.')
    pay_text = ' &nbsp;|&nbsp; '.join(pay_lines)

    terms_data = [[
        Paragraph(
            f'<b>Payment Due by {data["due_date"]}</b><br/>'
            f'Reference: <b>{data["invoice_number"]}</b><br/>'
            + pay_text, sS),
        Paragraph(
            f'<b>Thank you for your business!</b><br/>'
            f'{data["business_email"]}' +
            (f'<br/>NTN: {data["business_ntn"]}' if data.get("business_ntn") else ""),
            ParagraphStyle('TY', fontName='Helvetica', fontSize=8, leading=13,
                           textColor=colors.HexColor('#888'), alignment=TA_RIGHT))
    ]]
    terms_t = Table(terms_data, colWidths=[100*mm, 80*mm])
    terms_t.setStyle(TableStyle([
        ('BACKGROUND',(0,0),(-1,-1),LIGHT),
        ('TOPPADDING',(0,0),(-1,-1),10),('BOTTOMPADDING',(0,0),(-1,-1),10),
        ('LEFTPADDING',(0,0),(0,-1),10),('RIGHTPADDING',(1,0),(1,-1),10),
        ('VALIGN',(0,0),(-1,-1),'MIDDLE'),
    ]))
    story.append(terms_t)
    story.append(Spacer(1,6*mm))
    story.append(HRFlowable(width="100%", thickness=0.5, color=GRAY))
    story.append(Spacer(1,3*mm))

    # Notes
    if data.get("notes"):
        story.append(Paragraph(f'<i>Note: {data["notes"]}</i>', sC))
        story.append(Spacer(1,3*mm))

    story.append(Paragraph(
        f'Generated by InvoiceFlow · {data["business_name"]} · {data["business_email"]}', sC))

    doc.build(story)
    return buf.getvalue()

# ─────────────────────────────────────────────
# EMAIL
# ─────────────────────────────────────────────
def send_email(to_email, client_name, inv_num, body, pdf_bytes, biz_name):
    try:
        msg = MIMEMultipart()
        msg['From']    = f"{biz_name} <{GMAIL_USER}>"
        msg['To']      = to_email
        msg['Subject'] = f"Invoice {inv_num} from {biz_name}"
        msg.attach(MIMEText(body, 'plain'))
        part = MIMEBase('application', 'octet-stream')
        part.set_payload(pdf_bytes)
        encoders.encode_base64(part)
        part.add_header('Content-Disposition', f'attachment; filename="{inv_num}.pdf"')
        msg.attach(part)
        with smtplib.SMTP_SSL('smtp.gmail.com', 465) as s:
            s.login(GMAIL_USER, GMAIL_PASSWORD)
            s.sendmail(GMAIL_USER, to_email, msg.as_string())
            s.sendmail(GMAIL_USER, GMAIL_USER, msg.as_string())
        log.info(f"Email sent to {to_email} for {inv_num}")
        return True
    except Exception as e:
        log.error(f"Email failed: {e}")
        return False

# ─────────────────────────────────────────────
# API — CONFIG
# ─────────────────────────────────────────────
@app.route("/")
def index():
    return send_from_directory("inv_static", "index.html")

@app.route("/new")
def new_invoice_page():
    return send_from_directory("inv_static", "invoice.html")

@app.route("/api/config")
def api_config():
    return jsonify({
        "business_name":    BUSINESS_NAME,
        "business_email":   BUSINESS_EMAIL,
        "business_phone":   BUSINESS_PHONE,
        "business_address": BUSINESS_ADDRESS,
        "business_ntn":     BUSINESS_NTN,
        "easypaisa":        EASYPAISA_NUM,
        "jazzcash":         JAZZCASH_NUM,
        "gmail_ok":         bool(GMAIL_USER and GMAIL_PASSWORD),
        "gemini_ok":        bool(GEMINI_API_KEY),
    })

# ─────────────────────────────────────────────
# API — CLIENTS
# ─────────────────────────────────────────────
@app.route("/api/clients", methods=["GET"])
def list_clients():
    db = get_db()
    rows = db.execute("SELECT * FROM clients ORDER BY name").fetchall()
    return jsonify([dict(r) for r in rows])

@app.route("/api/clients", methods=["POST"])
def create_client():
    d  = request.json
    db = get_db()
    try:
        db.execute("INSERT INTO clients(name,email,phone,address,currency) VALUES(?,?,?,?,?)",
                   (d["name"], d["email"], d.get("phone",""), d.get("address",""), d.get("currency","PKR")))
        db.commit()
        row = db.execute("SELECT * FROM clients WHERE email=?", (d["email"],)).fetchone()
        return jsonify(dict(row))
    except sqlite3.IntegrityError:
        row = db.execute("SELECT * FROM clients WHERE email=?", (d["email"],)).fetchone()
        return jsonify(dict(row))

@app.route("/api/clients/search")
def search_clients():
    q  = request.args.get("q","")
    db = get_db()
    rows = db.execute("SELECT * FROM clients WHERE name LIKE ? OR email LIKE ? LIMIT 8",
                      (f"%{q}%", f"%{q}%")).fetchall()
    return jsonify([dict(r) for r in rows])

@app.route("/api/clients/<int:cid>")
def get_client(cid):
    db  = get_db()
    row = db.execute("SELECT * FROM clients WHERE id=?", (cid,)).fetchone()
    if not row: return jsonify({"error":"Not found"}), 404
    invs = db.execute(
        "SELECT invoice_number, total, status, currency, invoice_date FROM invoices WHERE client_id=? ORDER BY created_at DESC LIMIT 10",
        (cid,)).fetchall()
    return jsonify({"client": dict(row), "invoices": [dict(i) for i in invs]})

# ─────────────────────────────────────────────
# API — INVOICES
# ─────────────────────────────────────────────
@app.route("/api/invoices", methods=["GET"])
def list_invoices():
    db     = get_db()
    status = request.args.get("status","")
    q      = request.args.get("q","")
    sql    = "SELECT * FROM invoices WHERE 1=1"
    params = []
    if status: sql += " AND status=?";          params.append(status)
    if q:      sql += " AND (client_name LIKE ? OR invoice_number LIKE ?)"; params += [f"%{q}%",f"%{q}%"]
    sql   += " ORDER BY created_at DESC LIMIT 100"
    rows   = db.execute(sql, params).fetchall()
    return jsonify([dict(r) for r in rows])

@app.route("/api/invoices/<inv_num>")
def get_invoice(inv_num):
    db  = get_db()
    inv = db.execute("SELECT * FROM invoices WHERE invoice_number=?", (inv_num,)).fetchone()
    if not inv: return jsonify({"error":"Not found"}), 404
    items = db.execute("SELECT * FROM invoice_items WHERE invoice_id=?", (inv["id"],)).fetchall()
    return jsonify({"invoice": dict(inv), "items": [dict(i) for i in items]})

@app.route("/api/invoices/<inv_num>/status", methods=["PATCH"])
def update_status(inv_num):
    d      = request.json
    status = d.get("status","")
    paid   = float(d.get("amount_paid", 0))
    db     = get_db()
    db.execute("UPDATE invoices SET status=?, amount_paid=? WHERE invoice_number=?",
               (status, paid, inv_num))
    db.commit()
    return jsonify({"ok": True})

@app.route("/api/stats")
def stats():
    db = get_db()
    total_inv   = db.execute("SELECT COUNT(*) FROM invoices").fetchone()[0]
    total_rev   = db.execute("SELECT COALESCE(SUM(total),0) FROM invoices WHERE currency='PKR'").fetchone()[0]
    paid_rev    = db.execute("SELECT COALESCE(SUM(total),0) FROM invoices WHERE status='PAID' AND currency='PKR'").fetchone()[0]
    pending     = db.execute("SELECT COUNT(*) FROM invoices WHERE status='SENT'").fetchone()[0]
    overdue     = db.execute("SELECT COUNT(*) FROM invoices WHERE status='SENT' AND due_date < date('now')").fetchone()[0]
    clients     = db.execute("SELECT COUNT(*) FROM clients").fetchone()[0]
    usd_rev     = db.execute("SELECT COALESCE(SUM(total),0) FROM invoices WHERE currency='USD'").fetchone()[0]
    monthly     = db.execute("""
        SELECT strftime('%Y-%m', created_at) as month, SUM(total) as total
        FROM invoices WHERE currency='PKR'
        GROUP BY month ORDER BY month DESC LIMIT 6
    """).fetchall()
    return jsonify({
        "total_invoices": total_inv,
        "total_revenue_pkr": total_rev,
        "paid_revenue_pkr":  paid_rev,
        "pending_invoices":  pending,
        "overdue_invoices":  overdue,
        "total_clients":     clients,
        "total_revenue_usd": usd_rev,
        "monthly": [dict(r) for r in monthly],
    })

# ─────────────────────────────────────────────
# API — GENERATE INVOICE (main)
# ─────────────────────────────────────────────
@app.route("/api/generate-invoice", methods=["POST"])
def generate_invoice():
    d = request.json
    required = ["client_name","client_email","items"]
    for f in required:
        if not d.get(f):
            return jsonify({"error": f"Missing: {f}"}), 400

    items = d["items"]
    if not items or not isinstance(items, list):
        return jsonify({"error": "items must be a non-empty list"}), 400

    try:
        currency  = d.get("currency", "PKR")
        tax_pct   = float(d.get("tax_percent", 0))
        due_days  = int(d.get("due_days", 15))
        today     = datetime.date.today()
        due_date  = today + datetime.timedelta(days=due_days)
        inv_num   = get_next_invoice_number()
        db        = get_db()

        # Upsert client
        db.execute("""INSERT INTO clients(name,email,phone,address,currency)
                      VALUES(?,?,?,?,?)
                      ON CONFLICT(email) DO UPDATE SET name=excluded.name""",
                   (d["client_name"], d["client_email"],
                    d.get("client_phone",""), d.get("client_address",""), currency))
        db.commit()
        client = db.execute("SELECT id FROM clients WHERE email=?", (d["client_email"],)).fetchone()

        # Process items
        processed_items = []
        subtotal = 0
        for item in items:
            qty        = float(item.get("qty", 1))
            unit_price = float(item["unit_price"])
            amount     = qty * unit_price
            subtotal  += amount
            desc       = enhance_description(item["description"], amount, currency)
            processed_items.append({
                "description": desc,
                "qty":         qty,
                "unit_price":  unit_price,
                "amount":      amount,
            })

        tax_amount = subtotal * tax_pct / 100
        total      = subtotal + tax_amount

        # Build PDF data
        pdf_data = {
            "invoice_number":   inv_num,
            "invoice_date":     today.strftime("%d %b %Y"),
            "due_date":         due_date.strftime("%d %b %Y"),
            "client_name":      d["client_name"],
            "client_email":     d["client_email"],
            "business_name":    d.get("business_name",    BUSINESS_NAME),
            "business_email":   d.get("business_email",   BUSINESS_EMAIL),
            "business_phone":   d.get("business_phone",   BUSINESS_PHONE),
            "business_address": d.get("business_address", BUSINESS_ADDRESS),
            "business_ntn":     d.get("business_ntn",     BUSINESS_NTN),
            "easypaisa":        d.get("easypaisa",        EASYPAISA_NUM),
            "jazzcash":         d.get("jazzcash",         JAZZCASH_NUM),
            "currency":         currency,
            "tax_percent":      tax_pct,
            "items":            processed_items,
            "notes":            d.get("notes",""),
        }

        pdf_bytes = generate_pdf(pdf_data)
        pdf_path  = INVOICES_DIR / f"{inv_num}.pdf"
        pdf_path.write_bytes(pdf_bytes)

        # Save to DB
        db.execute("""INSERT INTO invoices
            (invoice_number,client_id,client_name,client_email,currency,
             subtotal,tax_percent,tax_amount,total,due_date,invoice_date,notes,pdf_path)
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (inv_num, client["id"], d["client_name"], d["client_email"], currency,
             subtotal, tax_pct, tax_amount, total,
             due_date.strftime("%Y-%m-%d"), today.strftime("%Y-%m-%d"),
             d.get("notes",""), str(pdf_path)))
        inv_id = db.execute("SELECT id FROM invoices WHERE invoice_number=?", (inv_num,)).fetchone()["id"]

        for item in processed_items:
            db.execute("INSERT INTO invoice_items(invoice_id,description,qty,unit_price,amount) VALUES(?,?,?,?,?)",
                       (inv_id, item["description"], item["qty"], item["unit_price"], item["amount"]))
        db.commit()

        # Email
        email_sent = False
        email_body = generate_email_body(d["client_name"], inv_num,
                       processed_items[0]["description"], total,
                       due_date.strftime("%d %b %Y"),
                       pdf_data["business_name"], currency)

        if d.get("send_email", True) and GMAIL_USER and GMAIL_PASSWORD:
            email_sent = send_email(d["client_email"], d["client_name"],
                                    inv_num, email_body, pdf_bytes, pdf_data["business_name"])
            db.execute("UPDATE invoices SET email_sent=? WHERE invoice_number=?",
                       (1 if email_sent else 0, inv_num))
            db.commit()

        return jsonify({
            "success":        True,
            "invoice_number": inv_num,
            "subtotal":       subtotal,
            "tax_amount":     tax_amount,
            "total":          total,
            "currency":       currency,
            "email_sent":     email_sent,
            "email_preview":  email_body,
            "pdf_url":        f"/invoices/{inv_num}.pdf",
        })

    except Exception as e:
        log.error(f"Invoice generation failed: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500

@app.route("/api/webhook/sheets", methods=["POST"])
def sheets_webhook():
    if request.headers.get("X-Webhook-Secret","") != WEBHOOK_SECRET:
        return jsonify({"error":"Unauthorized"}), 401
    return generate_invoice()

@app.route("/invoices/<filename>")
def serve_invoice(filename):
    return send_from_directory("invoices", filename)

# ─────────────────────────────────────────────
# BOOT
# ─────────────────────────────────────────────
if __name__ == "__main__":
    init_db()
    log.info(f"InvoiceFlow starting — Business: {BUSINESS_NAME}")
    log.info(f"Gmail: {'OK' if GMAIL_USER else 'NOT SET'} | Gemini: {'OK' if GEMINI_API_KEY else 'NOT SET'}")
    print("\n  🚀 InvoiceFlow running at http://localhost:5001\n")
    app.run(debug=False, port=5001)