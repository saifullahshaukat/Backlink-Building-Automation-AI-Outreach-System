import csv
from urllib.parse import urlparse
import re
from io import StringIO

def normalize_url(url):
    if not url:
        return ""
    
    url = url.strip()
    
    if not url.startswith(('http://', 'https://')):
        url = 'https://' + url
    
    parsed = urlparse(url)
    domain = parsed.netloc.lower()
    
    if domain.startswith('www.'):
        domain = domain[4:]
    
    parts = domain.split('.')
    if len(parts) >= 2:
        domain = '.'.join(parts[-2:])
    
    path = parsed.path.rstrip('/')
    if not path:
        path = '/'
    
    return f"{domain}{path}"

def find_duplicates(primary_csv, secondary_csv):
    primary_data = []
    secondary_urls = set()
    
    try:
        primary_reader = csv.DictReader(StringIO(primary_csv))
        for row in primary_reader:
            if 'URL' in row and row['URL']:
                primary_data.append(row)
    except Exception as e:
        raise ValueError(f"Error reading primary CSV: {str(e)}")
    
    try:
        secondary_reader = csv.DictReader(StringIO(secondary_csv))
        for row in secondary_reader:
            if 'URL' in row and row['URL']:
                normalized = normalize_url(row['URL'])
                if normalized:
                    secondary_urls.add(normalized)
    except Exception as e:
        raise ValueError(f"Error reading secondary CSV: {str(e)}")
    
    cleaned_data = []
    duplicate_urls = []
    removed_count = 0
    
    for row in primary_data:
        normalized_primary = normalize_url(row['URL'])
        if normalized_primary not in secondary_urls:
            cleaned_data.append(row)
        else:
            duplicate_urls.append(row)
            removed_count += 1
    
    return cleaned_data, removed_count, duplicate_urls

def generate_clean_csv(data):
    if not data:
        return ""
    
    output = StringIO()
    fieldnames = data[0].keys()
    writer = csv.DictWriter(output, fieldnames=fieldnames)
    writer.writeheader()
    writer.writerows(data)
    
    output.seek(0)
    return output.getvalue()