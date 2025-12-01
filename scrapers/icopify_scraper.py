import requests
from bs4 import BeautifulSoup
import time
import re
from urllib.parse import urljoin, urlparse
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.common.exceptions import TimeoutException, NoSuchElementException, WebDriverException
from webdriver_manager.chrome import ChromeDriverManager
import logging

class IcopifyScraper:
    def __init__(self, start_page=1):
        self.base_url = "https://icopify.co"
        self.login_url = "https://icopify.co/login"
        self.project_url = "https://icopify.co/project/62309/publishers"
        self.driver = None
        self.current_page = start_page
        self.scraped_urls = set()
        self.login_attempts = 0
        self.max_login_attempts = 3
        self.driver_crashes = 0
        self.max_driver_crashes = 5
        
        logging.basicConfig(level=logging.INFO)
        self.logger = logging.getLogger(__name__)

    def is_driver_alive(self):
        try:
            self.driver.current_url
            return True
        except:
            return False

    def restart_driver_and_login(self):
        try:
            self.logger.warning(f"Driver crash detected. Restart attempt {self.driver_crashes + 1}")
            
            if self.driver:
                try:
                    self.driver.quit()
                except:
                    pass
            
            self.driver_crashes += 1
            
            if self.driver_crashes > self.max_driver_crashes:
                self.logger.error(f"Too many driver crashes: {self.driver_crashes}")
                return False
            
            time.sleep(5)
            
            if not self.setup_driver(headless=True):
                self.logger.error("Failed to restart driver")
                return False
            
            self.login_attempts = 0
            login_success = False
            
            while self.login_attempts < self.max_login_attempts and not login_success:
                login_success = self.login()
                if not login_success:
                    self.login_attempts += 1
                    time.sleep(10)
            
            if login_success:
                self.logger.info("Driver restarted and logged in successfully")
                return True
            else:
                self.logger.error("Failed to login after driver restart")
                return False
                
        except Exception as e:
            self.logger.error(f"Error restarting driver: {str(e)}")
            return False

    def safe_driver_action(self, action_func, *args, **kwargs):
        max_retries = 2
        retry_count = 0
        
        while retry_count < max_retries:
            try:
                if not self.is_driver_alive():
                    if not self.restart_driver_and_login():
                        return None
                
                result = action_func(*args, **kwargs)
                return result
                
            except Exception as e:
                self.logger.warning(f"Driver action failed (attempt {retry_count + 1}): {str(e)}")
                retry_count += 1
                
                if retry_count < max_retries:
                    time.sleep(3)
                else:
                    self.logger.error(f"All retry attempts failed for driver action")
                    return None
        
        return None
        
    def setup_driver(self, headless=True):
        try:
            chrome_options = Options()
            if headless:
                chrome_options.add_argument("--headless")
            chrome_options.add_argument("--no-sandbox")
            chrome_options.add_argument("--disable-dev-shm-usage")
            chrome_options.add_argument("--disable-gpu")
            chrome_options.add_argument("--window-size=1920,1080")
            chrome_options.add_argument("--disable-extensions")
            chrome_options.add_argument("--disable-blink-features=AutomationControlled")
            chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
            chrome_options.add_experimental_option('useAutomationExtension', False)
            chrome_options.add_argument("--user-agent=Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
            chrome_options.add_argument("--disable-web-security")
            chrome_options.add_argument("--allow-running-insecure-content")
            chrome_options.add_argument("--disable-logging")
            chrome_options.add_argument("--disable-notifications")
            chrome_options.add_argument("--disable-popup-blocking")
            chrome_options.add_argument("--remote-debugging-port=9222")
            chrome_options.add_argument("--disable-software-rasterizer")
            chrome_options.add_argument("--memory-pressure-off")
            
            prefs = {
                "profile.default_content_setting_values": {
                    "notifications": 2,
                    "geolocation": 2,
                }
            }
            chrome_options.add_experimental_option("prefs", prefs)
            
            try:
                service = Service(ChromeDriverManager().install())
            except Exception as e:
                self.logger.warning(f"ChromeDriver manager failed: {e}. Using system chromedriver...")
                service = Service()
            
            self.driver = webdriver.Chrome(service=service, options=chrome_options)
            self.driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
            self.driver.set_page_load_timeout(60)
            self.driver.implicitly_wait(10)
            self.logger.info("Chrome driver initialized successfully")
            return True
        except WebDriverException as e:
            self.logger.error(f"WebDriverException during setup: {str(e)}")
            return False
        except Exception as e:
            self.logger.error(f"Failed to initialize Chrome driver: {str(e)}")
            return False

    def login(self, username="AndrewAUSSEO", password="321Test890!"):
        try:
            self.logger.info("Attempting to login...")
            self.driver.get(self.login_url)
            self.logger.info(f"Navigated to login page: {self.driver.current_url}")
            time.sleep(8)
            
            email_field = None
            email_selectors = [
                (By.NAME, "email"),
                (By.ID, "Email"),
                (By.ID, "email"),
                (By.CSS_SELECTOR, "input[type='email']"),
                (By.CSS_SELECTOR, "input[name='email']"),
                (By.XPATH, "//input[@name='email' or @id='email' or @id='Email']")
            ]
            
            for selector_type, selector_value in email_selectors:
                try:
                    email_field = WebDriverWait(self.driver, 10).until(
                        EC.presence_of_element_located((selector_type, selector_value))
                    )
                    self.logger.info(f"Found email field using: {selector_type}={selector_value}")
                    break
                except TimeoutException:
                    continue
            
            if not email_field:
                self.logger.error("Could not find email field")
                return False
            
            password_field = None
            password_selectors = [
                (By.NAME, "password"),
                (By.ID, "password"),
                (By.ID, "Password"),
                (By.CSS_SELECTOR, "input[type='password']"),
                (By.CSS_SELECTOR, "input[name='password']"),
                (By.XPATH, "//input[@name='password' or @id='password' or @id='Password']")
            ]
            
            for selector_type, selector_value in password_selectors:
                try:
                    password_field = self.driver.find_element(selector_type, selector_value)
                    self.logger.info(f"Found password field using: {selector_type}={selector_value}")
                    break
                except NoSuchElementException:
                    continue
            
            if not password_field:
                self.logger.error("Could not find password field")
                return False
            
            email_field.clear()
            time.sleep(1)
            email_field.send_keys(username)
            self.logger.info(f"Entered username: {username}")
            time.sleep(2)
            
            password_field.clear()
            time.sleep(1)
            password_field.send_keys(password)
            self.logger.info("Entered password")
            time.sleep(2)
            
            submit_button = None
            submit_selectors = [
                (By.CSS_SELECTOR, "button[type='submit']"),
                (By.CSS_SELECTOR, "input[type='submit']"),
                (By.XPATH, "//button[@type='submit']"),
                (By.XPATH, "//input[@type='submit']"),
                (By.XPATH, "//button[contains(text(), 'Login') or contains(text(), 'Sign In')]"),
                (By.CLASS_NAME, "btn-primary")
            ]
            
            for selector_type, selector_value in submit_selectors:
                try:
                    submit_button = self.driver.find_element(selector_type, selector_value)
                    self.logger.info(f"Found submit button using: {selector_type}={selector_value}")
                    break
                except NoSuchElementException:
                    continue
            
            if not submit_button:
                self.logger.error("Could not find submit button")
                return False
            
            self.logger.info("Clicking submit button...")
            self.driver.execute_script("arguments[0].click();", submit_button)
            time.sleep(8)
            
            try:
                WebDriverWait(self.driver, 30).until(
                    lambda driver: driver.current_url != self.login_url
                )
                self.logger.info(f"Current URL after login: {self.driver.current_url}")
            except TimeoutException:
                self.logger.error("Login timeout - URL didn't change")
                return False
            
            if "login" in self.driver.current_url.lower():
                error_elements = self.driver.find_elements(By.CSS_SELECTOR, ".alert, .error, .invalid-feedback")
                for elem in error_elements:
                    if elem.is_displayed():
                        self.logger.error(f"Login error message: {elem.text}")
                self.logger.error("Login failed - still on login page")
                return False
            
            self.logger.info("Login successful")
            return True
            
        except TimeoutException:
            self.logger.error(f"Login timeout - current URL: {self.driver.current_url}")
            return False
        except Exception as e:
            self.logger.error(f"Login failed: {str(e)}")
            return False

    def extract_text_safe(self, element):
        try:
            return element.get_text(strip=True) if element else ""
        except:
            return ""

    def extract_number_from_text(self, text):
        try:
            numbers = re.findall(r'[\d,]+', text)
            if numbers:
                return numbers[0].replace(',', '')
            return ""
        except:
            return ""

    def clean_url(self, url):
        try:
            if not url:
                return ""
            url = url.strip()
            if not url.startswith(('http://', 'https://')):
                url = 'https://' + url
            parsed = urlparse(url)
            return f"{parsed.scheme}://{parsed.netloc}"
        except:
            return ""

    def extract_categories(self, row_soup):
        try:
            categories = []
            category_badges = row_soup.find_all('span', class_='badge badge-soft-primary')
            for badge in category_badges:
                cat_text = self.extract_text_safe(badge)
                if cat_text and cat_text not in categories:
                    categories.append(cat_text)
            return ', '.join(categories) if categories else ""
        except:
            return ""

    def extract_monthly_traffic(self, row_soup):
        try:
            traffic_cell = row_soup.find('td', class_='text-center align-middle')
            if traffic_cell and 'Monthly Traffic' in self.extract_text_safe(traffic_cell):
                traffic_span = traffic_cell.find('span', class_='font-weight-bold')
                if traffic_span:
                    return self.extract_number_from_text(self.extract_text_safe(traffic_span))
            return ""
        except:
            return ""

    def extract_ahrefs_dr(self, row_soup):
        try:
            cells = row_soup.find_all('td', class_='text-center align-middle')
            for cell in cells:
                cell_text = self.extract_text_safe(cell)
                if 'DR' in cell_text and 'Ahrefs' in str(cell):
                    dr_match = re.search(r'DR\s*(\d+)', cell_text)
                    if dr_match:
                        return dr_match.group(1)
            return ""
        except:
            return ""

    def extract_moz_da(self, row_soup):
        try:
            cells = row_soup.find_all('td', class_='text-center align-middle')
            for cell in cells:
                cell_text = self.extract_text_safe(cell)
                if 'DA' in cell_text:
                    da_match = re.search(r'DA\s*(\d+)', cell_text)
                    if da_match:
                        return da_match.group(1)
            return ""
        except:
            return ""

    def extract_language(self, row_soup):
        try:
            cells = row_soup.find_all('td', class_='text-center align-middle')
            for cell in cells:
                if cell.find('img') and 'flag' in str(cell):
                    spans = cell.find_all('span')
                    for span in spans:
                        text = self.extract_text_safe(span)
                        if text and text not in ['', 'M', 'DA'] and not text.isdigit():
                            return text
            return ""
        except:
            return ""

    def extract_website_url(self, row_soup):
        try:
            link = row_soup.find('a', href=True, target='_blank')
            if link:
                href = link.get('href', '')
                if href and not href.startswith('#') and 'javascript:' not in href:
                    return self.clean_url(href)
            
            domain_text = row_soup.find(text=lambda text: text and '.' in text and len(text.strip()) > 3)
            if domain_text:
                domain = domain_text.strip()
                if '.' in domain and not domain.startswith('.'):
                    return self.clean_url(domain)
            
            return ""
        except:
            return ""

    def scrape_page_data(self, page_num):
        def _scrape_page_internal():
            try:
                url = f"{self.project_url}?page={page_num}"
                self.logger.info(f"Scraping page {page_num}: {url}")
                
                self.driver.get(url)
                time.sleep(8)
                
                try:
                    WebDriverWait(self.driver, 30).until(
                        EC.presence_of_element_located((By.TAG_NAME, "table"))
                    )
                    self.logger.info("Table found on page")
                except TimeoutException:
                    self.logger.error("Table not found on page within timeout")
                    return []
                
                soup = BeautifulSoup(self.driver.page_source, 'html.parser')
                
                table = soup.find('table')
                if not table:
                    self.logger.error("No table found in page source")
                    return []
                
                tbody = table.find('tbody')
                if tbody:
                    rows = tbody.find_all('tr')
                else:
                    rows = table.find_all('tr')[1:]
                
                if not rows:
                    self.logger.warning("No data rows found in table")
                    return []
                
                self.logger.info(f"Found {len(rows)} rows to process")
                page_data = []
                
                for i, row in enumerate(rows):
                    try:
                        website_url = self.extract_website_url(row)
                        
                        if not website_url:
                            self.logger.debug(f"Row {i+1}: No website URL found, skipping")
                            continue
                        
                        if website_url in self.scraped_urls:
                            self.logger.debug(f"Duplicate URL skipped: {website_url}")
                            continue
                        
                        categories = self.extract_categories(row)
                        monthly_traffic = self.extract_monthly_traffic(row)
                        ahrefs_dr = self.extract_ahrefs_dr(row)
                        moz_da = self.extract_moz_da(row)
                        language = self.extract_language(row)
                        
                        data_row = {
                            'URL': website_url,
                            'CATEGORIES': categories,
                            'MONTHLY_TRAFFIC': monthly_traffic,
                            'AHREFS_DR': ahrefs_dr,
                            'MOZ_DA': moz_da,
                            'LANGUAGES': language
                        }
                        
                        page_data.append(data_row)
                        self.scraped_urls.add(website_url)
                        self.logger.debug(f"Row {i+1}: Extracted data for {website_url}")
                        
                    except Exception as e:
                        self.logger.error(f"Error processing row {i+1}: {str(e)}")
                        continue
                
                self.logger.info(f"Successfully extracted {len(page_data)} records from page {page_num}")
                return page_data
                
            except Exception as e:
                self.logger.error(f"Error scraping page {page_num}: {str(e)}")
                return []
        
        return self.safe_driver_action(_scrape_page_internal)

    def cleanup(self):
        if self.driver:
            try:
                self.driver.quit()
                self.logger.info("Driver cleanup completed")
            except Exception as e:
                self.logger.error(f"Error closing driver: {str(e)}")