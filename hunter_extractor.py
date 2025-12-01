import requests
import threading
import time
from urllib.parse import urlparse
from database import db, ExtractedEmail
from datetime import datetime

class HunterExtractor:
    def __init__(self, api_key):
        self.api_key = api_key
        self.base_url = 'https://api.hunter.io/v2'
        self.running = False
        self.stats = {
            'urls_processed': 0,
            'emails_found': 0,
            'errors': 0,
            'current_url': '',
            'status': 'Idle',
            'credits_used': 0
        }
    
    def extract_domain(self, url):
        if not url.startswith(('http://', 'https://')):
            url = 'https://' + url
        parsed = urlparse(url)
        domain = parsed.netloc or parsed.path
        domain = domain.replace('www.', '')
        return domain
    
    def search_domain_emails(self, domain):
        endpoint = f'{self.base_url}/domain-search'
        params = {
            'domain': domain,
            'api_key': self.api_key,
            'limit': 100
        }
        
        try:
            response = requests.get(endpoint, params=params, timeout=30)
            response.raise_for_status()
            data = response.json()
            
            if data.get('data') and data['data'].get('emails'):
                emails = []
                for email_data in data['data']['emails']:
                    email = email_data.get('value')
                    if email:
                        emails.append(email)
                return emails[:10]
            return []
        except requests.exceptions.RequestException as e:
            if hasattr(e.response, 'json'):
                error_data = e.response.json()
                if 'errors' in error_data:
                    error_msg = error_data['errors'][0].get('details', str(e))
                    raise Exception(f"Hunter API error: {error_msg}")
            raise Exception(f"Hunter API error: {str(e)}")
    
    def process_urls(self, urls, app):
        self.running = True
        self.stats['status'] = 'Running'
        
        with app.app_context():
            for url in urls:
                if not self.running:
                    break
                
                self.stats['current_url'] = url
                
                try:
                    domain = self.extract_domain(url)
                    emails = self.search_domain_emails(domain)
                    
                    existing = ExtractedEmail.query.filter_by(url=url).first()
                    
                    if emails:
                        if existing:
                            existing.set_emails(emails)
                            existing.status = 'success'
                            existing.error_message = None
                            existing.created_at = datetime.utcnow()
                        else:
                            email_record = ExtractedEmail(
                                url=url,
                                status='success'
                            )
                            email_record.set_emails(emails)
                            db.session.add(email_record)
                        
                        self.stats['emails_found'] += len(emails)

                    else:
                        if existing:
                            existing.status = 'no_email_found'
                            existing.set_emails([])
                            existing.error_message = None
                            existing.created_at = datetime.utcnow()
                        else:
                            email_record = ExtractedEmail(
                                url=url,
                                status='no_email_found'
                            )
                            email_record.set_emails([])
                            db.session.add(email_record)
                    
                    db.session.commit()
                    self.stats['urls_processed'] += 1
                    
                except Exception as e:
                    self.stats['errors'] += 1
                    try:
                        existing = ExtractedEmail.query.filter_by(url=url).first()
                        if existing:
                            existing.status = 'error'
                            existing.error_message = str(e)
                            existing.created_at = datetime.utcnow()
                        else:
                            email_record = ExtractedEmail(
                                url=url,
                                status='error',
                                error_message=str(e)
                            )
                            email_record.set_emails([])
                            db.session.add(email_record)
                        db.session.commit()
                    except:
                        pass
                
                time.sleep(1)
        
        self.running = False
        self.stats['status'] = 'Completed'
        self.stats['current_url'] = ''
    
    def start_extraction(self, urls, app):
        if not self.running:
            self.stats = {
                'urls_processed': 0,
                'emails_found': 0,
                'errors': 0,
                'current_url': '',
                'status': 'Starting...',
                'credits_used': len(urls)
            }
            thread = threading.Thread(target=self.process_urls, args=(urls, app))
            thread.daemon = True
            thread.start()
            return True
        return False
        
    def stop_extraction(self):
        if self.running:
            self.running = False
            self.stats['status'] = 'Stopping...'
            return True
        return False