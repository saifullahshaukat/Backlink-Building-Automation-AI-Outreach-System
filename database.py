from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
import json

db = SQLAlchemy()

class URL(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    url = db.Column(db.String(500), unique=True, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    def __repr__(self):
        return f'<URL {self.url}>'

class URLData(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    url_id = db.Column(db.Integer, db.ForeignKey('url.id'), nullable=False)
    
    current_metrics = db.Column(db.Text)
    domain_rating = db.Column(db.Text)
    backlinks_stats = db.Column(db.Text)
    historical_metrics = db.Column(db.Text)
    top_keywords = db.Column(db.Text)
    country_metrics = db.Column(db.Text)
    
    fetched_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    url = db.relationship('URL', backref=db.backref('data', lazy=True))
    
    def get_top_keywords(self):
        return json.loads(self.top_keywords) if self.top_keywords else None
    
    def set_top_keywords(self, data):
        self.top_keywords = json.dumps(data) if data else None
    
    def get_country_metrics(self):
        return json.loads(self.country_metrics) if self.country_metrics else None
    
    def set_country_metrics(self, data):
        self.country_metrics = json.dumps(data) if data else None
    
    def get_current_metrics(self):
        return json.loads(self.current_metrics) if self.current_metrics else None

    def set_current_metrics(self, data):
        self.current_metrics = json.dumps(data) if data else None

    def get_domain_rating(self):
        return json.loads(self.domain_rating) if self.domain_rating else None

    def set_domain_rating(self, data):
        self.domain_rating = json.dumps(data) if data else None

    def get_backlinks_stats(self):
        return json.loads(self.backlinks_stats) if self.backlinks_stats else None

    def set_backlinks_stats(self, data):
        self.backlinks_stats = json.dumps(data) if data else None

    def get_historical_metrics(self):
        return json.loads(self.historical_metrics) if self.historical_metrics else None

    def set_historical_metrics(self, data):
        self.historical_metrics = json.dumps(data) if data else None
    
    def get_historical_summary(self):
        historical_data = self.get_historical_metrics()
        if not historical_data:
            return None
        
        total_ranges = 0
        has_data = False
        
        for range_key, range_data in historical_data.items():
            if range_data and range_data.get('metrics'):
                total_ranges += 1
                if isinstance(range_data['metrics'], list) and len(range_data['metrics']) > 0:
                    has_data = True
        
        if not has_data:
            return None
        
        return {
            'total_ranges': total_ranges,
            'has_data': has_data
        }

    def get_country_summary(self):
        country_data = self.get_country_metrics()
        if not country_data or 'metrics' not in country_data:
            return None
        
        countries = country_data['metrics']
        total_traffic = sum(country.get('org_traffic', 0) for country in countries)
        
        if total_traffic == 0:
            return None
        
        significant_countries = []
        other_traffic = 0
        
        for country in countries:
            traffic = country.get('org_traffic', 0)
            percentage = (traffic / total_traffic) * 100
            
            if percentage >= 0.1:
                significant_countries.append({
                    'country': country.get('country', ''),
                    'traffic': traffic,
                    'percentage': round(percentage, 1)
                })
            else:
                other_traffic += traffic
        
        if other_traffic > 0:
            other_percentage = (other_traffic / total_traffic) * 100
            significant_countries.append({
                'country': 'Other',
                'traffic': other_traffic,
                'percentage': round(other_percentage, 1)
            })
        
        return {
            'countries': significant_countries[:10],
            'total_traffic': total_traffic
        }
    
    def get_all_data(self):
        return {
            'current_metrics': self.get_current_metrics(),
            'domain_rating': self.get_domain_rating(),
            'backlinks_stats': self.get_backlinks_stats(),
            'historical_metrics': self.get_historical_metrics(),
            'top_keywords': self.get_top_keywords(),
            'country_metrics': self.get_country_metrics()
        }

class ArchivedURLData(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    original_url_data_id = db.Column(db.Integer)
    url = db.Column(db.String(500), nullable=False)
    
    current_metrics = db.Column(db.Text)
    domain_rating = db.Column(db.Text)
    backlinks_stats = db.Column(db.Text)
    historical_metrics = db.Column(db.Text)
    top_keywords = db.Column(db.Text)
    country_metrics = db.Column(db.Text)
    
    original_fetched_at = db.Column(db.DateTime)
    archived_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    def get_top_keywords(self):
        return json.loads(self.top_keywords) if self.top_keywords else None
    
    def set_top_keywords(self, data):
        self.top_keywords = json.dumps(data) if data else None
    
    def get_country_metrics(self):
        return json.loads(self.country_metrics) if self.country_metrics else None
    
    def set_country_metrics(self, data):
        self.country_metrics = json.dumps(data) if data else None
    
    def get_current_metrics(self):
        return json.loads(self.current_metrics) if self.current_metrics else None

    def set_current_metrics(self, data):
        self.current_metrics = json.dumps(data) if data else None

    def get_domain_rating(self):
        return json.loads(self.domain_rating) if self.domain_rating else None

    def set_domain_rating(self, data):
        self.domain_rating = json.dumps(data) if data else None

    def get_backlinks_stats(self):
        return json.loads(self.backlinks_stats) if self.backlinks_stats else None

    def set_backlinks_stats(self, data):
        self.backlinks_stats = json.dumps(data) if data else None

    def get_historical_metrics(self):
        return json.loads(self.historical_metrics) if self.historical_metrics else None

    def set_historical_metrics(self, data):
        self.historical_metrics = json.dumps(data) if data else None
    
    def get_historical_summary(self):
        historical_data = self.get_historical_metrics()
        if not historical_data:
            return None
        
        total_ranges = 0
        has_data = False
        
        for range_key, range_data in historical_data.items():
            if range_data and range_data.get('metrics'):
                total_ranges += 1
                if isinstance(range_data['metrics'], list) and len(range_data['metrics']) > 0:
                    has_data = True
        
        if not has_data:
            return None
        
        return {
            'total_ranges': total_ranges,
            'has_data': has_data
        }

    def get_country_summary(self):
        country_data = self.get_country_metrics()
        if not country_data or 'metrics' not in country_data:
            return None
        
        countries = country_data['metrics']
        total_traffic = sum(country.get('org_traffic', 0) for country in countries)
        
        if total_traffic == 0:
            return None
        
        significant_countries = []
        other_traffic = 0
        
        for country in countries:
            traffic = country.get('org_traffic', 0)
            percentage = (traffic / total_traffic) * 100
            
            if percentage >= 0.1:
                significant_countries.append({
                    'country': country.get('country', ''),
                    'traffic': traffic,
                    'percentage': round(percentage, 1)
                })
            else:
                other_traffic += traffic
        
        if other_traffic > 0:
            other_percentage = (other_traffic / total_traffic) * 100
            significant_countries.append({
                'country': 'Other',
                'traffic': other_traffic,
                'percentage': round(other_percentage, 1)
            })
        
        return {
            'countries': significant_countries[:10],
            'total_traffic': total_traffic
        }
    
    def get_all_data(self):
        return {
            'current_metrics': self.get_current_metrics(),
            'domain_rating': self.get_domain_rating(),
            'backlinks_stats': self.get_backlinks_stats(),
            'historical_metrics': self.get_historical_metrics(),
            'top_keywords': self.get_top_keywords(),
            'country_metrics': self.get_country_metrics()
        }
    
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(120), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class ScrapedData(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    url = db.Column(db.String(500), nullable=False)
    source = db.Column(db.String(20), nullable=False)
    categories = db.Column(db.Text)
    language = db.Column(db.String(100))
    monthly_traffic = db.Column(db.String(50))
    ahrefs_traffic = db.Column(db.String(50))
    similarweb_traffic = db.Column(db.String(50))
    semrush_traffic = db.Column(db.String(50))
    ahrefs_dr = db.Column(db.String(10))
    moz_da = db.Column(db.String(10))
    referral_domains = db.Column(db.String(50))
    content_placement_price = db.Column(db.String(20))
    writing_placement_price = db.Column(db.String(20))
    semrush_as = db.Column(db.String(10))
    completion_rate = db.Column(db.String(10))
    link_lifetime = db.Column(db.String(10))
    tat_days = db.Column(db.String(10))
    link_type = db.Column(db.String(20))
    sponsored_required = db.Column(db.String(20))
    content_size = db.Column(db.String(10))
    spam_score = db.Column(db.String(10))
    description = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class ScrapingSession(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    source = db.Column(db.String(20), nullable=False)
    start_page = db.Column(db.Integer, nullable=False)
    pages_to_scrape = db.Column(db.Integer, nullable=False)
    current_page = db.Column(db.Integer, default=0)
    status = db.Column(db.String(20), default='pending')
    records_scraped = db.Column(db.Integer, default=0)
    started_at = db.Column(db.DateTime, default=datetime.utcnow)
    completed_at = db.Column(db.DateTime)
    error_message = db.Column(db.Text)

class OutreachData(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    url = db.Column(db.String(500), nullable=False)
    status = db.Column(db.String(50), nullable=False)
    form_found = db.Column(db.Boolean, default=False)
    form_submitted = db.Column(db.Boolean, default=False)
    error_message = db.Column(db.Text)
    config_used = db.Column(db.Text)
    execution_mode = db.Column(db.String(20), default='automatic')
    screenshot_path = db.Column(db.String(500))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    def get_config_used(self):
        return json.loads(self.config_used) if self.config_used else None
    
    def set_config_used(self, config_data):
        self.config_used = json.dumps(config_data) if config_data else None
        
class SuppressionList(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    url = db.Column(db.String(500), unique=True, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    reason = db.Column(db.String(200))
    
    def __repr__(self):
        return f'<Suppressed {self.url}>'
    
class OutreachConfig(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    config_data = db.Column(db.Text, nullable=False)
    is_default = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    def get_config_data(self):
        return json.loads(self.config_data) if self.config_data else {}
    
    def set_config_data(self, config_data):
        self.config_data = json.dumps(config_data) if config_data else "{}"

class ExtractedEmail(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    url = db.Column(db.String(500), nullable=False, unique=True)
    emails = db.Column(db.Text)
    status = db.Column(db.String(50), nullable=False)
    error_message = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    def get_emails(self):
        return json.loads(self.emails) if self.emails else []
    
    def set_emails(self, email_list):
        self.emails = json.dumps(email_list) if email_list else None
    
    def __repr__(self):
        return f'<ExtractedEmail {self.url}>'
    
class EmailOutreach(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(200), nullable=False)
    url = db.Column(db.String(500), nullable=False)
    subject = db.Column(db.String(500), nullable=False)
    message = db.Column(db.Text, nullable=False)
    status = db.Column(db.String(50), default='pending')
    sent_at = db.Column(db.DateTime)
    error_message = db.Column(db.Text)
    execution_mode = db.Column(db.String(20), default='automatic')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    def __repr__(self):
        return f'<EmailOutreach {self.email}>'

class EmailCredentials(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(200), unique=True, nullable=False)
    password = db.Column(db.String(500), nullable=False)
    smtp_server = db.Column(db.String(200), nullable=False)
    smtp_port = db.Column(db.Integer, nullable=False)
    is_default = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    def __repr__(self):
        return f'<EmailCredentials {self.email}>'

class EmailTemplate(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), unique=True, nullable=False)
    subject = db.Column(db.String(500), nullable=False)
    message = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    def __repr__(self):
        return f'<EmailTemplate {self.name}>'