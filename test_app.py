import os
import tempfile
from io import BytesIO
import pytest
from app import app
from models import db, User, Lead, Property

@pytest.fixture
def client():
    dbfile = tempfile.NamedTemporaryFile(delete=False, suffix='.db'); dbfile.close()
    app.config.update(TESTING=True, SQLALCHEMY_DATABASE_URI='sqlite:///' + dbfile.name, SECRET_KEY='test')
    with app.app_context():
        db.drop_all(); db.create_all()
        u=User(full_name='Admin',email='admin@test.local',role='admin'); u.set_password('pass'); db.session.add(u); db.session.commit()
    with app.test_client() as c:
        yield c
    os.unlink(dbfile.name)

def login(c):
    return c.post('/login', data={'email':'admin@test.local','password':'pass'}, follow_redirects=True)

def test_login_and_add_lead(client):
    r=login(client); assert b'Dashboard' in r.data
    r=client.post('/leads/new', data={'full_name':'Test Lead','phone':'9876543210'}, follow_redirects=True)
    assert b'Test Lead' in r.data
    with app.app_context():
        lead=Lead.query.filter_by(full_name='Test Lead').first(); assert lead.source=='99Acres'

def test_export_csv(client):
    login(client); client.post('/leads/new', data={'full_name':'Export Lead','phone':'9876543211'}, follow_redirects=True)
    r=client.get('/export/leads?format=csv'); assert r.status_code==200; assert b'99Acres' in r.data

def test_send_lead_email_via_smtp(client, monkeypatch):
    sent = {}

    class FakeSMTP:
        def __init__(self, host, port, timeout):
            sent['connection'] = (host, port, timeout)

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc_value, traceback):
            return False

        def starttls(self):
            sent['tls'] = True

        def login(self, username, password):
            sent['login'] = (username, password)

        def send_message(self, message):
            sent['message'] = message

    monkeypatch.setattr('app.smtplib.SMTP', FakeSMTP)
    for key, value in {
        'SMTP_HOST': 'smtp.test.local', 'SMTP_PORT': '587', 'SMTP_USERNAME': 'sender@test.local',
        'SMTP_PASSWORD': 'secret', 'SMTP_USE_TLS': 'true', 'MAIL_FROM': 'sender@test.local',
    }.items():
        monkeypatch.setenv(key, value)

    login(client)
    client.post('/leads/new', data={'full_name':'Email Lead','phone':'9876543223','email':'lead@test.local'})
    with app.app_context():
        lead = Lead.query.filter_by(full_name='Email Lead').one()

    response = client.post('/leads/%s/send-email' % lead.id, data={'subject':'Welcome', 'body':'Hello from CRM'}, follow_redirects=True)
    assert response.status_code == 200
    assert b'Email sent to lead@test.local.' in response.data
    assert sent['connection'] == ('smtp.test.local', 587, 20)
    assert sent['tls'] is True
    assert sent['login'] == ('sender@test.local', 'secret')
    assert sent['message']['To'] == 'lead@test.local'
    assert sent['message']['Subject'] == 'Welcome'
    assert sent['message'].get_content().strip() == 'Hello from CRM'

def test_send_email_page_opens(client):
    login(client)
    client.post('/leads/new', data={'full_name':'Compose Lead','phone':'9876543224','email':'compose@test.local'})
    with app.app_context():
        lead = Lead.query.filter_by(full_name='Compose Lead').one()
    response = client.get('/leads/%s/send-email' % lead.id)
    assert response.status_code == 200
    assert b'Send Email' in response.data
    assert b'compose@test.local' in response.data

def test_google_sheet_sync_creates_lead_and_skips_duplicate(client, monkeypatch):
    monkeypatch.setenv('GOOGLE_SHEET_SYNC_TOKEN', 'test-sync-token')
    payload = {
        'date': '2026-07-21', 'full_name': 'Sheet Customer', 'phone': '91-8448919797',
        'listing_id': 'Z92871214', 'property_type': 'Ready to move Office Space',
        'budget': 'Rs16.08 Lac', 'location': 'Electronic city',
        'property_name': 'Test Project', 'source': 'Dealer', 'notes': 'Call tomorrow',
    }
    response = client.post('/api/google-sheet/leads', json=payload, headers={'X-CRM-Sync-Token': 'test-sync-token'})
    assert response.status_code == 200
    assert response.json['created'] == 1
    duplicate = client.post('/api/google-sheet/leads', json=payload, headers={'X-CRM-Sync-Token': 'test-sync-token'})
    assert duplicate.status_code == 200
    assert duplicate.json['duplicates'] == 1
    with app.app_context():
        lead = Lead.query.filter_by(phone='918448919797').one()
        assert lead.property.property_id == 'Z92871214'
        assert lead.notes == 'Call tomorrow'

def test_direct_and_referral_statuses_are_available(client):
    login(client)
    response = client.get('/leads/new')
    assert b'>Direct<' in response.data
    assert b'>Referral<' in response.data

def test_delete_multiple_leads(client):
    login(client)
    client.post('/leads/new', data={'full_name':'Delete One','phone':'9876543221'})
    client.post('/leads/new', data={'full_name':'Delete Two','phone':'9876543222'})
    with app.app_context():
        lead_ids = [lead.id for lead in Lead.query.order_by(Lead.id).all()]

    response = client.post('/leads/delete', data={'lead_ids': lead_ids}, follow_redirects=True)
    assert response.status_code == 200
    assert b'moved to Recently Deleted' in response.data
    with app.app_context():
        assert Lead.query.filter(Lead.deleted_at.is_(None)).count() == 0

def test_import_saves_all_rows_and_updates_dashboard(client):
    login(client)
    csv_data = b'full_name,phone,status\nImported One,9876543212,New\nImported Two,9876543213,Interested\nImported Three,9876543214,New\n'
    preview = client.post('/import', data={'file': (BytesIO(csv_data), 'leads.csv')}, follow_redirects=False)
    assert preview.status_code == 302
    confirm = client.post('/import/preview', data={'full_name': 'full_name', 'phone': 'phone', 'status': 'status'}, follow_redirects=True)
    assert confirm.status_code == 200
    assert b'Imported Three' in confirm.data
    dashboard = client.get('/')
    assert b'data-kpi="total">3' in dashboard.data
    with app.app_context():
        assert Lead.query.count() == 3

def test_import_redirects_to_dashboard_with_imported_leads(client):
    login(client)
    csv_data = b'full_name,phone,status\nDashboard Lead,9876543225,Interested\n'
    client.post('/import', data={'file': (BytesIO(csv_data), 'dashboard-lead.csv')}, follow_redirects=False)
    response = client.post('/import/preview', data={}, follow_redirects=True)
    assert response.status_code == 200
    assert b'Dashboard Lead' in response.data
    assert b'data-kpi="total">1' in response.data

def test_import_auto_maps_common_headers(client):
    login(client)
    csv_data = b'Name,Mobile,Email Address,Lead Status\nSheet Customer,9876543215,customer@example.com,Contacted\n'
    preview = client.post('/import', data={'file': (BytesIO(csv_data), 'customer-leads.csv')}, follow_redirects=False)
    assert preview.status_code == 302
    confirm = client.post('/import/preview', data={}, follow_redirects=True)
    assert confirm.status_code == 200
    with app.app_context():
        lead = Lead.query.filter_by(full_name='Sheet Customer').one()
        assert lead.phone == '9876543215'
        assert lead.status == 'Contacted'

def test_imported_source_is_visible_on_dashboard(client):
    login(client)
    csv_data = b'Name,Mobile,Source\nOther Source Lead,9876543220,Website\n'
    client.post('/import', data={'file': (BytesIO(csv_data), 'website-leads.csv')}, follow_redirects=False)
    response = client.post('/import/preview', data={}, follow_redirects=True)
    assert response.status_code == 200
    assert b'Other Source Lead' in client.get('/').data
    with app.app_context():
        lead = Lead.query.filter_by(full_name='Other Source Lead').one()
        assert lead.source == 'Website'

def test_import_auto_maps_indian_csv_headers(client):
    login(client)
    csv_data = b'Customer Name,Mobile No.,Remarks\nHindi Sheet Customer,9876543216,Interested buyer\n'
    client.post('/import', data={'file': (BytesIO(csv_data), 'indian-leads.csv')}, follow_redirects=False)
    response = client.post('/import/preview', data={}, follow_redirects=True)
    assert response.status_code == 200
    with app.app_context():
        lead = Lead.query.filter_by(full_name='Hindi Sheet Customer').one()
        assert lead.phone == '9876543216'
        assert lead.notes == 'Interested buyer'

def test_import_listing_sheet_saves_properties(client):
    login(client)
    csv_data = b'Listing id,Proptype,Locality,Society,City,Size,Price,Listing status\nY94007016,Ready to move,Sector 48,JMID IT Mega,Gurgaon,5684 sqft,Rs3.98 Lac,Active\n'
    client.post('/import', data={'file': (BytesIO(csv_data), 'listing-sheet.csv')}, follow_redirects=False)
    response = client.post('/import/preview', data={}, follow_redirects=True)
    assert response.status_code == 200
    with app.app_context():
        property_record = Property.query.filter_by(property_id='Y94007016').one()
        assert property_record.city == 'Gurgaon'
        assert str(property_record.price) == '3.98'
        listing_lead = Lead.query.filter_by(property_id=property_record.id).one()
        assert listing_lead.full_name == 'JMID IT Mega'
