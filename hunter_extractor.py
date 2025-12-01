import requests
import threading
import time
import logging
from urllib.parse import urlparse
from database import db, ExtractedEmail
from datetime import datetime

# Configure logging
logger = logging.getLogger(__name__)

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
        """Extract clean domain from URL"""
        if not url.startswith(('http://', 'https://')):
            url = 'https://' + url
        parsed = urlparse(url)
        domain = parsed.netloc or parsed.path
        domain = domain.replace('www.', '')
        logger.debug(f"Extracted domain: {domain} from {url}")
        return domain
    
    def search_domain_emails(self, domain):
        """Search for emails using Hunter.io API"""
        endpoint = f'{self.base_url}/domain-search'
        params = {
            'domain': domain,
            'api_key': self.api_key,
            'limit': 100
        }
        
        try:
            logger.info(f"Searching Hunter.io for emails on domain: {domain}")
            response = requests.get(endpoint, params=params, timeout=30)
            response.raise_for_status()
            data = response.json()
            
            if data.get('data') and data['data'].get('emails'):
                emails = []
                for email_data in data['data']['emails']:
                    email = email_data.get('value')
                    if email:
                        emails.append(email)
                logger.info(f"Found {len(emails)} emails for {domain}")
                return emails[:10]
            else:
                logger.warning(f"No emails found for domain: {domain}")
            return []
        except requests.exceptions.HTTPError as e:
            if e.response.status_code == 401:
                logger.error("Hunter.io API authentication failed - Invalid API key")
                raise Exception("Invalid Hunter.io API key")
            elif e.response.status_code == 429:
                logger.error("Hunter.io API rate limit exceeded")
                raise Exception("Hunter.io rate limit exceeded. Please try again later.")
            else:
                try:
                    error_data = e.response.json()
                    if 'errors' in error_data:
                        error_msg = error_data['errors'][0].get('details', str(e))
                        logger.error(f"Hunter API error for {domain}: {error_msg}")
                        raise Exception(f"Hunter API error: {error_msg}")
                except:
                    pass
                logger.error(f"Hunter API HTTP error: {str(e)}")
                raise Exception(f"Hunter API error: {str(e)}")
        except requests.exceptions.Timeout:
            logger.error(f"Timeout connecting to Hunter.io for {domain}")
            raise Exception("Hunter.io API timeout")
        except requests.exceptions.RequestException as e:
            logger.error(f"Request error for {domain}: {str(e)}")
            raise Exception(f"Hunter API error: {str(e)}")
    
    def process_urls(self, urls, app):
        """Process URLs using Hunter.io API with logging"""
        self.running = True
        self.stats['status'] = 'Running'
        logger.info(f"Starting Hunter.io extraction for {len(urls)} URLs")
        
        with app.app_context():
            for url in urls:
                if not self.running:
                    logger.info("Extraction stopped by user")
                    break
                
                self.stats['current_url'] = url
                logger.info(f"Processing URL {self.stats['urls_processed'] + 1}/{len(urls)}: {url}")
                
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
                    error_msg = str(e)
                    logger.error(f"Error processing {url}: {error_msg}")
                    try:
                        existing = ExtractedEmail.query.filter_by(url=url).first()
                        if existing:
                            existing.status = 'error'
                            existing.error_message = error_msg
                            existing.created_at = datetime.utcnow()
                        else:
                            email_record = ExtractedEmail(
                                url=url,
                                status='error',
                                error_message=error_msg
                            )
                            email_record.set_emails([])
                            db.session.add(email_record)
                        db.session.commit()
                        logger.debug(f"Saved error to database for {url}")
                    except Exception as db_error:
                        logger.error(f"Failed to save error to database: {str(db_error)}")
                        db.session.rollback()
                
                time.sleep(1)
        
        self.running = False
        self.stats['status'] = 'Completed'
        self.stats['current_url'] = ''
        logger.info(f"Hunter extraction completed. Processed: {self.stats['urls_processed']}, Found: {self.stats['emails_found']}, Errors: {self.stats['errors']}")
    
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