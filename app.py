import csv
import hmac
import io
import json
import os
import re
import smtplib
from datetime import datetime, date, time
from email.message import EmailMessage
from functools import wraps

import pandas as pd
from dotenv import load_dotenv
from flask import Flask, flash, jsonify, redirect, render_template, request, send_file, session, url_for
from sqlalchemy import or_, func
from werkzeug.utils import secure_filename

from models import db, User, Lead, Property, Followup, Task, LeadNote, ActivityLog, ImportHistory, Role, LeadStatus, Priority, utcnow

load_dotenv()

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
app = Flask(__name__)
DEFAULT_DATABASE = os.path.join(app.instance_path, "99acres_crm.db")
app.config.update(
    SECRET_KEY=os.getenv("SECRET_KEY", "dev-only-change-me"),
    SQLALCHEMY_DATABASE_URI=os.getenv("YAYATH_CRM_POSTGRES_URLT_DATABASE}").replace("postgres://", "postgresql://"),SQLALCHEMY_DATABASE_URI=os.getenv("YAYATH_CRM_POSTGRES_URL", f"sqlite:///{DEFAULT_DATABASE}").replace("postgres://", "postgresql://"),SQLALCHEMY_DATABASE_URI=os.getenv("YAYATH_CRM_POSTGRES_URL", f"sqlite:///{DEFAULT_DATABASE}").replace("postgres://", "postgresql://"),
    SQLALCHEMY_TRACK_MODIFICATIONS=False,
    MAX_CONTENT_LENGTH=25 * 1024 * 1024,
)
db.init_app(app)

STATUS_VALUES = [s.value for s in LeadStatus]
PRIORITY_VALUES = [p.value for p in Priority]
ACTION_TYPES = ["Call", "WhatsApp", "Meeting", "Site Visit", "Email", "Other"]
LEGACY_STATUS_MAP = {
    "Contacted": LeadStatus.QUALIFIED.value,
    "Interested": LeadStatus.QUALIFIED.value,
    "Follow-up Required": LeadStatus.QUALIFIED.value,
    "Site Visit Scheduled": LeadStatus.MEETING_DONE.value,
    "Site Visit Done": LeadStatus.MEETING_DONE.value,
    "Negotiation": LeadStatus.PROPOSAL_SENT.value,
    "Disqualified": LeadStatus.NEW.value,
}


def current_user():
    uid = session.get("user_id")
    return db.session.get(User, uid) if uid else None


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not current_user():
            return redirect(url_for("login", next=request.path))
        return view(*args, **kwargs)
    return wrapped


def roles_required(*roles):
    def deco(view):
        @wraps(view)
        @login_required
        def wrapped(*args, **kwargs):
            user = current_user()
            if user.role not in [r.value if isinstance(r, Role) else r for r in roles]:
                flash("You do not have permission for this action.", "danger")
                return redirect(url_for("dashboard"))
            return view(*args, **kwargs)
        return wrapped
    return deco


def parse_date(value):
    if not value:
        return None
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%m/%d/%Y"):
        try:
            return datetime.strptime(str(value).strip(), fmt).date()
        except ValueError:
            pass
    if isinstance(value, (pd.Timestamp, datetime)):
        return value.date()
    if isinstance(value, date):
        return value
    return None


def parse_time(value):
    if value is None or str(value).strip() == "":
        return None
    if isinstance(value, time):
        return value
    if isinstance(value, pd.Timestamp):
        return value.time()
    for fmt in ("%H:%M", "%I:%M %p", "%H:%M:%S"):
        try:
            return datetime.strptime(str(value).strip(), fmt).time()
        except ValueError:
            pass
    return None


def clean_phone(value):
    return re.sub(r"[^0-9+]", "", str(value or "")).strip()


def import_staging_path(import_id):
    return os.path.join(app.instance_path, f"import_{import_id}.json")


IMPORT_ALIASES = {
    "full_name": ["full_name", "fullname", "name", "lead_name", "customer_name", "client_name", "customer", "lead"],
    "phone": ["phone", "mobile", "mobile_number", "mobile_no", "phone_number", "phone_no", "contact", "contact_number", "contact_no", "telephone", "whatsapp", "whatsapp_number"],
    "alternate_phone": ["alternate_phone", "alternate_mobile", "secondary_phone"],
    "email": ["email", "email_address", "mail"],
    "city": ["city", "town"],
    "location": ["location", "locality", "area", "address"],
    "property_name": ["property_name", "property", "project", "project_name"],
    "property_type": ["property_type", "type"],
    "budget": ["budget", "price", "budget_range"],
    "requirement": ["requirement", "requirements", "demand"],
    "bhk": ["bhk", "bedrooms", "bedroom"],
    "size": ["size", "area", "property_size", "sqft"],
    "furnishing": ["furnishing", "furnished"],
    "purpose": ["purpose", "listing_type", "buy_rent"],
    "status": ["status", "lead_status"],
    "priority": ["priority", "lead_priority"],
    "assigned_to": ["assigned_to", "assigned", "sales_person", "agent"],
    "followup_date": ["followup_date", "follow_up_date", "next_followup_date"],
    "followup_time": ["followup_time", "follow_up_time", "next_followup_time"],
    "notes": ["notes", "note", "remarks", "comments"],
    "source": ["source", "lead_source", "channel", "origin"],
}

PROPERTY_ALIASES = {
    "property_id": ["listing_id", "listingid", "property_id", "propertyid", "id"],
    "property_name": ["society", "society_name", "property_name", "project", "project_name", "locality"],
    "property_type": ["proptype", "property_type", "propertytype", "type"],
    "location": ["locality", "location", "area"],
    "address": ["society", "address"],
    "city": ["city", "town"],
    "size": ["size", "area", "property_size", "sqft"],
    "price": ["price", "amount", "property_price"],
    "availability_status": ["listing_status", "listingstatus", "status", "availability"],
    "description": ["category", "verification", "description", "remarks"],
}


def import_mapping(columns):
    normalized = {re.sub(r"[^a-z0-9]", "", str(column).lower()): column for column in columns}
    mapping = {}
    for field, aliases in IMPORT_ALIASES.items():
        for alias in aliases:
            key = re.sub(r"[^a-z0-9]", "", alias)
            if key in normalized:
                mapping[field] = normalized[key]
                break
    return mapping


def property_import_mapping(columns):
    normalized = {re.sub(r"[^a-z0-9]", "", str(column).lower()): column for column in columns}
    mapping = {}
    for field, aliases in PROPERTY_ALIASES.items():
        for alias in aliases:
            if re.sub(r"[^a-z0-9]", "", alias) in normalized:
                mapping[field] = normalized[re.sub(r"[^a-z0-9]", "", alias)]
                break
    return mapping


def clean_price(value):
    cleaned = re.sub(r"[^0-9.]", "", str(value or "")).strip()
    try:
        return float(cleaned) if cleaned else None
    except ValueError:
        return None


def budget_amount(value):
    text = str(value or "").lower().replace(",", "").strip()
    amount = clean_price(text)
    if amount is None:
        return None
    if re.search(r"\b(cr|crore|crores)\b|\bcr$", text):
        return amount * 10000000
    if re.search(r"\b(l|lac|lakh|lakhs)\b|\bl$", text):
        return amount * 100000
    if re.search(r"\b(k|thousand)\b|\bk$", text):
        return amount * 1000
    return amount


def fallback_import_value(row, field):
    if field == "full_name":
        keys = ("name", "customer", "client", "lead")
        for column, value in row.items():
            normalized = re.sub(r"[^a-z0-9]", "", str(column).lower())
            if any(key in normalized for key in keys) and str(value).strip():
                return str(value).strip()
    if field == "phone":
        for value in row.values():
            candidate = clean_phone(value)
            if re.fullmatch(r"\+?[0-9]{8,15}", candidate):
                return candidate
    return ""


def log_activity(lead_id, user_id, activity_type, description):
    db.session.add(ActivityLog(lead_id=lead_id, user_id=user_id, activity_type=activity_type, description=description))


def visible_leads(user):
    q = Lead.query.filter(Lead.deleted_at.is_(None))
    if user.role == Role.SALES_EMPLOYEE.value:
        q = q.filter(Lead.assigned_to == user.id)
    return q


def serialize_lead(lead):
    return {
        "id": lead.id, "lead_id": lead.lead_id, "full_name": lead.full_name, "phone": lead.phone,
        "alternate_phone": lead.alternate_phone, "email": lead.email, "source": lead.source,
        "property_name": lead.property_name, "property_type": lead.property_type, "location": lead.location,
        "city": lead.city, "budget": lead.budget, "requirement": lead.requirement, "bhk": lead.bhk,
        "size": lead.size, "furnishing": lead.furnishing, "purpose": lead.purpose,
        "status": lead.status, "priority": lead.priority, "assigned_to": lead.assigned_user.full_name if lead.assigned_user else "Unassigned",
        "last_contact_date": lead.last_contact_date.isoformat() if lead.last_contact_date else None,
        "next_followup_date": lead.next_followup_date.isoformat() if lead.next_followup_date else None,
        "next_followup_time": lead.next_followup_time.strftime("%H:%M") if lead.next_followup_time else None,
        "created_at": lead.created_at.isoformat() if lead.created_at else None,
        "updated_at": lead.updated_at.isoformat() if lead.updated_at else None,
        "notes": lead.notes,
    }


def next_lead_id():
    year = datetime.utcnow().year
    prefix = f"99A-{year}-"
    last = Lead.query.filter(Lead.lead_id.like(f"{prefix}%")).order_by(Lead.id.desc()).first()
    num = int(last.lead_id.split("-")[-1]) + 1 if last else 1
    return f"{prefix}{num:05d}"


def find_duplicate(phone, email=None, exclude_id=None):
    conditions = [Lead.phone == clean_phone(phone)]
    if email:
        conditions.append(func.lower(Lead.email) == str(email).lower().strip())
    q = Lead.query.filter(Lead.deleted_at.is_(None), or_(*conditions))
    if exclude_id:
        q = q.filter(Lead.id != exclude_id)
    return q.first()


def form_data():
    return {
        "full_name": request.form.get("full_name", "").strip(),
        "phone": clean_phone(request.form.get("phone")),
        "alternate_phone": clean_phone(request.form.get("alternate_phone")),
        "email": request.form.get("email", "").strip(),
        "city": request.form.get("city", "").strip(),
        "location": request.form.get("location", "").strip(),
        "property_name": request.form.get("property_name", "").strip(),
        "property_type": request.form.get("property_type", "").strip(),
        "budget": request.form.get("budget", "").strip(),
        "requirement": request.form.get("requirement", "").strip(),
        "bhk": request.form.get("bhk", "").strip(),
        "size": request.form.get("size", "").strip(),
        "furnishing": request.form.get("furnishing", "").strip(),
        "purpose": request.form.get("purpose", "").strip(),
        "status": LEGACY_STATUS_MAP.get(request.form.get("status", LeadStatus.NEW.value), request.form.get("status", LeadStatus.NEW.value)),
        "priority": request.form.get("priority", Priority.MEDIUM.value),
        "assigned_to": int(request.form["assigned_to"]) if request.form.get("assigned_to") else None,
        "next_followup_date": parse_date(request.form.get("next_followup_date")),
        "next_followup_time": parse_time(request.form.get("next_followup_time")),
        "notes": request.form.get("notes", "").strip(),
        "last_contact_date": parse_date(request.form.get("last_contact_date")),
    }


@app.context_processor
def inject_globals():
    return {"user": current_user(), "STATUS_VALUES": STATUS_VALUES, "PRIORITY_VALUES": PRIORITY_VALUES, "ACTION_TYPES": ACTION_TYPES}


def normalize_legacy_lead_statuses():
    for old_status, new_status in LEGACY_STATUS_MAP.items():
        Lead.query.filter(Lead.status == old_status).update({Lead.status: new_status}, synchronize_session=False)
    db.session.commit()


def ensure_import_columns():
    inspector = db.inspect(db.engine)
    for table in ("leads", "properties"):
        if "import_id" not in {column["name"] for column in inspector.get_columns(table)}:
            db.session.execute(db.text(f"ALTER TABLE {table} ADD COLUMN import_id INTEGER"))
    db.session.commit()


@app.cli.command("init-db")
def init_db():
    db.create_all()
    ensure_import_columns()
    normalize_legacy_lead_statuses()
    admin_email = os.getenv("ADMIN_EMAIL", "admin@example.com")
    admin_password = os.getenv("ADMIN_PASSWORD", "ChangeMeImmediately!")
    if not User.query.filter_by(email=admin_email).first():
        u = User(full_name="System Admin", email=admin_email, role=Role.ADMIN.value, status="active")
        u.set_password(admin_password)
        db.session.add(u)
        db.session.commit()
    print("Database initialized.")


@app.route("/login", methods=["GET", "POST"])
def login():
    if current_user():
        return redirect(url_for("dashboard"))
    if request.method == "POST":
        email = request.form.get("email", "").lower().strip()
        password = request.form.get("password", "")
        user = User.query.filter(func.lower(User.email) == email, User.status == "active").first()
        if not user or not user.check_password(password):
            flash("Invalid email or password.", "danger")
            return render_template("login.html")
        session.clear()
        session["user_id"] = user.id
        return redirect(request.args.get("next") or url_for("dashboard"))
    return render_template("login.html")


@app.post("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/")
@login_required
def dashboard():
    user = current_user()
    q = visible_leads(user)
    min_revenue = request.args.get("min_revenue", "").strip()
    max_revenue = request.args.get("max_revenue", "").strip()
    min_amount = budget_amount(min_revenue) if min_revenue else None
    max_amount = budget_amount(max_revenue) if max_revenue else None
    dashboard_leads = [lead for lead in q.order_by(Lead.created_at.desc()).all()
                       if (min_amount is None or (budget_amount(lead.budget) or 0) >= min_amount)
                       and (max_amount is None or (budget_amount(lead.budget) or 0) <= max_amount)]
    today = date.today()
    total = len(dashboard_leads)
    status_counts = {s: sum(1 for lead in dashboard_leads if lead.status == s) for s in STATUS_VALUES}
    qualified_statuses = {LeadStatus.QUALIFIED.value}
    closed_statuses = {LeadStatus.DEAL_CLOSED.value}
    open_statuses = set(STATUS_VALUES) - closed_statuses
    funnel = {
        "total": total,
        "new": status_counts.get(LeadStatus.NEW.value, 0),
        "qualified": sum(status_counts.get(status, 0) for status in qualified_statuses),
        "meeting_done": status_counts.get(LeadStatus.MEETING_DONE.value, 0),
        "proposal_sent": status_counts.get(LeadStatus.PROPOSAL_SENT.value, 0),
        "active_pipeline": sum(status_counts.get(status, 0) for status in open_statuses),
        "deal_closed": sum(status_counts.get(status, 0) for status in closed_statuses),
    }
    max_metric = max(funnel.values(), default=1)
    revenue_total = sum(budget_amount(lead.budget) or 0 for lead in dashboard_leads)
    closed_revenue = sum(budget_amount(lead.budget) or 0 for lead in dashboard_leads if lead.status in closed_statuses)
    imported_sheets = ImportHistory.query.count()
    imported_rows = db.session.query(func.coalesce(func.sum(ImportHistory.imported), 0)).scalar()
    due_today = Followup.query.join(Lead).filter(Lead.deleted_at.is_(None), Followup.followup_date == today, Followup.status == "Pending")
    future = Followup.query.join(Lead).filter(Lead.deleted_at.is_(None), Followup.followup_date > today, Followup.status == "Pending")
    overdue = Followup.query.join(Lead).filter(Lead.deleted_at.is_(None), Followup.followup_date < today, Followup.status.notin_(["Completed", "Cancelled"]))
    if user.role == Role.SALES_EMPLOYEE.value:
        due_today = due_today.filter(Followup.assigned_to == user.id)
        future = future.filter(Followup.assigned_to == user.id)
        overdue = overdue.filter(Followup.assigned_to == user.id)
    latest = dashboard_leads[:8]
    priority = [lead for lead in dashboard_leads if lead.priority == Priority.HIGH.value][:8]
    return render_template("dashboard.html", total=total, status_counts=status_counts, funnel=funnel, max_metric=max_metric,
                           revenue_total=revenue_total, closed_revenue=closed_revenue,
                           imported_sheets=imported_sheets, imported_rows=imported_rows,
                           min_revenue=min_revenue, max_revenue=max_revenue,
                           today_followups=due_today.count(), upcoming_followups=future.count(),
                           overdue_followups=overdue.count(), latest=latest, priority=priority)


@app.route("/leads")
@login_required
def leads():
    user = current_user()
    q = visible_leads(user)
    search = request.args.get("search", "").strip()
    filters = {k: request.args.get(k, "").strip() for k in ("status", "priority", "property", "assigned_to", "location", "created_from", "created_to")}
    if search:
        like = f"%{search}%"
        q = q.filter(or_(Lead.full_name.ilike(like), Lead.phone.ilike(like), Lead.email.ilike(like), Lead.lead_id.ilike(like), Lead.property_name.ilike(like), Lead.location.ilike(like)))
    if filters["status"]: q = q.filter(Lead.status == filters["status"])
    if filters["priority"]: q = q.filter(Lead.priority == filters["priority"])
    if filters["property"]: q = q.filter(Lead.property_name.ilike(f"%{filters['property']}%"))
    if filters["assigned_to"]: q = q.filter(Lead.assigned_to == int(filters["assigned_to"]))
    if filters["location"]: q = q.filter(Lead.location.ilike(f"%{filters['location']}%"))
    if filters["created_from"]:
        d = parse_date(filters["created_from"])
        if d: q = q.filter(Lead.created_at >= datetime.combine(d, time.min))
    if filters["created_to"]:
        d = parse_date(filters["created_to"])
        if d: q = q.filter(Lead.created_at <= datetime.combine(d, time.max))
    page = max(int(request.args.get("page", 1)), 1)
    per_page = min(max(int(request.args.get("per_page", 25)), 25), 100)
    pagination = q.order_by(Lead.created_at.desc()).paginate(page=page, per_page=per_page, error_out=False)
    users = User.query.filter_by(status="active").order_by(User.full_name).all()
    return render_template("leads.html", leads=pagination.items, pagination=pagination, users=users, filters=filters, search=search)


@app.route("/leads/new", methods=["GET", "POST"])
@login_required
def add_lead():
    user = current_user()
    users = User.query.filter_by(status="active").order_by(User.full_name).all()
    if request.method == "POST":
        data = form_data()
        if not data["full_name"] or not data["phone"]:
            flash("Full Name and Phone are required.", "danger")
            return render_template("leads.html", leads=[], pagination=None, users=users, form_mode="new")
        if not re.fullmatch(r"\+?[0-9]{8,15}", data["phone"]):
            flash("Invalid phone number.", "danger")
            return render_template("leads.html", leads=[], pagination=None, users=users, form_mode="new")
        dup = find_duplicate(data["phone"], data["email"])
        if dup:
            flash(f"Possible duplicate lead found: {dup.lead_id}. Open it or continue intentionally.", "warning")
            return redirect(url_for("lead_detail", lead_id=dup.id, duplicate_from="new"))
        lead = Lead(lead_id=next_lead_id(), source="99Acres", created_by=user.id, **data)
        db.session.add(lead)
        db.session.flush()
        log_activity(lead.id, user.id, "Lead Created", f"Created 99Acres lead {lead.lead_id}.")
        db.session.commit()
        flash("Lead created successfully.", "success")
        return redirect(url_for("lead_detail", lead_id=lead.id))
    return render_template("lead_detail.html", lead=None, users=users, new_mode=True)


@app.route("/leads/<int:lead_id>", methods=["GET", "POST"])
@login_required
def lead_detail(lead_id):
    user = current_user()
    lead = visible_leads(user).filter(Lead.id == lead_id).first_or_404()
    users = User.query.filter_by(status="active").order_by(User.full_name).all()
    if request.method == "POST":
        old_status, old_priority, old_assigned = lead.status, lead.priority, lead.assigned_to
        data = form_data()
        if not data["full_name"] or not data["phone"]:
            flash("Full Name and Phone are required.", "danger")
            return redirect(url_for("lead_detail", lead_id=lead.id))
        dup = find_duplicate(data["phone"], data["email"], exclude_id=lead.id)
        if dup:
            flash(f"Possible duplicate lead found: {dup.lead_id}.", "warning")
            return redirect(url_for("lead_detail", lead_id=lead.id))
        for k, v in data.items(): setattr(lead, k, v)
        lead.source = "99Acres"
        lead.updated_at = utcnow()
        log_activity(lead.id, user.id, "Lead Edited", "Lead details updated.")
        if old_status != lead.status: log_activity(lead.id, user.id, "Status Changed", f"{old_status} → {lead.status}")
        if old_priority != lead.priority: log_activity(lead.id, user.id, "Priority Changed", f"{old_priority} → {lead.priority}")
        if old_assigned != lead.assigned_to: log_activity(lead.id, user.id, "Lead Assigned", "Assigned employee changed.")
        db.session.commit()
        flash("Lead updated successfully.", "success")
        return redirect(url_for("lead_detail", lead_id=lead.id))
    return render_template("lead_detail.html", lead=lead, users=users, new_mode=False)


@app.route("/leads/<int:lead_id>/send-email", methods=["GET", "POST"])
@login_required
def send_lead_email(lead_id):
    user = current_user()
    lead = visible_leads(user).filter(Lead.id == lead_id).first_or_404()
    if request.method == "GET":
        if not lead.email:
            flash("This lead does not have an email address.", "danger")
            return redirect(url_for("lead_detail", lead_id=lead.id))
        return render_template("send_email.html", lead=lead)
    if not lead.email:
        flash("This lead does not have an email address.", "danger")
        return redirect(url_for("lead_detail", lead_id=lead.id))

    smtp_host = os.getenv("SMTP_HOST")
    smtp_username = os.getenv("SMTP_USERNAME")
    smtp_password = os.getenv("SMTP_PASSWORD")
    if not smtp_host or not smtp_username or not smtp_password:
        flash("Email is not configured. Set SMTP_HOST, SMTP_USERNAME, SMTP_PASSWORD, and MAIL_FROM.", "danger")
        return redirect(url_for("lead_detail", lead_id=lead.id))

    message = EmailMessage()
    message["Subject"] = request.form.get("subject", "99Acres CRM Follow-up").strip() or "99Acres CRM Follow-up"
    message["From"] = os.getenv("MAIL_FROM", smtp_username)
    message["To"] = lead.email
    message.set_content(request.form.get("body", "").strip() or f"Hello {lead.full_name},\n\nWe are following up regarding your property requirement.\n")
    try:
        smtp_port = int(os.getenv("SMTP_PORT", "587"))
        with smtplib.SMTP(smtp_host, smtp_port, timeout=20) as smtp:
            if os.getenv("SMTP_USE_TLS", "true").lower() in {"1", "true", "yes"}:
                smtp.starttls()
            smtp.login(smtp_username, smtp_password)
            smtp.send_message(message)
    except (OSError, smtplib.SMTPException, ValueError) as exc:
        app.logger.exception("Could not send lead email")
        flash(f"Email could not be sent: {exc}", "danger")
        return redirect(url_for("lead_detail", lead_id=lead.id))

    log_activity(lead.id, user.id, "Email Sent", f"Email sent to {lead.email}.")
    db.session.commit()
    flash(f"Email sent to {lead.email}.", "success")
    return redirect(url_for("lead_detail", lead_id=lead.id))


@app.post("/leads/<int:lead_id>/delete")
@roles_required(Role.ADMIN)
def delete_lead(lead_id):
    lead = Lead.query.filter(Lead.id == lead_id, Lead.deleted_at.is_(None)).first_or_404()
    lead.deleted_at = utcnow()
    db.session.commit()
    flash("Lead moved to Recently Deleted.", "success")
    return redirect(url_for("leads"))


@app.post("/leads/delete")
@roles_required(Role.ADMIN)
def delete_leads():
    lead_ids = []
    for lead_id in request.form.getlist("lead_ids"):
        try:
            lead_ids.append(int(lead_id))
        except (TypeError, ValueError):
            continue
    if not lead_ids:
        flash("Select at least one lead to delete.", "warning")
        return redirect(url_for("leads"))

    leads_to_delete = visible_leads(current_user()).filter(Lead.id.in_(lead_ids)).all()
    deleted_at = utcnow()
    for lead in leads_to_delete:
        lead.deleted_at = deleted_at
    db.session.commit()
    flash(f"{len(leads_to_delete)} lead(s) moved to Recently Deleted.", "success")
    return redirect(url_for("leads"))


@app.post("/leads/<int:lead_id>/restore")
@roles_required(Role.ADMIN)
def restore_lead(lead_id):
    lead = Lead.query.filter(Lead.id == lead_id).first_or_404()
    lead.deleted_at = None
    db.session.commit()
    flash("Lead restored.", "success")
    return redirect(url_for("leads"))


@app.post("/leads/<int:lead_id>/notes")
@login_required
def add_note(lead_id):
    user = current_user()
    lead = visible_leads(user).filter(Lead.id == lead_id).first_or_404()
    text = request.form.get("note", "").strip()
    if not text:
        flash("Note cannot be empty.", "danger")
    else:
        db.session.add(LeadNote(lead_id=lead.id, note=text, created_by=user.id))
        log_activity(lead.id, user.id, "Note Added", text[:200])
        db.session.commit()
        flash("Note added.", "success")
    return redirect(url_for("lead_detail", lead_id=lead.id))


@app.post("/leads/<int:lead_id>/followups")
@login_required
def add_followup(lead_id):
    user = current_user()
    lead = visible_leads(user).filter(Lead.id == lead_id).first_or_404()
    d = parse_date(request.form.get("followup_date"))
    if not d:
        flash("Valid follow-up date is required.", "danger")
        return redirect(url_for("lead_detail", lead_id=lead.id))
    assigned = int(request.form["assigned_to"]) if request.form.get("assigned_to") else (lead.assigned_to or user.id)
    f = Followup(lead_id=lead.id, assigned_to=assigned, action_type=request.form.get("action_type", "Call"), followup_date=d, followup_time=parse_time(request.form.get("followup_time")), status="Pending", reminder=request.form.get("reminder"), notes=request.form.get("notes"), created_by=user.id)
    lead.next_followup_date, lead.next_followup_time = d, f.followup_time
    db.session.add(f); db.session.flush()
    log_activity(lead.id, user.id, "Follow-up Created", f"{f.action_type} scheduled for {d} {f.followup_time or ''}")
    db.session.commit()
    flash("Follow-up scheduled.", "success")
    return redirect(url_for("lead_detail", lead_id=lead.id))


@app.post("/followups/<int:followup_id>/status")
@login_required
def followup_status(followup_id):
    user = current_user()
    f = Followup.query.get_or_404(followup_id)
    lead = visible_leads(user).filter(Lead.id == f.lead_id).first_or_404()
    new_status = request.form.get("status")
    if new_status not in ["Pending", "Completed", "Rescheduled", "Cancelled"]:
        return jsonify({"error": "Invalid status"}), 400
    f.status = new_status
    if new_status == "Completed": log_activity(lead.id, user.id, "Follow-up Completed", f"{f.action_type} follow-up completed.")
    elif new_status == "Rescheduled": log_activity(lead.id, user.id, "Follow-up Rescheduled", "Follow-up marked for rescheduling.")
    db.session.commit()
    return redirect(url_for("lead_detail", lead_id=lead.id))


@app.route("/followups")
@login_required
def followups():
    user = current_user(); today = date.today()
    q = Followup.query.join(Lead).filter(Lead.deleted_at.is_(None))
    if user.role == Role.SALES_EMPLOYEE.value: q = q.filter(Followup.assigned_to == user.id)
    today_items = q.filter(Followup.followup_date == today, Followup.status == "Pending").order_by(Followup.followup_time).all()
    upcoming = q.filter(Followup.followup_date > today, Followup.status == "Pending").order_by(Followup.followup_date, Followup.followup_time).all()
    overdue = q.filter(Followup.followup_date < today, Followup.status.notin_(["Completed", "Cancelled"])).order_by(Followup.followup_date).all()
    return render_template("followups.html", today_items=today_items, upcoming=upcoming, overdue=overdue)


@app.post("/leads/<int:lead_id>/tasks")
@login_required
def add_task(lead_id):
    user = current_user(); lead = visible_leads(user).filter(Lead.id == lead_id).first_or_404()
    d = parse_date(request.form.get("due_date"))
    if not request.form.get("title") or not d:
        flash("Task title and due date are required.", "danger")
        return redirect(url_for("lead_detail", lead_id=lead.id))
    assigned = int(request.form["assigned_to"]) if request.form.get("assigned_to") else (lead.assigned_to or user.id)
    t = Task(lead_id=lead.id, title=request.form["title"].strip(), task_type=request.form.get("task_type"), description=request.form.get("description"), assigned_to=assigned, due_date=d, due_time=parse_time(request.form.get("due_time")), priority=request.form.get("priority", Priority.MEDIUM.value), status="Pending", created_by=user.id)
    db.session.add(t); db.session.flush(); log_activity(lead.id, user.id, "Task Created", t.title); db.session.commit()
    flash("Task created.", "success")
    return redirect(url_for("lead_detail", lead_id=lead.id))


@app.route("/tasks")
@login_required
def tasks():
    user = current_user(); today = date.today()
    q = Task.query.join(Lead).filter(or_(Lead.deleted_at.is_(None), Lead.id.is_(None)))
    if user.role == Role.SALES_EMPLOYEE.value: q = q.filter(Task.assigned_to == user.id)
    today_items = q.filter(Task.due_date == today, Task.status != "Completed").order_by(Task.due_time).all()
    upcoming = q.filter(Task.due_date > today, Task.status != "Completed").order_by(Task.due_date, Task.due_time).all()
    overdue = q.filter(Task.due_date < today, Task.status != "Completed").order_by(Task.due_date).all()
    completed = q.filter(Task.status == "Completed").order_by(Task.updated_at.desc()).limit(100).all()
    return render_template("tasks.html", today_items=today_items, upcoming=upcoming, overdue=overdue, completed=completed)


@app.post("/tasks/<int:task_id>/status")
@login_required
def task_status(task_id):
    user = current_user(); t = Task.query.get_or_404(task_id)
    if user.role == Role.SALES_EMPLOYEE.value and t.assigned_to != user.id:
        flash("You cannot update this task.", "danger"); return redirect(url_for("tasks"))
    status = request.form.get("status")
    if status not in ["Pending", "In Progress", "Completed"]: return redirect(url_for("tasks"))
    t.status = status
    if t.lead_id: log_activity(t.lead_id, user.id, "Task Completed" if status == "Completed" else "Task Updated", f"Task {t.title}: {status}")
    db.session.commit(); return redirect(url_for("tasks"))


@app.route("/properties", methods=["GET", "POST"])
@login_required
def properties():
    user = current_user()
    if request.method == "POST":
        if user.role not in [Role.ADMIN.value, Role.MANAGER.value]:
            flash("Only admin or manager can add properties.", "danger"); return redirect(url_for("properties"))
        p = Property(property_id=request.form.get("property_id") or f"PROP-{datetime.utcnow().strftime('%Y%m%d%H%M%S')}", property_name=request.form.get("property_name", "").strip(), property_type=request.form.get("property_type"), location=request.form.get("location"), address=request.form.get("address"), city=request.form.get("city"), size=request.form.get("size"), bhk=request.form.get("bhk"), furnishing=request.form.get("furnishing"), price=request.form.get("price") or None, rent=request.form.get("rent") or None, availability_status=request.form.get("availability_status", "Available"), description=request.form.get("description"), created_by=user.id)
        if not p.property_name: flash("Property name is required.", "danger")
        else: db.session.add(p); db.session.commit(); flash("Property created.", "success")
        return redirect(url_for("properties"))
    items = Property.query.filter(Property.deleted_at.is_(None)).order_by(Property.created_at.desc()).all()
    return render_template("properties.html", properties=items)


@app.post("/properties/<int:property_id>/delete")
@roles_required(Role.ADMIN)
def delete_property(property_id):
    p = Property.query.get_or_404(property_id); p.deleted_at = utcnow(); db.session.commit(); flash("Property deleted.", "success"); return redirect(url_for("properties"))


@app.route("/properties/<int:property_id>/edit", methods=["GET", "POST"])
@roles_required(Role.ADMIN, Role.MANAGER)
def edit_property(property_id):
    property_record = Property.query.filter(Property.id == property_id, Property.deleted_at.is_(None)).first_or_404()
    if request.method == "POST":
        property_record.property_id = request.form.get("property_id", "").strip() or property_record.property_id
        property_record.property_name = request.form.get("property_name", "").strip()
        property_record.property_type = request.form.get("property_type", "").strip()
        property_record.location = request.form.get("location", "").strip()
        property_record.address = request.form.get("address", "").strip()
        property_record.city = request.form.get("city", "").strip()
        property_record.size = request.form.get("size", "").strip()
        property_record.price = clean_price(request.form.get("price"))
        property_record.availability_status = request.form.get("availability_status", "Available")
        property_record.description = request.form.get("description", "").strip()
        if not property_record.property_name:
            flash("Property name is required.", "danger")
        else:
            db.session.commit(); flash("Property updated successfully.", "success"); return redirect(url_for("properties"))
    return render_template("property_edit.html", property=property_record)


@app.route("/users", methods=["GET", "POST"])
@roles_required(Role.ADMIN)
def users():
    if request.method == "POST":
        action = request.form.get("action", "create")
        if action == "update":
            target = db.session.get(User, request.form.get("user_id", type=int))
            if not target:
                flash("User not found.", "danger")
                return redirect(url_for("users"))
            email = request.form.get("email", "").lower().strip()
            duplicate = User.query.filter(func.lower(User.email) == email, User.id != target.id).first()
            if duplicate:
                flash("A user with that email already exists.", "danger")
            elif target.id == current_user().id and request.form.get("status") == "inactive":
                flash("You cannot deactivate your own admin account.", "danger")
            else:
                target.full_name = request.form.get("full_name", "").strip()
                target.email = email
                target.phone = request.form.get("phone", "").strip()
                target.role = request.form.get("role", Role.SALES_EMPLOYEE.value)
                target.status = request.form.get("status", "active")
                if request.form.get("password"):
                    target.set_password(request.form["password"])
                db.session.commit()
                flash("User updated successfully.", "success")
            return redirect(url_for("users"))
        email = request.form.get("email", "").lower().strip()
        if User.query.filter(func.lower(User.email) == email).first():
            flash("A user with that email already exists.", "danger")
        else:
            u = User(full_name=request.form.get("full_name", "").strip(), email=email, phone=request.form.get("phone"), role=request.form.get("role", Role.SALES_EMPLOYEE.value), status="active")
            u.set_password(request.form.get("password", "")); db.session.add(u); db.session.commit(); flash("User created.", "success")
        return redirect(url_for("users"))
    return render_template("users.html", users=User.query.order_by(User.created_at.desc()).all())


@app.post("/users/<int:user_id>/delete")
@roles_required(Role.ADMIN)
def delete_user(user_id):
    target = db.session.get(User, user_id)
    if not target:
        flash("User not found.", "danger")
    elif target.id == current_user().id:
        flash("You cannot delete your own admin account.", "danger")
    else:
        target.status = "inactive"
        db.session.commit()
        flash("User deactivated. Existing history and assignments were preserved.", "success")
    return redirect(url_for("users"))


@app.route("/settings")
@login_required
def settings():
    return render_template("settings.html")


@app.route("/reports")
@login_required
def reports():
    user = current_user(); q = visible_leads(user); start = request.args.get("start"); end = request.args.get("end")
    if start:
        d = parse_date(start)
        if d: q = q.filter(Lead.created_at >= datetime.combine(d, time.min))
    if end:
        d = parse_date(end)
        if d: q = q.filter(Lead.created_at <= datetime.combine(d, time.max))
    status_report = q.with_entities(Lead.status, func.count(Lead.id)).group_by(Lead.status).all()
    property_report = q.with_entities(Lead.property_name, func.count(Lead.id)).group_by(Lead.property_name).order_by(func.count(Lead.id).desc()).limit(20).all()
    employee_report = q.join(User, Lead.assigned_to == User.id, isouter=True).with_entities(User.full_name, func.count(Lead.id)).group_by(User.full_name).order_by(func.count(Lead.id).desc()).all()
    closed = q.filter(Lead.status == LeadStatus.DEAL_CLOSED.value).count(); total = q.count(); conversion = round((closed / total) * 100, 2) if total else 0
    return render_template("reports.html", status_report=status_report, property_report=property_report, employee_report=employee_report, conversion=conversion, total=total, closed=closed)


@app.route("/import", methods=["GET", "POST"])
@roles_required(Role.ADMIN, Role.MANAGER)
def import_leads():
    if request.method == "POST":
        file = request.files.get("file")
        if not file or not file.filename:
            flash("Please choose an Excel or CSV file.", "danger"); return redirect(url_for("import_leads"))
        filename = secure_filename(file.filename)
        ext = os.path.splitext(filename)[1].lower()
        if ext not in [".xlsx", ".xls", ".csv"]:
            flash("Unsupported file type. Use .xlsx, .xls or .csv.", "danger"); return redirect(url_for("import_leads"))
        try:
            if ext == ".csv": df = pd.read_csv(file)
            else: df = pd.read_excel(file)
        except Exception as exc:
            flash(f"Unable to read file: {exc}", "danger"); return redirect(url_for("import_leads"))
        if df.empty:
            flash("The uploaded file is empty.", "danger"); return redirect(url_for("import_leads"))
        rows = df.fillna("").to_dict(orient="records")
        import_id = None
        history = ImportHistory(file_name=filename, uploaded_by=current_user().id, total_records=len(rows))
        db.session.add(history); db.session.flush(); import_id = history.id
        os.makedirs(app.instance_path, exist_ok=True)
        with open(import_staging_path(import_id), "w", encoding="utf-8") as staging_file:
            json.dump({"columns": list(df.columns), "rows": rows}, staging_file, default=str)
        columns = list(df.columns)
        is_property_sheet = any(re.sub(r"[^a-z0-9]", "", str(column).lower()) in {"listingid", "proptype", "listingstatus"} for column in columns)
        session["import_preview"] = {"id": import_id, "filename": filename, "columns": columns, "rows": rows[:50], "mapping": property_import_mapping(columns) if is_property_sheet else import_mapping(columns), "kind": "property" if is_property_sheet else "lead"}
        db.session.commit()
        return redirect(url_for("import_preview"))
    history = ImportHistory.query.order_by(ImportHistory.created_at.desc()).limit(20).all()
    return render_template("import.html", history=history)


@app.post("/import/<int:import_id>/delete")
@roles_required(Role.ADMIN, Role.MANAGER)
def delete_import(import_id):
    history = db.session.get(ImportHistory, import_id)
    if not history:
        flash("Import sheet not found.", "danger")
        return redirect(url_for("import_leads"))
    leads = Lead.query.filter_by(import_id=import_id).all()
    lead_ids = [lead.id for lead in leads]
    if lead_ids:
        Followup.query.filter(Followup.lead_id.in_(lead_ids)).delete(synchronize_session=False)
        Task.query.filter(Task.lead_id.in_(lead_ids)).delete(synchronize_session=False)
        LeadNote.query.filter(LeadNote.lead_id.in_(lead_ids)).delete(synchronize_session=False)
        ActivityLog.query.filter(ActivityLog.lead_id.in_(lead_ids)).delete(synchronize_session=False)
        Lead.query.filter(Lead.id.in_(lead_ids)).delete(synchronize_session=False)
    Property.query.filter_by(import_id=import_id).delete(synchronize_session=False)
    staging_file = import_staging_path(import_id)
    if os.path.exists(staging_file):
        os.remove(staging_file)
    filename = history.file_name
    db.session.delete(history)
    db.session.commit()
    flash(f"Imported sheet '{filename}' and its {len(leads)} records were deleted.", "success")
    return redirect(url_for("import_leads"))


@app.route("/import/preview", methods=["GET", "POST"])
@roles_required(Role.ADMIN, Role.MANAGER)
def import_preview():
    payload = session.get("import_preview")
    if not payload: return redirect(url_for("import_leads"))
    rows = payload["rows"]
    if request.method == "POST":
        suggested_mapping = payload.get("mapping", {})
        mapping = {field: request.form.get(field) or suggested_mapping.get(field) for field in IMPORT_ALIASES}
        user = current_user(); history = db.session.get(ImportHistory, payload["id"])
        try:
            with open(import_staging_path(payload["id"]), encoding="utf-8") as staging_file:
                rows = json.load(staging_file)["rows"]
        except (FileNotFoundError, json.JSONDecodeError):
            flash("The staged import file is no longer available. Please upload it again.", "danger")
            return redirect(url_for("import_leads"))
        imported = updated = duplicates = errors = 0
        if payload.get("kind") == "property":
            property_mapping = {field: request.form.get(field) or suggested_mapping.get(field) for field in PROPERTY_ALIASES}
            for row in rows:
                def property_val(field):
                    column = property_mapping.get(field)
                    return str(row.get(column, "")).strip() if column else ""
                property_id = property_val("property_id")
                property_name = property_val("property_name") or property_id
                if not property_id or not property_name:
                    errors += 1
                    continue
                if Property.query.filter_by(property_id=property_id).first():
                    duplicates += 1
                    continue
                listing_status = property_val("availability_status") or "Available"
                if listing_status not in ["Available", "Reserved", "Sold", "Rented", "Inactive"]:
                    listing_status = "Available" if listing_status.lower() in ["active", "yes"] else "Inactive"
                property_record = Property(property_id=property_id, property_name=property_name, property_type=property_val("property_type"), location=property_val("location"), address=property_val("address"), city=property_val("city"), size=property_val("size"), price=clean_price(property_val("price")), availability_status=listing_status, description=property_val("description"), created_by=user.id, import_id=history.id)
                db.session.add(property_record)
                db.session.flush()
                db.session.add(Lead(lead_id=next_lead_id(), full_name=property_name, phone=f"listing-{property_id}", source="99Acres", property_id=property_record.id, property_name=property_name, property_type=property_record.property_type, location=property_record.location, city=property_record.city, size=property_record.size, status=LeadStatus.NEW.value, priority=Priority.MEDIUM.value, created_by=user.id, import_id=history.id, notes="Imported from property listing sheet."))
                imported += 1
            history.imported, history.updated, history.duplicates, history.errors = imported, updated, duplicates, errors
            db.session.commit(); session.pop("import_preview", None)
            try:
                os.remove(import_staging_path(payload["id"]))
            except FileNotFoundError:
                pass
            flash(f"{imported} properties imported successfully. {duplicates} matched existing records were also kept. {errors} invalid records skipped.", "success")
            return redirect(url_for("dashboard"))
        for row in rows:
            def val(field, default=""): return str(row.get(mapping.get(field), default)).strip() if mapping.get(field) else default
            name = val("full_name") or fallback_import_value(row, "full_name")
            phone = clean_phone(val("phone")) or fallback_import_value(row, "phone")
            email = val("email")
            if not name or not phone or not re.fullmatch(r"\+?[0-9]{8,15}", phone): errors += 1; continue
            if not email: email = None
            dup = find_duplicate(phone, email)
            status = val("status", LeadStatus.NEW.value) or LeadStatus.NEW.value
            status = LEGACY_STATUS_MAP.get(status, status)
            if status not in STATUS_VALUES: status = LeadStatus.NEW.value
            assigned = None
            if val("assigned_to"):
                try: assigned = int(val("assigned_to"))
                except Exception: assigned = None
            data = dict(full_name=name, phone=phone, alternate_phone=clean_phone(val("alternate_phone")), email=email, city=val("city"), location=val("location"), property_name=val("property_name"), property_type=val("property_type"), budget=val("budget"), requirement=val("requirement"), bhk=val("bhk"), size=val("size"), furnishing=val("furnishing"), purpose=val("purpose"), status=status, priority=val("priority", Priority.MEDIUM.value) or Priority.MEDIUM.value, assigned_to=assigned, next_followup_date=parse_date(val("followup_date")), next_followup_time=parse_time(val("followup_time")), notes=val("notes"), last_contact_date=None)
            if dup:
                duplicates += 1
            source = val("source", "99Acres") or "99Acres"
            lead = Lead(lead_id=next_lead_id(), source=source[:30], created_by=user.id, import_id=history.id, **data)
            db.session.add(lead); db.session.flush(); log_activity(lead.id, user.id, "Lead Imported", f"Imported from {payload['filename']}"); imported += 1
        history.imported, history.updated, history.duplicates, history.errors = imported, updated, duplicates, errors
        db.session.commit(); session.pop("import_preview", None)
        try:
            os.remove(import_staging_path(payload["id"]))
        except FileNotFoundError:
            pass
        flash(f"{imported} leads imported successfully. {duplicates} matched existing records were also kept. {errors} invalid records skipped.", "success")
        return redirect(url_for("dashboard"))
    fields = list(PROPERTY_ALIASES) if payload.get("kind") == "property" else ["full_name", "phone", "alternate_phone", "email", "city", "location", "property_name", "property_type", "budget", "requirement", "bhk", "size", "furnishing", "purpose", "status", "priority", "assigned_to", "followup_date", "followup_time", "notes", "source"]
    return render_template("property_import.html" if payload.get("kind") == "property" else "import.html", preview=payload, mapping_fields=fields)


def lead_rows_for_export(leads):
    headers = ["Lead ID","Full Name","Phone","Alternate Phone","Email","Source","Property","Property Type","Location","City","Budget","Requirement","BHK","Size","Furnishing","Purpose","Status","Priority","Assigned To","Last Contact Date","Next Follow-up Date","Next Follow-up Time","Created Date","Updated Date","Notes"]
    rows = []
    for l in leads:
        rows.append([l.lead_id,l.full_name,l.phone,l.alternate_phone,l.email,"99Acres",l.property_name,l.property_type,l.location,l.city,l.budget,l.requirement,l.bhk,l.size,l.furnishing,l.purpose,l.status,l.priority,l.assigned_user.full_name if l.assigned_user else "",l.last_contact_date,l.next_followup_date,l.next_followup_time,l.created_at,l.updated_at,l.notes])
    return headers, rows


@app.route("/export/leads")
@login_required
def export_leads():
    user = current_user(); leads = visible_leads(user).order_by(Lead.created_at.desc()).all(); headers, rows = lead_rows_for_export(leads)
    fmt = request.args.get("format", "csv")
    if fmt == "xlsx":
        df = pd.DataFrame(rows, columns=headers); bio = io.BytesIO(); df.to_excel(bio, index=False, engine="openpyxl"); bio.seek(0); return send_file(bio, as_attachment=True, download_name="99Acres_Leads.xlsx", mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    out = io.StringIO(); w = csv.writer(out); w.writerow(headers); w.writerows(rows); bio = io.BytesIO(out.getvalue().encode("utf-8-sig")); return send_file(bio, as_attachment=True, download_name="99Acres_Leads.csv", mimetype="text/csv")


@app.route("/api/dashboard")
@login_required
def api_dashboard():
    user = current_user(); q = visible_leads(user); today = date.today()
    return jsonify({"total": q.count(), "statuses": {s: q.filter(Lead.status == s).count() for s in STATUS_VALUES}, "today_followups": Followup.query.filter(Followup.followup_date == today, Followup.status == "Pending").count()})


@app.post("/api/google-sheet/leads")
def google_sheet_leads():
    expected_token = os.getenv("GOOGLE_SHEET_SYNC_TOKEN", "").strip()
    supplied_token = request.headers.get("X-CRM-Sync-Token", "").strip()
    if not expected_token or not hmac.compare_digest(supplied_token, expected_token):
        return jsonify({"error": "Invalid sync token."}), 401

    payload = request.get_json(silent=True)
    rows = payload if isinstance(payload, list) else [payload]
    if not rows or any(not isinstance(row, dict) for row in rows) or len(rows) > 100:
        return jsonify({"error": "Send one lead or a maximum of 100 lead objects."}), 400

    creator = User.query.filter_by(role=Role.ADMIN.value, status="active").order_by(User.id).first()
    if not creator:
        return jsonify({"error": "No active admin user is configured."}), 500

    created = 0
    duplicates = 0
    duplicate_details = []
    errors = []
    for row_number, row in enumerate(rows, start=1):
        name = str(row.get("full_name", "")).strip()
        phone = clean_phone(row.get("phone", ""))
        if not name or not re.fullmatch(r"\+?[0-9]{8,15}", phone):
            errors.append({"row": row_number, "error": "Name and valid phone are required."})
            continue
        existing_lead = find_duplicate(phone, row.get("email"))
        if existing_lead:
            duplicates += 1
            duplicate_details.append({"name": name, "phone": phone, "lead_id": existing_lead.lead_id})
            continue

        property_record = None
        listing_id = str(row.get("listing_id", "")).strip()
        property_name = str(row.get("property_name", "")).strip()
        if listing_id:
            property_record = Property.query.filter_by(property_id=listing_id).first()
            if not property_record:
                property_record = Property(
                    property_id=listing_id,
                    property_name=property_name or listing_id,
                    property_type=str(row.get("property_type", "")).strip(),
                    location=str(row.get("location", "")).strip(),
                    price=clean_price(row.get("budget", "")),
                    availability_status="Available",
                    created_by=creator.id,
                )
                db.session.add(property_record)
                db.session.flush()

        status = LEGACY_STATUS_MAP.get(str(row.get("status", LeadStatus.NEW.value)).strip(), str(row.get("status", LeadStatus.NEW.value)).strip())
        if status not in STATUS_VALUES:
            status = LeadStatus.NEW.value
        lead = Lead(
            lead_id=next_lead_id(),
            full_name=name,
            phone=phone,
            email=str(row.get("email", "")).strip() or None,
            source=str(row.get("source", "99Acres")).strip()[:30] or "99Acres",
            property_id=property_record.id if property_record else None,
            property_name=property_name,
            property_type=str(row.get("property_type", "")).strip(),
            location=str(row.get("location", "")).strip(),
            budget=str(row.get("budget", "")).strip(),
            status=status,
            priority=Priority.MEDIUM.value,
            notes=str(row.get("notes", "")).strip(),
            created_by=creator.id,
            last_contact_date=parse_date(row.get("date")),
        )
        db.session.add(lead)
        db.session.flush()
        log_activity(lead.id, creator.id, "Google Sheet Import", "Imported from Google Sheet")
        created += 1

    db.session.commit()
    return jsonify({"created": created, "duplicates": duplicates, "duplicate_details": duplicate_details, "errors": errors}), 200


@app.errorhandler(413)
def too_large(_):
    return "Uploaded file is too large. Maximum size is 25MB.", 413


with app.app_context():
    db.create_all()
    ensure_import_columns()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False, use_reloader=False)
