import requests
import datetime
from config import Config

class AhrefsAPI:
    def __init__(self, token=None):
        self.token = token or Config.AHREFS_TOKEN
        self.base_url = Config.AHREFS_BASE_URL
        self.headers = {
            "Authorization": f"Bearer {self.token}",
            "Accept": "application/json"
        }
    
    def _get(self, path, **params):
        try:
            url = f"{self.base_url}/{path}"
            response = requests.get(url, headers=self.headers, params=params, timeout=30)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            return {"error": str(e)}
    
    def get_metrics(self, target, date=None):
        if not date:
            date = datetime.date.today().isoformat()
        return self._get("metrics", target=target, date=date)
    
    def get_domain_rating(self, target, date=None):
        if not date:
            date = datetime.date.today().isoformat()
        return self._get("domain-rating", target=target, date=date)
    
    def get_backlinks_stats(self, target, date=None):
        if not date:
            date = datetime.date.today().isoformat()
        return self._get("backlinks-stats", target=target, date=date)
    
    def get_metrics_history(self, target, date_from=None, date_to=None):
        params = {'target': target}
        if date_from:
            params['date_from'] = date_from
        if date_to:
            params['date_to'] = date_to
        return self._get("metrics-history", **params)
    
    def get_historical_snapshots(self, target, dates=None):
        if dates is None:
            dates = ['2020-01-01', '2021-01-01', '2022-01-01', '2023-01-01', '2024-01-01']
        
        historical_data = {}
        for date in dates:
            try:
                data = self._get("metrics", target=target, date=date)
                historical_data[date] = data
            except Exception as e:
                historical_data[date] = {"error": str(e)}
        
        return historical_data
    
    def get_comprehensive_data(self, target, operations, date_ranges=None):
        result = {}
        
        if 'metrics' in operations:
            result['current_metrics'] = self.get_metrics(target)
        
        if 'domain_rating' in operations:
            result['domain_rating'] = self.get_domain_rating(target)
        
        if 'backlinks_stats' in operations:
            result['backlinks_stats'] = self.get_backlinks_stats(target)
        
        if 'history_metrics' in operations:
            if date_ranges and len(date_ranges) > 0:
                result['historical_metrics'] = {}
                for i, date_range in enumerate(date_ranges):
                    range_key = f"range_{i+1}_{date_range.get('from', 'start')}_{date_range.get('to', 'end')}"
                    try:
                        data = self.get_metrics_history(
                            target, 
                            date_range.get('from'), 
                            date_range.get('to')
                        )
                        result['historical_metrics'][range_key] = data
                    except Exception as e:
                        result['historical_metrics'][range_key] = {"error": str(e)}
            else:
                result['historical_snapshots'] = self.get_historical_snapshots(target)
        
        return result
    
    def get_organic_keywords(self, target, date=None, limit=10):
        if not date:
            yesterday = (datetime.date.today() - datetime.timedelta(days=1)).isoformat()
            date = yesterday
        return self._get("organic-keywords", target=target, date=date, select="keyword,sum_traffic", limit=limit)

    def get_metrics_by_country(self, target, date=None):
        if not date:
            date = datetime.date.today().isoformat()
        return self._get("metrics-by-country", target=target, mode="domain", date=date, select="country,org_traffic")

    def get_comprehensive_data(self, target, operations, date_ranges=None):
        result = {}
        
        if 'metrics' in operations:
            result['current_metrics'] = self.get_metrics(target)
        
        if 'domain_rating' in operations:
            result['domain_rating'] = self.get_domain_rating(target)
        
        if 'backlinks_stats' in operations:
            result['backlinks_stats'] = self.get_backlinks_stats(target)
        
        if 'top_keywords' in operations:
            result['top_keywords'] = self.get_organic_keywords(target)
        
        if 'country_metrics' in operations:
            result['country_metrics'] = self.get_metrics_by_country(target)
        
        if 'history_metrics' in operations:
            if date_ranges and len(date_ranges) > 0:
                result['historical_metrics'] = {}
                for i, date_range in enumerate(date_ranges):
                    range_key = f"range_{i+1}_{date_range.get('from', 'start')}_{date_range.get('to', 'end')}"
                    try:
                        data = self.get_metrics_history(
                            target, 
                            date_range.get('from'), 
                            date_range.get('to')
                        )
                        result['historical_metrics'][range_key] = data
                    except Exception as e:
                        result['historical_metrics'][range_key] = {"error": str(e)}
            else:
                result['historical_snapshots'] = self.get_historical_snapshots(target)
        
        return result

    def normalize_url(self, url):
        url = url.strip()
        
        if url.startswith('http%3A//') or url.startswith('https%3A//'):
            import urllib.parse
            url = urllib.parse.unquote(url)
        
        if not url.startswith(('http://', 'https://')):
            if url.startswith('www.'):
                url = 'https://' + url
            else:
                url = 'https://' + url
        
        return url

    def get_url_variations(self, url, www_mode):
        normalized_url = self.normalize_url(url)
        
        base_url = normalized_url.replace('https://', '').replace('http://', '')
        if base_url.startswith('www.'):
            base_domain = base_url[4:]
            www_version = base_url
        else:
            base_domain = base_url
            www_version = 'www.' + base_url
        
        if www_mode == 'both':
            return [
                'https://' + base_domain,
                'https://' + www_version
            ]
        elif www_mode == 'with_www':
            return ['https://' + www_version]
        elif www_mode == 'without_www':
            return ['https://' + base_domain]
        else:
            return [normalized_url]
        
    def clean_url(self, url):
        url = url.strip()
        if not url.startswith(('http://', 'https://')):
            if '.' in url and not url.startswith('www.'):
                url = 'www.' + url
        return url