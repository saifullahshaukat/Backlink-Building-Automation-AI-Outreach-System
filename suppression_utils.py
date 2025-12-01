from database import db, SuppressionList, ScrapedData, URL, URLData, OutreachData
from urllib.parse import urlparse
import re

def normalize_url(url):
    if not url:
        return url
    
    url = url.strip()
    if not url.startswith(('http://', 'https://')):
        if url.startswith('www.'):
            url = 'https://' + url
        else:
            url = 'https://' + url
    
    try:
        parsed = urlparse(url)
        domain = parsed.netloc.lower()
        if domain.startswith('www.'):
            domain = domain[4:]
        
        parts = domain.split('.')
        if len(parts) >= 2:
            domain = '.'.join(parts[-2:])
        
        return domain
    except:
        clean = url.lower().replace('http://', '').replace('https://', '').replace('www.', '')
        parts = clean.split('/')[0].split('.')
        if len(parts) >= 2:
            return '.'.join(parts[-2:])
        return clean.split('/')[0]

def is_url_suppressed(url):
    if not url:
        return False
    
    normalized_url = normalize_url(url)
    suppressed_domains = get_suppressed_domains()
    
    for suppressed_domain in suppressed_domains:
        if normalized_url == suppressed_domain or suppressed_domain in normalized_url or normalized_url in suppressed_domain:
            return True
    
    return False

def filter_urls_by_suppression(urls):
    if not urls:
        return []
    
    suppressed_domains = get_suppressed_domains()
    filtered_urls = []
    
    for url in urls:
        normalized_url = normalize_url(url)
        is_suppressed = False
        
        for suppressed_domain in suppressed_domains:
            if normalized_url == suppressed_domain or suppressed_domain in normalized_url or normalized_url in suppressed_domain:
                is_suppressed = True
                break
        
        if not is_suppressed:
            filtered_urls.append(url)
    
    return filtered_urls

def get_suppressed_domains():
    suppressed_urls = db.session.query(SuppressionList.url).all()
    suppressed_domains = set()
    
    for (suppressed_url,) in suppressed_urls:
        normalized_suppressed = normalize_url(suppressed_url)
        suppressed_domains.add(normalized_suppressed)
    
    return suppressed_domains

def bulk_check_suppression(urls):
    if not urls:
        return {}
    
    suppressed_domains = get_suppressed_domains()
    results = {}
    
    for url in urls:
        normalized_url = normalize_url(url)
        is_suppressed = False
        
        for suppressed_domain in suppressed_domains:
            if normalized_url == suppressed_domain or suppressed_domain in normalized_url or normalized_url in suppressed_domain:
                is_suppressed = True
                break
        
        results[url] = is_suppressed
    
    return results

def clean_url_before_storage(url):
    if not url:
        return url
    
    url = url.strip()
    if not url.startswith(('http://', 'https://')):
        url = 'https://' + url
    
    return url

def get_urls_from_source(source, search_term=None):
    urls = []
    
    if source.startswith('scraper'):
        query = ScrapedData.query
        if source == 'scraper_adsy':
            query = query.filter_by(source='adsy')
        elif source == 'scraper_icopify':
            query = query.filter_by(source='icopify')
        
        if search_term:
            query = query.filter(ScrapedData.url.contains(search_term))
        
        records = query.all()
        urls = [record.url for record in records]
    
    elif source == 'ahrefs_urls':
        query = URL.query
        if search_term:
            query = query.filter(URL.url.contains(search_term))
        
        records = query.all()
        urls = [record.url for record in records]
    
    elif source == 'ahrefs_data':
        query = URLData.query.join(URL)
        if search_term:
            query = query.filter(URL.url.contains(search_term))
        
        records = query.all()
        urls = [record.url.url for record in records]
    
    elif source == 'outreach_data':
        query = OutreachData.query
        if search_term:
            query = query.filter(OutreachData.url.contains(search_term))
        
        records = query.all()
        urls = [record.url for record in records]
    
    return list(set(urls))

def get_suppression_stats():
    scraper_count = ScrapedData.query.count()
    ahrefs_count = URL.query.count()
    outreach_count = OutreachData.query.count()
    suppressed_count = SuppressionList.query.count()
    
    return {
        'scraper_count': scraper_count,
        'ahrefs_count': ahrefs_count,
        'outreach_count': outreach_count,
        'suppressed_count': suppressed_count
    }