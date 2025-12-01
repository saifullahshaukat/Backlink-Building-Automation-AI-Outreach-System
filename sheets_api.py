import requests
from datetime import datetime

class SheetsAPI:
    def __init__(self):
        self.api_url = "https://api.apispreadsheets.com/data/jjVzaCQ5TTbbWQ0r/"
        
    def format_ahrefs_data_for_sheets(self, url_data_record):
        url_obj = url_data_record.url
        
        current_metrics = url_data_record.get_current_metrics()
        domain_rating = url_data_record.get_domain_rating()
        backlinks_stats = url_data_record.get_backlinks_stats()
        top_keywords = url_data_record.get_top_keywords()
        country_summary = url_data_record.get_country_summary()
        historical_metrics = url_data_record.get_historical_metrics()
        
        org_keywords = ""
        org_traffic = ""
        traffic_value = ""
        if current_metrics and current_metrics.get('metrics'):
            metrics = current_metrics['metrics']
            org_keywords = str(metrics.get('org_keywords', '')) if metrics.get('org_keywords') else ""
            org_traffic = str(metrics.get('org_traffic', '')) if metrics.get('org_traffic') else ""
            traffic_value = f"${metrics.get('org_cost', '')}" if metrics.get('org_cost') else ""
        
        dr_display = ""
        if domain_rating and domain_rating.get('domain_rating'):
            dr_data = domain_rating['domain_rating']
            dr_score = dr_data.get('domain_rating', '')
            ahrefs_rank = dr_data.get('ahrefs_rank', '')
            if dr_score:
                dr_display = f"DR {dr_score}"
                if ahrefs_rank:
                    dr_display += f" (#{ahrefs_rank:,})"
        
        live_backlinks = ""
        referring_domains = ""
        if backlinks_stats and backlinks_stats.get('metrics'):
            bl_data = backlinks_stats['metrics']
            live_backlinks = str(bl_data.get('live', '')) if bl_data.get('live') else ""
            referring_domains = str(bl_data.get('live_refdomains', '')) if bl_data.get('live_refdomains') else ""
        
        top_keywords_str = ""
        if top_keywords and top_keywords.get('keywords'):
            keywords_list = []
            for kw in top_keywords['keywords'][:5]:
                keyword = kw.get('keyword', '')
                traffic = kw.get('sum_traffic', 0)
                if keyword:
                    keywords_list.append(f"{keyword} ({traffic:,})")
            top_keywords_str = "; ".join(keywords_list)
        
        country_distribution = ""
        if country_summary and country_summary.get('countries'):
            country_list = []
            for country in country_summary['countries'][:5]:
                country_name = country.get('country', '')
                percentage = country.get('percentage', 0)
                if country_name:
                    country_list.append(f"{country_name}: {percentage}%")
            country_distribution = "; ".join(country_list)
        
        historical_data = ""
        if historical_metrics:
            yearly_data = {}
            for range_key, range_data in historical_metrics.items():
                if range_data and range_data.get('metrics') and isinstance(range_data['metrics'], list):
                    for month_data in range_data['metrics']:
                        if month_data and month_data.get('date'):
                            year = month_data['date'][:4]
                            if year not in yearly_data:
                                yearly_data[year] = 0
                            yearly_data[year] += month_data.get('org_traffic', 0) or 0
            
            if yearly_data:
                year_list = []
                for year in sorted(yearly_data.keys(), reverse=True):
                    avg_monthly = yearly_data[year] / 12
                    if avg_monthly >= 1000000:
                        year_list.append(f"{year}: {avg_monthly/1000000:.1f}M")
                    elif avg_monthly >= 1000:
                        year_list.append(f"{year}: {avg_monthly/1000:.1f}K")
                    else:
                        year_list.append(f"{year}: {int(avg_monthly):,}")
                historical_data = "; ".join(year_list)
        
        return {
            "URL": url_obj.url,
            "Org_keywords": org_keywords,
            "Org_traffic": org_traffic,
            "Traffic_value": traffic_value,
            "Domain_rating": dr_display,
            "Live_backlinks": live_backlinks,
            "Reffering_domains": referring_domains,
            "Top_keywords": top_keywords_str,
            "Country_distribution": country_distribution,
            "Historical_data": historical_data,
            "Last_updated": url_data_record.fetched_at.strftime('%Y-%m-%d %H:%M')
        }
    
    def send_to_sheets(self, formatted_data):
        try:
            response = requests.post(self.api_url, headers={}, json={"data": formatted_data})
            return response.status_code == 201
        except Exception as e:
            return False
    
    def update_ahrefs_data(self, url_data_record):
        formatted_data = self.format_ahrefs_data_for_sheets(url_data_record)
        return self.send_to_sheets(formatted_data)