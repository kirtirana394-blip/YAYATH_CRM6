from datetime import datetime, date, time, timezone
from enum import Enum
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash


db = SQLAlchemy()


class Role(str, Enum):
    ADMIN = "admin"
    MANAGER = "manager"
    SALES_EMPLOYEE = "sales_employee"


class LeadStatus(str, Enum):
    NEW = "New"
    CONTACTED = "Contacted"
    INTERESTED = "Interested"
    FOLLOW_UP_REQUIRED = "Follow-up Required"
    SITE_VISIT_SCHEDULED = "Site Visit Scheduled"
    SITE_VISIT_DONE = "Site Visit Done"
    NEGOTIATION = "Negotiation"
    DEAL_CLOSED = "Deal Closed"
    DISQUALIFIED = "Disqualified"


class Priority(str, Enum):
    HIGH = "High"
    MEDIUM = "Medium"
    LOW = "Low"


class User(db.Model):
    __tablename__ = "profiles"
    id = db.Column(db.Integer, primary_key=True)
    full_name = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(255), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(30), nullable=False, default=Role.SALES_EMPLOYEE.value, index=True)
    phone = db.Column(db.String(30))
    status = db.Column(db.String(20), nullable=False, default="active")
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)


class Property(db.Model):
    __tablename__ = "properties"
    id = db.Column(db.Integer, primary_key=True)
    property_id = db.Column(db.String(40), unique=True, nullable=False, index=True)
    property_name = db.Column(db.String(200), nullable=False)
    property_type = db.Column(db.String(120))
    location = db.Column(db.String(200), index=True)
    address = db.Column(db.String(500))
    city = db.Column(db.String(100))
    size = db.Column(db.String(80))
    bhk = db.Column(db.String(40))
    furnishing = db.Column(db.String(80))
    price = db.Column(db.Numeric(14, 2))
    rent = db.Column(db.Numeric(14, 2))
    availability_status = db.Column(db.String(30), nullable=False, default="Available")
    description = db.Column(db.Text)
    created_by = db.Column(db.Integer, db.ForeignKey("profiles.id"))
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    deleted_at = db.Column(db.DateTime)


class Lead(db.Model):
    __tablename__ = "leads"
    id = db.Column(db.Integer, primary_key=True)
    lead_id = db.Column(db.String(40), unique=True, nullable=False, index=True)
    full_name = db.Column(db.String(160), nullable=False)
    phone = db.Column(db.String(30), nullable=False, index=True)
    alternate_phone = db.Column(db.String(30))
    email = db.Column(db.String(255), index=True)
    source = db.Column(db.String(30), nullable=False, default="99Acres", index=True)
    property_id = db.Column(db.Integer, db.ForeignKey("properties.id"), index=True)
    property_name = db.Column(db.String(200))
    property_type = db.Column(db.String(120))
    location = db.Column(db.String(200), index=True)
    city = db.Column(db.String(100))
    budget = db.Column(db.String(120))
    requirement = db.Column(db.Text)
    bhk = db.Column(db.String(40))
    size = db.Column(db.String(80))
    furnishing = db.Column(db.String(80))
    purpose = db.Column(db.String(50))
    status = db.Column(db.String(50), nullable=False, default=LeadStatus.NEW.value, index=True)
    priority = db.Column(db.String(20), nullable=False, default=Priority.MEDIUM.value, index=True)
    assigned_to = db.Column(db.Integer, db.ForeignKey("profiles.id"), index=True)
    last_contact_date = db.Column(db.Date)
    next_followup_date = db.Column(db.Date, index=True)
    next_followup_time = db.Column(db.Time)
    notes = db.Column(db.Text)
    created_by = db.Column(db.Integer, db.ForeignKey("profiles.id"))
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False, index=True)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    deleted_at = db.Column(db.DateTime)

    property = db.relationship("Property", foreign_keys=[property_id])
    assigned_user = db.relationship("User", foreign_keys=[assigned_to])
    creator = db.relationship("User", foreign_keys=[created_by])


class Followup(db.Model):
    __tablename__ = "followups"
    id = db.Column(db.Integer, primary_key=True)
    lead_id = db.Column(db.Integer, db.ForeignKey("leads.id"), nullable=False, index=True)
    assigned_to = db.Column(db.Integer, db.ForeignKey("profiles.id"), index=True)
    action_type = db.Column(db.String(40), nullable=False)
    followup_date = db.Column(db.Date, nullable=False, index=True)
    followup_time = db.Column(db.Time)
    status = db.Column(db.String(30), nullable=False, default="Pending", index=True)
    reminder = db.Column(db.String(50))
    notes = db.Column(db.Text)
    created_by = db.Column(db.Integer, db.ForeignKey("profiles.id"))
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    lead = db.relationship("Lead", backref=db.backref("followups", lazy=True))


class Task(db.Model):
    __tablename__ = "tasks"
    id = db.Column(db.Integer, primary_key=True)
    lead_id = db.Column(db.Integer, db.ForeignKey("leads.id"), index=True)
    title = db.Column(db.String(200), nullable=False)
    task_type = db.Column(db.String(60))
    description = db.Column(db.Text)
    assigned_to = db.Column(db.Integer, db.ForeignKey("profiles.id"), index=True)
    due_date = db.Column(db.Date, nullable=False, index=True)
    due_time = db.Column(db.Time)
    priority = db.Column(db.String(20), default=Priority.MEDIUM.value)
    status = db.Column(db.String(30), nullable=False, default="Pending", index=True)
    created_by = db.Column(db.Integer, db.ForeignKey("profiles.id"))
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    lead = db.relationship("Lead", backref=db.backref("tasks", lazy=True))


class LeadNote(db.Model):
    __tablename__ = "lead_notes"
    id = db.Column(db.Integer, primary_key=True)
    lead_id = db.Column(db.Integer, db.ForeignKey("leads.id"), nullable=False, index=True)
    note = db.Column(db.Text, nullable=False)
    created_by = db.Column(db.Integer, db.ForeignKey("profiles.id"))
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    lead = db.relationship("Lead", backref=db.backref("lead_notes", lazy=True, order_by="LeadNote.created_at.desc()"))


class ActivityLog(db.Model):
    __tablename__ = "activity_logs"
    id = db.Column(db.Integer, primary_key=True)
    lead_id = db.Column(db.Integer, db.ForeignKey("leads.id"), nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey("profiles.id"), index=True)
    activity_type = db.Column(db.String(80), nullable=False)
    description = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False, index=True)
    lead = db.relationship("Lead", backref=db.backref("activities", lazy=True, order_by="ActivityLog.created_at.desc()"))


class ImportHistory(db.Model):
    __tablename__ = "import_history"
    id = db.Column(db.Integer, primary_key=True)
    file_name = db.Column(db.String(255), nullable=False)
    uploaded_by = db.Column(db.Integer, db.ForeignKey("profiles.id"))
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    total_records = db.Column(db.Integer, default=0)
    imported = db.Column(db.Integer, default=0)
    updated = db.Column(db.Integer, default=0)
    duplicates = db.Column(db.Integer, default=0)
    errors = db.Column(db.Integer, default=0)


def utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)
