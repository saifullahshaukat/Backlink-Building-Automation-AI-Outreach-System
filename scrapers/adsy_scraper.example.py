import requests
from bs4 import BeautifulSoup
import time
import re
from urllib.parse import urlparse

class AdsyScraper:
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        })
        
    def extract_domain(self, url):
        try:
            if not url.startswith(('http://', 'https://')):
                url = 'http://' + url
            parsed = urlparse(url)
            domain = parsed.netloc.lower()
            if domain.startswith('www.'):
                domain = domain[4:]
            return domain
        except:
            return None
    
    def login(self, email=None, password=None):
        """
        Login to Adsy platform
        
        Args:
            email (str): Your Adsy account email - REQUIRED
            password (str): Your Adsy account password - REQUIRED
            
        Returns:
            bool: True if login successful, False otherwise
            
        Usage:
            scraper = AdsyScraper()
            scraper.login(email='your-email@example.com', password='your-password')
        """
        if not email or not password:
            raise ValueError("Email and password are required for Adsy login")
            
        login_url = 'https://cp.adsy.com/login'
        
        try:
            response = self.session.get(login_url)
            soup = BeautifulSoup(response.content, 'html.parser')
            csrf_token = soup.find('input', {'name': '_csrf-frontend'})['value']
            
            login_data = {
                '_csrf-frontend': csrf_token,
                'LoginForm[email]': email,
                'LoginForm[password]': password,
                'LoginForm[rememberMe]': '0'
            }
            
            response = self.session.post(login_url, data=login_data)
            
            if response.status_code == 200 and 'marketer/platform' in response.url:
                return True
            else:
                return False
        except Exception as e:
            print(f"Login error: {e}")
            return False
    
    def clean_text(self, text):
        if not text:
            return ""
        return re.sub(r'\s+', ' ', text.strip())
    
    def extract_price(self, text, label):
        pattern = rf'{re.escape(label)}.*?\$(\d+\.?\d*)'
        match = re.search(pattern, text, re.DOTALL)
        return match.group(1) if match else ""
    
    def extract_number(self, text, label):
        pattern = rf'{re.escape(label)}.*?(\d{{1,3}}(?:,\d{{3}})*)'
        match = re.search(pattern, text, re.DOTALL)
        return match.group(1).replace(',', '') if match else ""
    
    def extract_percentage(self, text, label):
        pattern = rf'{re.escape(label)}.*?(\d+%)'
        match = re.search(pattern, text, re.DOTALL)
        return match.group(1) if match else ""
    
    def extract_domain_data(self, item_div):
        try:
            url_link = item_div.find('a', class_='link link-to-pub-url')
            if not url_link or 'Unlock URL' in item_div.get_text():
                return None
            
            url = url_link.get('href', '').replace('/marketer/platform/link?url=', '').replace('https%3A%2F%2F', 'https://').replace('%2F', '/')
            
            text_content = item_div.get_text()
            
            category_badges = item_div.find_all('span', class_='badge badge--category')
            categories = ', '.join([badge.get_text().strip() for badge in category_badges])
            
            language = ""
            for div in item_div.find_all('div'):
                if 'Language' in div.get_text() and 'English' in div.parent.get_text():
                    language = "English"
                    break
            
            ahrefs_traffic = self.extract_number(text_content, 'Ahrefs Organic Traffic')
            similarweb_traffic = self.extract_number(text_content, 'Similarweb Traffic')
            semrush_traffic = self.extract_number(text_content, 'SemRush Total Traffic')
            
            ahrefs_dr = self.extract_number(text_content, 'Ahrefs DR Range')
            referral_domains = self.extract_number(text_content, 'Referral Domains')
            
            content_placement = self.extract_price(text_content, 'Content placement')
            writing_placement = self.extract_price(text_content, 'Writing & Placement')
            
            moz_da = self.extract_number(text_content, 'Moz DA')
            semrush_as = self.extract_number(text_content, 'Semrush AS')
            
            completion_rate = self.extract_percentage(text_content, 'Completion rate')
            link_lifetime = self.extract_percentage(text_content, 'Avg lifetime of links')
            
            tat_match = re.search(r'TAT.*?(\d+)\s*days?', text_content, re.DOTALL)
            tat_days = tat_match.group(1) if tat_match else ""
            
            if 'Dofollow' in text_content:
                link_type = 'Dofollow'
            elif 'Nofollow' in text_content:
                link_type = 'Nofollow'
            else:
                link_type = ''
            
            if 'Marked "Sponsored by"' in text_content:
                if 'Yes / No' in text_content:
                    sponsored_required = 'Optional'
                elif 'Yes' in text_content:
                    sponsored_required = 'Yes'
                elif 'No' in text_content:
                    sponsored_required = 'No'
                else:
                    sponsored_required = ''
            else:
                sponsored_required = ''
            
            content_size_match = re.search(r'from (\d+) words?', text_content)
            content_size = content_size_match.group(1) if content_size_match else ""
            
            spam_score = self.extract_percentage(text_content, 'Spam Score')
            
            description = ""
            desc_div = item_div.find('div', style=re.compile('padding: 0px 20px 10px 10px'))
            if desc_div:
                desc_text = desc_div.get_text().strip()
                if desc_text and not desc_text.startswith('Mark site'):
                    lines = desc_text.split('\n')
                    for line in lines:
                        if line.strip() and not line.strip().startswith('Mark site'):
                            description = self.clean_text(line.strip())
                            break
            
            return {
                'URL': url,
                'Categories': categories,
                'Language': language,
                'Ahrefs_Traffic': ahrefs_traffic,
                'Similarweb_Traffic': similarweb_traffic,
                'SemRush_Traffic': semrush_traffic,
                'Ahrefs_DR': ahrefs_dr,
                'Referral_Domains': referral_domains,
                'Content_Placement_Price': content_placement,
                'Writing_Placement_Price': writing_placement,
                'Moz_DA': moz_da,
                'SemRush_AS': semrush_as,
                'Completion_Rate': completion_rate,
                'Link_Lifetime': link_lifetime,
                'TAT_Days': tat_days,
                'Link_Type': link_type,
                'Sponsored_Required': sponsored_required,
                'Content_Size': content_size,
                'Spam_Score': spam_score,
                'Description': description
            }
            
        except Exception as e:
            print(f"Error extracting data: {e}")
            return None
    
    def scrape_page(self, page_num):
        url = f'https://cp.adsy.com/marketer/platform/index?SiteSearch%5Bverified%5D=2&page={page_num}&per-page=100'
        
        try:
            response = self.session.get(url)
            soup = BeautifulSoup(response.content, 'html.parser')
            
            items = soup.find_all('div', class_='inv-item')
            page_data = []
            
            for item in items:
                domain_data = self.extract_domain_data(item)
                if domain_data:
                    page_data.append(domain_data)
            
            return page_data
            
        except Exception as e:
            print(f"Error scraping page {page_num}: {e}")
            return []
