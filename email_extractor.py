import re
import threading
import time
from urllib.parse import urljoin
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from bs4 import BeautifulSoup
from database import db, ExtractedEmail
from datetime import datetime

class EmailExtractor:
    def __init__(self):
        self.running = False
        self.stats = {
            'urls_processed': 0,
            'emails_found': 0,
            'errors': 0,
            'current_url': '',
            'status': 'Idle'
        }
        
    def setup_driver(self):
        options = Options()
        options.add_argument('--headless')
        options.add_argument('--enable-unsafe-swiftshader')
        options.add_argument('--no-sandbox')
        options.add_argument('--disable-dev-shm-usage')
        options.add_argument('--disable-gpu')
        options.add_argument('--window-size=1920,1080')
        options.add_argument('--disable-web-security')
        options.add_argument('--disable-features=VizDisplayCompositor')
        options.add_argument('--disable-extensions')
        options.add_argument('--disable-plugins')
        options.add_argument('--disable-images')
        options.add_argument('--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36')
        
        driver = webdriver.Chrome(options=options)
        driver.set_page_load_timeout(30)
        driver.implicitly_wait(10)
        return driver
    
    def clean_url(self, url):
        if not url.startswith(('http://', 'https://')):
            url = 'https://' + url
        return url
    
    def extract_emails_from_text(self, text):
        email_pattern = r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b'
        emails = re.findall(email_pattern, text)
        
        invalid_patterns = [
            r'.*\.(png|jpg|jpeg|gif|svg|css|js)$',
            r'.*example\.(com|org|net)',
            r'.*@(sentry\.io|domain\.com)',
            r'^(no-?reply|noreply)',
        ]
        
        valid_emails = []
        for email in emails:
            email = email.lower().strip()
            if not any(re.match(pattern, email) for pattern in invalid_patterns):
                valid_emails.append(email)
        
        return list(set(valid_emails))
    
    def find_contact_page(self, driver, base_url):
        contact_routes = [
            '/contact', '/contact-us', '/contact.html', '/get-in-touch', 
            '/reach-out', '/about', '/about-us', '/support', '/help'
        ]
        
        for route in contact_routes:
            try:
                contact_url = urljoin(base_url, route)
                driver.get(contact_url)
                WebDriverWait(driver, 10).until(EC.presence_of_element_located((By.TAG_NAME, "body")))
                return contact_url
            except:
                continue
        
        try:
            driver.get(base_url)
            WebDriverWait(driver, 10).until(EC.presence_of_element_located((By.TAG_NAME, "body")))
            
            soup = BeautifulSoup(driver.page_source, 'html.parser')
            contact_links = []
            
            for link in soup.find_all('a', href=True):
                href = link['href'].lower()
                text = link.get_text().lower()
                if any(word in href or word in text for word in ['contact', 'about', 'support', 'help', 'reach']):
                    full_url = urljoin(base_url, link['href'])
                    if full_url not in contact_links:
                        contact_links.append(full_url)
            
            for contact_url in contact_links[:3]:
                try:
                    driver.get(contact_url)
                    WebDriverWait(driver, 10).until(EC.presence_of_element_located((By.TAG_NAME, "body")))
                    return contact_url
                except:
                    continue
        except:
            pass
        
        return base_url
    
    def extract_email_from_url(self, driver, url):
        try:
            cleaned_url = self.clean_url(url)
            contact_page = self.find_contact_page(driver, cleaned_url)
            
            if contact_page:
                driver.get(contact_page)
                WebDriverWait(driver, 10).until(EC.presence_of_element_located((By.TAG_NAME, "body")))
            
            page_source = driver.page_source
            emails = self.extract_emails_from_text(page_source)
            
            if not emails:
                try:
                    mailto_links = driver.find_elements(By.CSS_SELECTOR, 'a[href^="mailto:"]')
                    for link in mailto_links:
                        href = link.get_attribute('href')
                        if href and 'mailto:' in href:
                            email = href.replace('mailto:', '').split('?')[0]
                            emails.extend(self.extract_emails_from_text(email))
                except:
                    pass
            
            return list(set(emails))[:5]
            
        except Exception as e:
            raise Exception(f"Error extracting email: {str(e)}")
    
    def process_urls(self, urls, app):
        self.running = True
        self.stats['status'] = 'Running'
        
        driver = None
        try:
            driver = self.setup_driver()
            
            with app.app_context():
                for url in urls:
                    if not self.running:
                        break
                    
                    self.stats['current_url'] = url
                    
                    try:
                        emails = self.extract_email_from_url(driver, url)
                        
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
                    
                    time.sleep(2)
        
        except Exception as e:
            self.stats['status'] = f'Critical error: {str(e)}'
        finally:
            if driver:
                try:
                    driver.quit()
                except:
                    pass
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
                'status': 'Starting...'
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