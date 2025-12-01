import pandas as pd
import requests
from bs4 import BeautifulSoup
import time
import threading
import json
import os
import csv
from urllib.parse import urljoin, urlparse
import re
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options
from selenium.common.exceptions import TimeoutException, NoSuchElementException
import logging
from database import db, OutreachData, OutreachConfig
from datetime import datetime
from suppression_utils import filter_urls_by_suppression
import os
import uuid

class OutreachBot:
    def __init__(self):
        self.running = False
        self.extract_emails_during_outreach = False
        self.stats = {
            'urls_processed': 0,
            'forms_submitted': 0,
            'forms_found': 0,
            'errors': 0,
            'emails_extracted': 0,
            'current_url': '',
            'status': 'Idle',
            'target_count': 0,
            'run_mode': 'continuous'
        }
        self.config = self.load_config()
        self.visited_urls = self.load_visited_urls()
        self.suppression_list = self.load_suppression_list()
        self.target_url_count = 0
        self.run_mode = 'continuous'
        
    def load_config(self):
        try:
            from flask import has_app_context
            if has_app_context():
                from database import OutreachConfig
                default_config = OutreachConfig.query.filter_by(is_default=True).first()
                if default_config:
                    return default_config.get_config_data()
        except:
            pass
        return {
            'first_name': '',
            'last_name': '',
            'email': '',
            'message': '',
            'delay_between_requests': 3,
            'custom_fields': []
        }

    def save_config(self, config, app=None):
        try:
            if app:
                with app.app_context():
                    from database import OutreachConfig, db
                    existing = OutreachConfig.query.filter_by(is_default=True).first()
                    if existing:
                        existing.set_config_data(config)
                        existing.updated_at = datetime.utcnow()
                    else:
                        new_config = OutreachConfig(is_default=True)
                        new_config.set_config_data(config)
                        db.session.add(new_config)
                    db.session.commit()
                    self.config = config
            else:
                from flask import current_app
                with current_app.app_context():
                    from database import OutreachConfig, db
                    existing = OutreachConfig.query.filter_by(is_default=True).first()
                    if existing:
                        existing.set_config_data(config)
                        existing.updated_at = datetime.utcnow()
                    else:
                        new_config = OutreachConfig(is_default=True)
                        new_config.set_config_data(config)
                        db.session.add(new_config)
                    db.session.commit()
                    self.config = config
        except Exception as e:
            print(f"Error saving config: {e}")
    
    def load_visited_urls(self):
        if os.path.exists('visited.csv'):
            df = pd.read_csv('visited.csv')
            return set(df['url'].tolist()) if 'url' in df.columns else set()
        return set()
    
    def save_visited_url(self, url, status, form_found, form_submitted):
        file_exists = os.path.exists('visited.csv')
        with open('visited.csv', 'a', newline='') as f:
            writer = csv.writer(f)
            if not file_exists:
                writer.writerow(['url', 'status', 'form_found', 'form_submitted', 'timestamp'])
            writer.writerow([url, status, form_found, form_submitted, time.strftime('%Y-%m-%d %H:%M:%S')])
    
    def load_suppression_list(self):
        if os.path.exists('suppression.csv'):
            df = pd.read_csv('suppression.csv')
            return set(df['url'].tolist()) if 'url' in df.columns else set()
        return set()
    
    def save_suppression_list(self, urls):
        with open('suppression.csv', 'w', newline='') as f:
            writer = csv.writer(f)
            writer.writerow(['url'])
            for url in urls:
                writer.writerow([url])
    
    def add_to_suppression(self, urls):
        if isinstance(urls, str):
            urls = [url.strip() for url in urls.split('\n') if url.strip()]
        
        new_urls = set(urls) - self.suppression_list
        self.suppression_list.update(new_urls)
        self.save_suppression_list(self.suppression_list)
        return len(new_urls)
    
    def remove_from_suppression(self, url):
        if url in self.suppression_list:
            self.suppression_list.remove(url)
            self.save_suppression_list(self.suppression_list)
            return True
        return False
    
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
        options.add_argument('--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36')
        options.add_argument('--disable-blink-features=AutomationControlled')
        options.add_experimental_option('excludeSwitches', ['enable-automation'])
        options.add_experimental_option('useAutomationExtension', False)
        
        driver = webdriver.Chrome(options=options)
        driver.set_page_load_timeout(45)
        driver.implicitly_wait(10)
        
        return driver
    
    def clean_url(self, url):
        if url.startswith('http%3A//'):
            url = url.replace('http%3A//', 'http://')
        if url.startswith('https%3A//'):
            url = url.replace('https%3A//', 'https://')
        if not url.startswith(('http://', 'https://')):
            url = 'https://' + url
        return url
    
    def find_contact_page(self, driver, base_url):
        contact_routes = ['/contact', '/contact.html', '/contact-us', '/contact-us.html', '/get-in-touch', '/reach-out', '/contact-form', '/contact.php']
        
        for route in contact_routes:
            try:
                contact_url = urljoin(base_url, route)
                driver.get(contact_url)
                WebDriverWait(driver, 10).until(EC.presence_of_element_located((By.TAG_NAME, "body")))
                
                if self.has_contact_form(driver):
                    return contact_url
                
                form_link = self.find_form_links_on_page(driver)
                if form_link:
                    driver.get(form_link)
                    WebDriverWait(driver, 10).until(EC.presence_of_element_located((By.TAG_NAME, "body")))
                    if self.has_contact_form(driver):
                        return form_link
                    
            except Exception as e:
                continue
        
        try:
            driver.get(base_url)
            WebDriverWait(driver, 10).until(EC.presence_of_element_located((By.TAG_NAME, "body")))
            
            if self.has_contact_form(driver):
                return base_url
            
            page_source = driver.page_source.lower()
            soup = BeautifulSoup(page_source, 'html.parser')
            
            contact_links = []
            for link in soup.find_all('a', href=True):
                href = link['href'].lower()
                text = link.get_text().lower()
                if any(word in href or word in text for word in ['contact', 'get-in-touch', 'reach-out', 'form']):
                    full_url = urljoin(base_url, link['href'])
                    if full_url not in contact_links:
                        contact_links.append(full_url)
            
            for contact_url in contact_links[:5]:
                try:
                    driver.get(contact_url)
                    WebDriverWait(driver, 10).until(EC.presence_of_element_located((By.TAG_NAME, "body")))
                    
                    if self.has_contact_form(driver):
                        return contact_url
                    
                    form_link = self.find_form_links_on_page(driver)
                    if form_link:
                        driver.get(form_link)
                        WebDriverWait(driver, 10).until(EC.presence_of_element_located((By.TAG_NAME, "body")))
                        if self.has_contact_form(driver):
                            return form_link
                except Exception as e:
                    continue
                    
        except Exception as e:
            pass
        
        return None
    
    def find_form_links_on_page(self, driver):
        try:
            soup = BeautifulSoup(driver.page_source, 'html.parser')
            form_keywords = ['form.html', 'contact-form', 'contact_form', 'contactform', 'inquiry', 'message-form', 'get-quote', 'quote-form']
            
            for link in soup.find_all('a', href=True):
                href = link['href'].lower()
                text = link.get_text().lower()
                
                if any(keyword in href or keyword in text for keyword in form_keywords):
                    full_url = urljoin(driver.current_url, link['href'])
                    return full_url
            
            buttons = driver.find_elements(By.TAG_NAME, 'button')
            for button in buttons:
                button_text = button.text.lower()
                if any(word in button_text for word in ['contact', 'form', 'message', 'inquiry']):
                    try:
                        button.click()
                        time.sleep(2)
                        if self.has_contact_form(driver):
                            return driver.current_url
                    except:
                        continue
            
        except Exception as e:
            pass
        return None
    
    def has_contact_form(self, driver):
        try:
            form_elements = driver.find_elements(By.TAG_NAME, 'form')
            for form in form_elements:
                inputs = form.find_elements(By.TAG_NAME, 'input')
                textareas = form.find_elements(By.TAG_NAME, 'textarea')
                
                has_name = False
                has_email = False
                has_message = False
                
                for inp in inputs:
                    input_type = inp.get_attribute('type')
                    input_name = inp.get_attribute('name') or ''
                    input_placeholder = inp.get_attribute('placeholder') or ''
                    input_id = inp.get_attribute('id') or ''
                    
                    field_identifier = (input_name + input_placeholder + input_id).lower()
                    
                    if input_type == 'email' or 'email' in field_identifier:
                        has_email = True
                    elif input_type in ['text', 'name'] or input_type is None:
                        if any(keyword in field_identifier for keyword in ['name', 'first', 'last']):
                            has_name = True
                
                for textarea in textareas:
                    textarea_name = textarea.get_attribute('name') or ''
                    textarea_placeholder = textarea.get_attribute('placeholder') or ''
                    textarea_id = textarea.get_attribute('id') or ''
                    field_identifier = (textarea_name + textarea_placeholder + textarea_id).lower()
                    if any(keyword in field_identifier for keyword in ['message', 'comment', 'description', 'inquiry', 'details']):
                        has_message = True
                
                if has_email and (has_name or has_message):
                    return True
        except:
            pass
        return False
    
    def fill_contact_form(self, driver, custom_config=None):
        config_to_use = custom_config or self.config
        
        try:
            WebDriverWait(driver, 10).until(EC.presence_of_element_located((By.TAG_NAME, "form")))
            forms = driver.find_elements(By.TAG_NAME, 'form')
            
            for form in forms:
                if not self.has_contact_form_in_element(form):
                    continue
                
                try:
                    driver.execute_script("arguments[0].scrollIntoView({behavior: 'smooth', block: 'center'});", form)
                    time.sleep(1)
                    
                    inputs = form.find_elements(By.TAG_NAME, 'input')
                    textareas = form.find_elements(By.TAG_NAME, 'textarea')
                    selects = form.find_elements(By.TAG_NAME, 'select')
                    
                    for inp in inputs:
                        try:
                            input_type = inp.get_attribute('type')
                            input_name = inp.get_attribute('name') or ''
                            input_placeholder = inp.get_attribute('placeholder') or ''
                            input_id = inp.get_attribute('id') or ''
                            
                            field_identifier = (input_name + input_placeholder + input_id).lower()
                            
                            if input_type == 'email' or 'email' in field_identifier:
                                driver.execute_script("arguments[0].focus();", inp)
                                inp.clear()
                                inp.send_keys(config_to_use.get('email', ''))
                            elif input_type in ['text', 'name'] or input_type is None:
                                if 'first' in field_identifier and 'name' in field_identifier:
                                    driver.execute_script("arguments[0].focus();", inp)
                                    inp.clear()
                                    inp.send_keys(config_to_use.get('first_name', ''))
                                elif 'last' in field_identifier and 'name' in field_identifier:
                                    driver.execute_script("arguments[0].focus();", inp)
                                    inp.clear()
                                    inp.send_keys(config_to_use.get('last_name', ''))
                                elif 'name' in field_identifier and 'first' not in field_identifier and 'last' not in field_identifier:
                                    full_name = f"{config_to_use.get('first_name', '')} {config_to_use.get('last_name', '')}".strip()
                                    driver.execute_script("arguments[0].focus();", inp)
                                    inp.clear()
                                    inp.send_keys(full_name)
                                elif any(keyword in field_identifier for keyword in ['subject', 'title']):
                                    subject_value = config_to_use.get('subject', 'Business Inquiry')
                                    driver.execute_script("arguments[0].focus();", inp)
                                    inp.clear()
                                    inp.send_keys(subject_value)
                                elif 'phone' in field_identifier:
                                    phone_value = config_to_use.get('phone', '')
                                    if phone_value:
                                        driver.execute_script("arguments[0].focus();", inp)
                                        inp.clear()
                                        inp.send_keys(phone_value)
                                elif 'company' in field_identifier:
                                    company_value = config_to_use.get('company', '')
                                    if company_value:
                                        driver.execute_script("arguments[0].focus();", inp)
                                        inp.clear()
                                        inp.send_keys(company_value)
                                
                                for custom_field in config_to_use.get('custom_fields', []):
                                    if custom_field.get('field_name', '').lower() in field_identifier:
                                        driver.execute_script("arguments[0].focus();", inp)
                                        inp.clear()
                                        inp.send_keys(custom_field.get('field_value', ''))
                                        break
                                        
                        except Exception as e:
                            continue
                    
                    for textarea in textareas:
                        try:
                            textarea_name = textarea.get_attribute('name') or ''
                            textarea_placeholder = textarea.get_attribute('placeholder') or ''
                            textarea_id = textarea.get_attribute('id') or ''
                            
                            field_identifier = (textarea_name + textarea_placeholder + textarea_id).lower()
                            
                            if any(keyword in field_identifier for keyword in ['message', 'comment', 'description', 'inquiry', 'details']):
                                driver.execute_script("arguments[0].focus();", textarea)
                                textarea.clear()
                                textarea.send_keys(config_to_use.get('message', ''))
                        except Exception as e:
                            continue
                    
                    submit_buttons = form.find_elements(By.XPATH, ".//input[@type='submit'] | .//button[@type='submit'] | .//button[contains(translate(text(), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'submit')] | .//input[contains(translate(@value, 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'submit')] | .//button[contains(translate(text(), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'send')] | .//input[contains(translate(@value, 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'send')] | .//button[contains(translate(text(), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'contact')]")
                    
                    if submit_buttons:
                        try:
                            submit_btn = submit_buttons[0]
                            driver.execute_script("arguments[0].scrollIntoView({behavior: 'smooth', block: 'center'});", submit_btn)
                            time.sleep(1)
                            
                            if submit_btn.is_enabled() and submit_btn.is_displayed():
                                driver.execute_script("arguments[0].click();", submit_btn)
                                time.sleep(5)
                                return True
                        except Exception as e:
                            try:
                                submit_btn.click()
                                time.sleep(5)
                                return True
                            except:
                                continue
                    
                except Exception as e:
                    continue
                
        except Exception as e:
            return False
        
        return False
    
    def has_contact_form_in_element(self, form_element):
        try:
            inputs = form_element.find_elements(By.TAG_NAME, 'input')
            textareas = form_element.find_elements(By.TAG_NAME, 'textarea')
            
            has_name = False
            has_email = False
            has_message = False
            
            for inp in inputs:
                input_type = inp.get_attribute('type')
                input_name = inp.get_attribute('name') or ''
                input_placeholder = inp.get_attribute('placeholder') or ''
                input_id = inp.get_attribute('id') or ''
                
                field_identifier = (input_name + input_placeholder + input_id).lower()
                
                if input_type == 'email' or 'email' in field_identifier:
                    has_email = True
                elif any(keyword in field_identifier for keyword in ['name', 'first', 'last']):
                    has_name = True
            
            for textarea in textareas:
                textarea_name = textarea.get_attribute('name') or ''
                textarea_placeholder = textarea.get_attribute('placeholder') or ''
                textarea_id = textarea.get_attribute('id') or ''
                field_identifier = (textarea_name + textarea_placeholder + textarea_id).lower()
                if any(keyword in field_identifier for keyword in ['message', 'comment', 'description']):
                    has_message = True
            
            return has_email and (has_name or has_message)
        except:
            return False
            
    def save_screenshot(self, driver, url, form_submitted=False):
        try:
            screenshots_dir = 'static/screenshots'
            os.makedirs(screenshots_dir, exist_ok=True)
            
            screenshot_filename = f"{uuid.uuid4().hex}_{int(time.time())}.png"
            screenshot_path = os.path.join(screenshots_dir, screenshot_filename)
            
            driver.save_screenshot(screenshot_path)
            return screenshot_path
        except Exception as e:
            print(f"Error saving screenshot: {e}")
            return None

    def process_urls(self, selected_urls=None, execution_mode='automatic', custom_config=None, app=None):
        self.running = True
        self.stats['status'] = 'Running'
        
        if app is None:
            self.stats['status'] = 'Error: No app context provided'
            self.running = False
            return
        
        with app.app_context():
            try:
                if selected_urls:
                    selected_urls_int = [int(url_id) for url_id in selected_urls]
                    outreach_records = OutreachData.query.filter(
                        OutreachData.id.in_(selected_urls_int),
                        OutreachData.status.in_(['pending', 'error', 'no_form_found', 'form_found_not_submitted'])
                    ).all()
                    urls_to_process = [(record.url, record.id) for record in outreach_records]
                else:
                    outreach_records = OutreachData.query.filter(
                        OutreachData.status.in_(['pending', 'error', 'no_form_found', 'form_found_not_submitted'])
                    ).all()
                    urls_to_process = [(record.url, record.id) for record in outreach_records]
            except Exception as e:
                self.stats['status'] = f'Error loading URLs: {str(e)}'
                self.running = False
                return
            
            if not urls_to_process:
                self.stats['status'] = 'No URLs to process'
                self.running = False
                return
            
            urls_to_process = [(url, uid) for url, uid in urls_to_process if not self.is_url_suppressed_check(url)]
            
            if not urls_to_process:
                self.stats['status'] = 'All URLs are suppressed'
                self.running = False
                return
            
            driver = None
            processed_count = 0
            
            try:
                driver = self.setup_driver()
                
                for url, record_id in urls_to_process:
                    if not self.running:
                        self.stats['status'] = 'Stopped by user'
                        break
                    
                    try:
                        outreach_record = OutreachData.query.get(record_id)
                        if not outreach_record:
                            continue
                        
                        cleaned_url = self.clean_url(url)
                        
                        if cleaned_url in self.visited_urls and outreach_record.status == 'completed':
                            continue
                        
                        self.stats['current_url'] = cleaned_url
                        
                        outreach_record.status = 'processing'
                        outreach_record.execution_mode = execution_mode
                        if custom_config:
                            outreach_record.set_config_used(custom_config)
                        else:
                            outreach_record.set_config_used(self.config)
                        db.session.commit()
                        
                        if self.extract_emails_during_outreach:
                            try:
                                emails_found = self.extract_and_save_emails(driver, cleaned_url, app)
                                if emails_found > 0:
                                    self.stats['emails_extracted'] = self.stats.get('emails_extracted', 0) + emails_found
                            except Exception as email_error:
                                print(f"Email extraction failed for {cleaned_url}: {email_error}")
                        
                        contact_page = None
                        try:
                            contact_page = self.find_contact_page(driver, cleaned_url)
                        except Exception as find_error:
                            print(f"Error finding contact page for {cleaned_url}: {find_error}")
                            outreach_record.status = 'error'
                            outreach_record.error_message = f'Contact page search failed: {str(find_error)}'
                            outreach_record.form_found = False
                            outreach_record.form_submitted = False
                            screenshot_path = self.save_screenshot(driver, cleaned_url, False)
                            if screenshot_path:
                                outreach_record.screenshot_path = screenshot_path
                            db.session.commit()
                            self.stats['errors'] += 1
                            processed_count += 1
                            self.stats['urls_processed'] += 1
                            self.visited_urls.add(cleaned_url)
                            self.save_visited_url(cleaned_url, 'error', False, False)
                            time.sleep(self.config.get('delay_between_requests', 3))
                            continue
                        
                        if contact_page:
                            if self.extract_emails_during_outreach:
                                try:
                                    emails_found = self.extract_and_save_emails(driver, contact_page, app)
                                    if emails_found > 0:
                                        self.stats['emails_extracted'] = self.stats.get('emails_extracted', 0) + emails_found
                                except Exception as email_error:
                                    print(f"Email extraction failed for contact page {contact_page}: {email_error}")
                            
                            self.stats['forms_found'] += 1
                            config_to_use = custom_config if execution_mode == 'dynamic' else self.config
                            
                            form_submitted = False
                            try:
                                form_submitted = self.fill_contact_form(driver, config_to_use)
                            except Exception as form_error:
                                print(f"Form filling failed for {cleaned_url}: {form_error}")
                            
                            screenshot_path = self.save_screenshot(driver, cleaned_url, form_submitted)
                            if screenshot_path:
                                outreach_record.screenshot_path = screenshot_path
                            
                            if form_submitted:
                                self.stats['forms_submitted'] += 1
                                outreach_record.status = 'completed'
                                outreach_record.form_found = True
                                outreach_record.form_submitted = True
                                self.save_visited_url(cleaned_url, 'success', True, True)
                            else:
                                outreach_record.status = 'form_found_not_submitted'
                                outreach_record.form_found = True
                                outreach_record.form_submitted = False
                                outreach_record.error_message = 'Form found but submission failed'
                                self.save_visited_url(cleaned_url, 'form_found_not_submitted', True, False)
                        else:
                            screenshot_path = self.save_screenshot(driver, cleaned_url, False)
                            if screenshot_path:
                                outreach_record.screenshot_path = screenshot_path
                            
                            outreach_record.status = 'no_form_found'
                            outreach_record.form_found = False
                            outreach_record.form_submitted = False
                            outreach_record.error_message = 'No contact form found on the website'
                            self.save_visited_url(cleaned_url, 'no_form_found', False, False)
                        
                        self.visited_urls.add(cleaned_url)
                        processed_count += 1
                        self.stats['urls_processed'] += 1
                        db.session.commit()
                        
                    except Exception as e:
                        self.stats['errors'] += 1
                        print(f"Error processing {url}: {str(e)}")
                        try:
                            outreach_record = OutreachData.query.get(record_id)
                            if outreach_record:
                                screenshot_path = self.save_screenshot(driver, url, False)
                                if screenshot_path:
                                    outreach_record.screenshot_path = screenshot_path
                                
                                outreach_record.status = 'error'
                                outreach_record.error_message = f'Processing error: {str(e)}'
                                outreach_record.form_found = False
                                outreach_record.form_submitted = False
                                db.session.commit()
                        except Exception as db_error:
                            print(f"Database error: {db_error}")
                        
                        self.save_visited_url(url, f'error: {str(e)}', False, False)
                        self.visited_urls.add(url)
                        processed_count += 1
                        self.stats['urls_processed'] += 1
                    
                    if self.run_mode == 'limited' and processed_count >= self.target_url_count:
                        self.stats['status'] = f'Completed {processed_count} URLs (target reached)'
                        break
                    
                    delay = self.config.get('delay_between_requests', 3)
                    time.sleep(delay)
            
            except Exception as e:
                self.stats['status'] = f'Critical error: {str(e)}'
                self.stats['errors'] += 1
                print(f"Critical error in process_urls: {str(e)}")
            finally:
                if driver:
                    try:
                        driver.quit()
                    except Exception as quit_error:
                        print(f"Error quitting driver: {quit_error}")
                
                self.running = False
                if self.stats['status'] == 'Running':
                    self.stats['status'] = f'Completed - Processed {processed_count} URLs'
                self.stats['current_url'] = ''

    def is_url_suppressed_check(self, url):
        from suppression_utils import is_url_suppressed
        return is_url_suppressed(url)

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

    def extract_and_save_emails(self, driver, url, app):
        try:
            page_source = driver.page_source
            emails = self.extract_emails_from_text(page_source)
            
            if emails:
                with app.app_context():
                    from database import ExtractedEmail
                    existing = ExtractedEmail.query.filter_by(url=url).first()
                    
                    if existing:
                        existing.set_emails(emails)
                        existing.status = 'success'
                        existing.error_message = None
                        existing.created_at = datetime.utcnow()
                    else:
                        email_record = ExtractedEmail(url=url, status='success')
                        email_record.set_emails(emails)
                        db.session.add(email_record)
                    
                    db.session.commit()
                    return len(emails)
        except Exception as e:
            pass
        return 0

    def start_bot(self, run_mode='continuous', target_count=0, selected_urls=None, execution_mode='automatic', custom_config=None, app=None, extract_emails=False):
        if not self.running:
            self.run_mode = run_mode
            self.target_url_count = target_count
            self.extract_emails_during_outreach = extract_emails
            self.stats = {
                'urls_processed': 0,
                'forms_submitted': 0,
                'forms_found': 0,
                'errors': 0,
                'emails_extracted': 0,
                'current_url': '',
                'status': 'Starting...',
                'target_count': target_count if run_mode == 'limited' else 0,
                'run_mode': run_mode
            }
            thread = threading.Thread(target=self.process_urls, args=(selected_urls, execution_mode, custom_config, app))
            thread.daemon = True
            thread.start()
            return True
        return False
    
    def stop_bot(self):
        if self.running:
            self.running = False
            self.stats['status'] = 'Stopping...'
            return True
        return False