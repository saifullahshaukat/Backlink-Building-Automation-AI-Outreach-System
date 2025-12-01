from flask import Flask, render_template, request, jsonify, flash, redirect, url_for, send_file, session
from werkzeug.utils import secure_filename
from werkzeug.security import check_password_hash, generate_password_hash
from functools import wraps
import os
import csv
import json
import pandas as pd
from io import StringIO, BytesIO
from datetime import datetime, timedelta
import threading
import time
import logging

from config import Config
from database import db, URL, URLData, SuppressionList, User, ScrapedData, ScrapingSession, OutreachData, OutreachConfig, ArchivedURLData
from ahrefs_api import AhrefsAPI
from outreach_bot import OutreachBot
from scrapers.adsy_scraper import AdsyScraper
from scrapers.icopify_scraper import IcopifyScraper
from system_stats import SystemStats

from suppression_utils import (
    is_url_suppressed, 
    filter_urls_by_suppression, 
    clean_url_before_storage,
    get_urls_from_source,
    get_suppression_stats
)

from dupe_utils import normalize_url, find_duplicates, generate_clean_csv

from sheets_api import SheetsAPI
from email_extractor import EmailExtractor
from database import ExtractedEmail
from hunter_extractor import HunterExtractor
from database import EmailOutreach, EmailCredentials, EmailTemplate
from email_sender import EmailSender

app = Flask(__name__)
app.config.from_object(Config)

USERS = {
    'admin': generate_password_hash('123'),
    'Andrew': generate_password_hash('P4ssW0Rd@00191')
}

app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=30)
app.config['SESSION_PERMANENT'] = False
hunter_extractor = HunterExtractor(app.config['HUNTER_API_KEY'])

db.init_app(app)
ahrefs_api = AhrefsAPI()
outreach_bot = OutreachBot()
sheets_api = SheetsAPI()
email_extractor = EmailExtractor()
email_sender = EmailSender()
system_stats = SystemStats()

scraping_stats = {
    'is_running': False,
    'current_session': None,
    'logs': []
}

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'logged_in' not in session or not session['logged_in']:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

def check_auth():
    return session.get('logged_in', False)

def create_admin_user():
    admin = User.query.filter_by(username='admin').first()
    if not admin:
        admin_user = User(
            username='admin',
            email='admin@admin.com',
            password_hash=generate_password_hash('123')
        )
        db.session.add(admin_user)
        db.session.commit()

def add_log(message, level='INFO'):
    log_entry = {
        'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'level': level,
        'message': message
    }
    scraping_stats['logs'].append(log_entry)
    if len(scraping_stats['logs']) > 100:
        scraping_stats['logs'].pop(0)

def save_scraped_data(data_list, source):
    try:
        with app.app_context():
            saved_count = 0
            
            for data in data_list:
                url = data.get('URL') or data.get('url', '')
                if url and not is_url_suppressed(url):
                    existing = ScrapedData.query.filter_by(url=url).first()
                    if not existing:
                        scraped_item = ScrapedData(
                            url=url,
                            source=source,
                            categories=data.get('CATEGORIES') or data.get('Categories', ''),
                            language=data.get('LANGUAGES') or data.get('Language', ''),
                            monthly_traffic=data.get('MONTHLY_TRAFFIC', ''),
                            ahrefs_traffic=data.get('Ahrefs_Traffic', ''),
                            similarweb_traffic=data.get('Similarweb_Traffic', ''),
                            semrush_traffic=data.get('SemRush_Traffic', ''),
                            ahrefs_dr=data.get('AHREFS_DR') or data.get('Ahrefs_DR', ''),
                            moz_da=data.get('MOZ_DA') or data.get('Moz_DA', ''),
                            referral_domains=data.get('Referral_Domains', ''),
                            content_placement_price=data.get('Content_Placement_Price', ''),
                            writing_placement_price=data.get('Writing_Placement_Price', ''),
                            semrush_as=data.get('SemRush_AS', ''),
                            completion_rate=data.get('Completion_Rate', ''),
                            link_lifetime=data.get('Link_Lifetime', ''),
                            tat_days=data.get('TAT_Days', ''),
                            link_type=data.get('Link_Type', ''),
                            sponsored_required=data.get('Sponsored_Required', ''),
                            content_size=data.get('Content_Size', ''),
                            spam_score=data.get('Spam_Score', ''),
                            description=data.get('Description', '')
                        )
                        db.session.add(scraped_item)
                        saved_count += 1
            
            db.session.commit()
            add_log(f"Saved {saved_count} new records to database")
            return saved_count
    except Exception as e:
        with app.app_context():
            db.session.rollback()
            add_log(f"Error saving data: {str(e)}", 'ERROR')
        return 0

def run_scraper_thread(source, start_page, pages_to_scrape, session_id):
    with app.app_context():
        session = None
        try:
            scraping_stats['is_running'] = True
            session = ScrapingSession.query.get(session_id)
            session.status = 'running'
            db.session.commit()
            
            add_log(f"Starting {source} scraper from page {start_page} for {pages_to_scrape} pages")
            
            if source == 'adsy':
                scraper = AdsyScraper()
                if scraper.login():
                    for page in range(start_page, start_page + pages_to_scrape):
                        if not scraping_stats['is_running']:
                            break
                        
                        session.current_page = page
                        db.session.commit()
                        
                        add_log(f"Scraping Adsy page {page}")
                        page_data = scraper.scrape_page(page)
                        
                        if page_data:
                            saved = save_scraped_data(page_data, 'adsy')
                            session.records_scraped += saved
                            db.session.commit()
                            add_log(f"Page {page}: Scraped {len(page_data)} records, saved {saved}")
                        
                        time.sleep(2)
                else:
                    add_log("Failed to login to Adsy", 'ERROR')
            
            elif source == 'icopify':
                scraper = IcopifyScraper(start_page=start_page)
                if scraper.setup_driver() and scraper.login():
                    for page in range(start_page, start_page + pages_to_scrape):
                        if not scraping_stats['is_running']:
                            break
                        
                        session.current_page = page
                        db.session.commit()
                        
                        add_log(f"Scraping Icopify page {page}")
                        page_data = scraper.scrape_page_data(page)
                        
                        if page_data:
                            saved = save_scraped_data(page_data, 'icopify')
                            session.records_scraped += saved
                            db.session.commit()
                            add_log(f"Page {page}: Scraped {len(page_data)} records, saved {saved}")
                        
                        time.sleep(2)
                    
                    scraper.cleanup()
                else:
                    add_log("Failed to setup or login to Icopify", 'ERROR')
            
            if session:
                session.status = 'completed'
                session.completed_at = datetime.utcnow()
                db.session.commit()
            add_log(f"{source} scraping completed successfully")
            
        except Exception as e:
            if session:
                session.status = 'failed'
                session.error_message = str(e)
                session.completed_at = datetime.utcnow()
                db.session.commit()
            add_log(f"Scraping failed: {str(e)}", 'ERROR')
        
        finally:
            scraping_stats['is_running'] = False
            scraping_stats['current_session'] = None

with app.app_context():
    db.create_all()
    
    try:
        existing_records = db.session.execute(db.text("SELECT * FROM extracted_email LIMIT 1")).fetchone()
        if existing_records and 'email' in [col for col in existing_records._fields]:
            db.session.execute(db.text("DROP TABLE extracted_email"))
            db.session.commit()
            db.create_all()
            print("Migrated ExtractedEmail table")
    except:
        pass
@app.route('/login', methods=['GET', 'POST'])
def login():
    if check_auth():
        return redirect(url_for('dashboard'))
    
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        remember = request.form.get('remember')
        
        if username in USERS and check_password_hash(USERS[username], password):
            session['logged_in'] = True
            session['username'] = username
            session['login_time'] = datetime.utcnow().isoformat()
            
            if remember:
                session.permanent = True
            
            flash(f'Welcome back, {username}!', 'success')
            
            next_page = request.args.get('next')
            if next_page and next_page.startswith('/'):
                return redirect(next_page)
            return redirect(url_for('dashboard'))
        else:
            flash('Invalid username or password. Please try again.', 'error')
    
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    username = session.get('username', 'User')
    session.clear()
    flash(f'You have been logged out successfully, {username}.', 'info')
    return redirect(url_for('login'))

@app.route('/')
@login_required
def dashboard():
    ahrefs_url_count = URL.query.count()
    ahrefs_data_count = URLData.query.count()
    archived_data_count = ArchivedURLData.query.count()
    suppressed_count = SuppressionList.query.count()
    
    outreach_data_count = OutreachData.query.count()
    
    scraped_total = ScrapedData.query.count()
    scraped_adsy = ScrapedData.query.filter_by(source='adsy').count()
    scraped_icopify = ScrapedData.query.filter_by(source='icopify').count()
    
    recent_sessions = ScrapingSession.query.order_by(ScrapingSession.started_at.desc()).limit(5).all()
    recent_urls = URL.query.order_by(URL.created_at.desc()).limit(5).all()
    recent_data = URLData.query.order_by(URLData.fetched_at.desc()).limit(5).all()
    
    stats = {
        'ahrefs': {
            'url_count': ahrefs_url_count,
            'data_count': ahrefs_data_count,
            'archived_count': archived_data_count,
            'recent_urls': recent_urls,
            'recent_data': recent_data
        },
        'outreach': {
            'data_count': outreach_data_count,
            'bot_stats': outreach_bot.stats
        },
        'scraping': {
            'total_records': scraped_total,
            'adsy_records': scraped_adsy,
            'icopify_records': scraped_icopify,
            'is_running': scraping_stats['is_running']
        },
        'suppressed_count': suppressed_count,
        'recent_sessions': recent_sessions
    }
    
    return render_template('dashboard.html', stats=stats)

@app.route('/ahrefs/urls')
@login_required
def ahrefs_urls():
    page = request.args.get('page', 1, type=int)
    search = request.args.get('search', '', type=str)
    
    query = URL.query
    if search:
        query = query.filter(URL.url.contains(search))
    
    urls_pagination = query.order_by(URL.created_at.desc()).paginate(
        page=page, per_page=50, error_out=False
    )
    
    return render_template('ahrefs/urls.html', urls=urls_pagination, search=search)

@app.route('/ahrefs/add_urls', methods=['POST'])
@login_required
def ahrefs_add_urls():
    if 'urls_text' in request.form:
        urls_text = request.form['urls_text']
        urls_list = [url.strip() for url in urls_text.split('\n') if url.strip()]
        urls_list = filter_urls_by_suppression(urls_list)
        
        added_count = 0
        for url in urls_list:
            clean_url = ahrefs_api.clean_url(url)
            existing = URL.query.filter_by(url=clean_url).first()
            if not existing:
                new_url = URL(url=clean_url)
                db.session.add(new_url)
                added_count += 1
        
        db.session.commit()
        flash(f'Added {added_count} new URLs', 'success')
    
    elif 'csv_file' in request.files:
        file = request.files['csv_file']
        if file and (file.filename.endswith('.csv') or file.filename.endswith('.xlsx') or file.filename.endswith('.xls')):
            filename = secure_filename(file.filename)
            filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            
            os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
            file.save(filepath)
            
            added_count = 0
            
            # Handle Excel files
            if file.filename.endswith('.xlsx') or file.filename.endswith('.xls'):
                df = pd.read_excel(filepath)
                for _, row in df.iterrows():
                    if 'URL' in df.columns and pd.notna(row['URL']):
                        clean_url = ahrefs_api.clean_url(str(row['URL']))
                        if not is_url_suppressed(clean_url):
                            existing = URL.query.filter_by(url=clean_url).first()
                            if not existing:
                                new_url = URL(url=clean_url)
                                db.session.add(new_url)
                                added_count += 1
            # Handle CSV files
            else:
                with open(filepath, 'r', encoding='utf-8') as csvfile:
                    reader = csv.DictReader(csvfile)
                    for row in reader:
                        if 'URL' in row and row['URL']:
                            clean_url = ahrefs_api.clean_url(row['URL'])
                            if not is_url_suppressed(clean_url):
                                existing = URL.query.filter_by(url=clean_url).first()
                                if not existing:
                                    new_url = URL(url=clean_url)
                                    db.session.add(new_url)
                                    added_count += 1
            
            db.session.commit()
            os.remove(filepath)
            flash(f'Added {added_count} URLs from file', 'success')
    
    return redirect(url_for('ahrefs_urls'))

@app.route('/ahrefs/import-from-scraped', methods=['POST'])
@login_required
def ahrefs_import_from_scraped():
    data = request.get_json()
    source = data.get('source', 'all')
    skip_existing = data.get('skip_existing', True)
    
    query = ScrapedData.query
    if source != 'all':
        query = query.filter_by(source=source)
    
    scraped_urls = query.all()
    added_count = 0
    
    for scraped in scraped_urls:
        clean_url = ahrefs_api.clean_url(scraped.url)
        if not is_url_suppressed(clean_url):
            if skip_existing:
                existing = URL.query.filter_by(url=clean_url).first()
                if existing:
                    continue
            
            new_url = URL(url=clean_url)
            db.session.add(new_url)
            added_count += 1
    
    db.session.commit()
    return jsonify({
        'success': True, 
        'message': f'Imported {added_count} URLs from {source} scraped data'
    })

@app.route('/ahrefs/scraped-stats')
@login_required
def ahrefs_scraped_stats():
    source = request.args.get('source', 'all')
    
    adsy_count = ScrapedData.query.filter_by(source='adsy').count()
    icopify_count = ScrapedData.query.filter_by(source='icopify').count()
    total_count = ScrapedData.query.count()
    
    if source == 'adsy':
        available_urls = ScrapedData.query.filter_by(source='adsy').all()
    elif source == 'icopify':
        available_urls = ScrapedData.query.filter_by(source='icopify').all()
    else:
        available_urls = ScrapedData.query.all()
    
    existing_urls = {url.url for url in URL.query.all()}
    new_count = sum(1 for scraped in available_urls if scraped.url not in existing_urls)
    existing_count = len(available_urls) - new_count
    
    return jsonify({
        'adsy_count': adsy_count,
        'icopify_count': icopify_count,
        'total_count': total_count,
        'new_count': new_count,
        'existing_count': existing_count
    })

@app.route('/ahrefs/bulk-delete-urls', methods=['POST'])
@login_required
def ahrefs_bulk_delete_urls():
    data = request.get_json()
    url_ids = data.get('ids', [])
    
    deleted_count = 0
    for url_id in url_ids:
        url = URL.query.get(url_id)
        if url:
            URLData.query.filter_by(url_id=url_id).delete()
            db.session.delete(url)
            deleted_count += 1
    
    db.session.commit()
    return jsonify({'success': True, 'deleted': deleted_count})

@app.route('/ahrefs/export-selected-urls', methods=['POST'])
@login_required
def ahrefs_export_selected_urls():
    url_ids = json.loads(request.form.get('url_ids', '[]'))
    urls = URL.query.filter(URL.id.in_(url_ids)).all()
    
    output = StringIO()
    writer = csv.writer(output)
    writer.writerow(['URL', 'Created At', 'Updated At', 'Has Data'])
    
    for url in urls:
        has_data = 'Yes' if URLData.query.filter_by(url_id=url.id).first() else 'No'
        writer.writerow([url.url, url.created_at, url.updated_at, has_data])
    
    output.seek(0)
    return send_file(
        BytesIO(output.getvalue().encode()),
        mimetype='text/csv',
        as_attachment=True,
        download_name=f'selected_urls_export_{datetime.now().strftime("%Y%m%d_%H%M%S")}.csv'
    )

@app.route('/ahrefs/view_data_by_url/<int:url_id>')
@login_required
def ahrefs_view_data_by_url(url_id):
    url = URL.query.get_or_404(url_id)
    url_data = URLData.query.filter_by(url_id=url_id).first()
    
    if url_data:
        return jsonify({
            'success': True,
            'data': {
                'url': url.url,
                'current_metrics': url_data.get_current_metrics(),
                'domain_rating': url_data.get_domain_rating(),
                'backlinks_stats': url_data.get_backlinks_stats(),
                'historical_metrics': url_data.get_historical_metrics(),
                'fetched_at': url_data.fetched_at.isoformat()
            }
        })
    else:
        return jsonify({'success': False, 'message': 'No data found for this URL'})

@app.route('/ahrefs/delete_url/<int:url_id>', methods=['POST'])
@login_required
def ahrefs_delete_url(url_id):
    url = URL.query.get_or_404(url_id)
    URLData.query.filter_by(url_id=url_id).delete()
    db.session.delete(url)
    db.session.commit()
    flash('URL deleted successfully', 'success')
    return redirect(url_for('ahrefs_urls'))

@app.route('/ahrefs/execute')
@login_required
def ahrefs_execute():
    urls = URL.query.order_by(URL.url).all()
    scraped_data = ScrapedData.query.order_by(ScrapedData.created_at.desc()).limit(100).all()
    url_data_records = URLData.query.join(URL).order_by(URLData.fetched_at.desc()).limit(100).all()
    
    return render_template('ahrefs/execute.html', 
                         urls=urls, 
                         scraped_data=scraped_data,
                         url_data_records=url_data_records)

@app.route('/ahrefs/import-for-execution', methods=['POST'])
@login_required
def ahrefs_import_for_execution():
    data = request.get_json()
    source_type = data.get('source_type')
    source_filter = data.get('source_filter', 'all')
    selected_ids = data.get('selected_ids', [])
    
    added_urls = []
    
    if source_type == 'scraped':
        if selected_ids:
            scraped_items = ScrapedData.query.filter(ScrapedData.id.in_(selected_ids)).all()
        else:
            query = ScrapedData.query
            if source_filter != 'all':
                query = query.filter_by(source=source_filter)
            scraped_items = query.all()
        
        for item in scraped_items:
            clean_url = ahrefs_api.clean_url(item.url)
            existing = URL.query.filter_by(url=clean_url).first()
            if not existing:
                new_url = URL(url=clean_url)
                db.session.add(new_url)
                db.session.flush()
                added_urls.append(new_url.id)
            else:
                added_urls.append(existing.id)
    
    elif source_type == 'url_data':
        if selected_ids:
            data_items = URLData.query.filter(URLData.id.in_(selected_ids)).all()
            added_urls = [item.url_id for item in data_items]
    
    db.session.commit()
    return jsonify({'success': True, 'added_urls': added_urls, 'count': len(added_urls)})

@app.route('/ahrefs/run_operation', methods=['POST'])
@login_required
def ahrefs_run_operation():
    operation_data = request.json

    selected_urls = operation_data.get('urls', [])
    operations = operation_data.get('operations', [])
    date_ranges = operation_data.get('dateRanges', [])
    www_mode = operation_data.get('www_mode', 'both')

    if 'new_urls' in operation_data and operation_data['new_urls']:
        new_urls_text = operation_data['new_urls']
        new_urls_list = [url.strip() for url in new_urls_text.split('\n') if url.strip()]
        new_urls_list = filter_urls_by_suppression(new_urls_list)

        for url in new_urls_list:
            url_variations = ahrefs_api.get_url_variations(url, www_mode)
            for clean_url in url_variations:
                if not is_url_suppressed(clean_url):
                    existing = URL.query.filter_by(url=clean_url).first()
                    if not existing:
                        new_url = URL(url=clean_url)
                        db.session.add(new_url)
                        db.session.flush()
                        selected_urls.append(new_url.id)
                    else:
                        selected_urls.append(existing.id)

    db.session.commit()

    results = []
    processed_urls = set()

    for url_id in selected_urls:
        url_obj = URL.query.get(url_id)
        if not url_obj:
            continue

        original_url = url_obj.url
        
        if www_mode == 'both':
            url_variations = ahrefs_api.get_url_variations(original_url, 'both')
            for variation in url_variations:
                if variation not in processed_urls:
                    processed_urls.add(variation)
                    existing_var = URL.query.filter_by(url=variation).first()
                    if not existing_var:
                        new_var = URL(url=variation)
                        db.session.add(new_var)
                        db.session.flush()
                        url_variations_to_process = [(new_var.id, variation)]
                    else:
                        url_variations_to_process = [(existing_var.id, variation)]
                    
                    for var_id, var_url in url_variations_to_process:
                        try:
                            comprehensive_data = ahrefs_api.get_comprehensive_data(var_url, operations, date_ranges)
                            
                            existing_data = URLData.query.filter_by(url_id=var_id).first()
                            
                            if existing_data:
                                update_url_data(existing_data, comprehensive_data)
                                existing_data.fetched_at = datetime.utcnow()
                            else:
                                new_data = URLData(url_id=var_id)
                                update_url_data(new_data, comprehensive_data)
                                db.session.add(new_data)
                            
                            results.append({
                                'url': var_url,
                                'operations': operations,
                                'status': 'success',
                                'data': comprehensive_data
                            })
                            
                        except Exception as e:
                            results.append({
                                'url': var_url,
                                'operations': operations,
                                'status': 'error',
                                'error': str(e)
                            })
        else:
            url_variations = ahrefs_api.get_url_variations(original_url, www_mode)
            target_url = url_variations[0]
            
            try:
                comprehensive_data = ahrefs_api.get_comprehensive_data(target_url, operations, date_ranges)
                
                existing_data = URLData.query.filter_by(url_id=url_id).first()
                
                if existing_data:
                    update_url_data(existing_data, comprehensive_data)
                    existing_data.fetched_at = datetime.utcnow()
                else:
                    new_data = URLData(url_id=url_id)
                    update_url_data(new_data, comprehensive_data)
                    db.session.add(new_data)
                
                results.append({
                    'url': target_url,
                    'operations': operations,
                    'status': 'success',
                    'data': comprehensive_data
                })
                
            except Exception as e:
                results.append({
                    'url': target_url,
                    'operations': operations,
                    'status': 'error',
                    'error': str(e)
                })

    db.session.commit()

    return jsonify({
        'status': 'success',
        'message': f'Completed operations for {len(results)} URL variations',
        'results': results
    })

def update_url_data(url_data, comprehensive_data):
    if comprehensive_data.get('current_metrics'):
        url_data.set_current_metrics(comprehensive_data['current_metrics'])
    if comprehensive_data.get('domain_rating'):
        url_data.set_domain_rating(comprehensive_data['domain_rating'])
    if comprehensive_data.get('backlinks_stats'):
        url_data.set_backlinks_stats(comprehensive_data['backlinks_stats'])
    if comprehensive_data.get('top_keywords'):
        url_data.set_top_keywords(comprehensive_data['top_keywords'])
    if comprehensive_data.get('country_metrics'):
        url_data.set_country_metrics(comprehensive_data['country_metrics'])
    if comprehensive_data.get('historical_metrics'):
        url_data.set_historical_metrics(comprehensive_data['historical_metrics'])
    elif comprehensive_data.get('historical_snapshots'):
        url_data.set_historical_metrics(comprehensive_data['historical_snapshots'])
    
    db.session.flush()
    
    try:
        sheets_api.update_ahrefs_data(url_data)
    except Exception as e:
        print(f"Failed to sync to sheets: {e}")

@app.route('/ahrefs/data')
@login_required
def ahrefs_data():
    page = request.args.get('page', 1, type=int)
    search = request.args.get('search', '', type=str)
    
    query = URLData.query.join(URL)
    
    if search:
        query = query.filter(URL.url.contains(search))
    
    data_pagination = query.order_by(URLData.fetched_at.desc()).paginate(
        page=page, per_page=20, error_out=False
    )
    
    return render_template('ahrefs/data.html', data=data_pagination, search=search)

@app.route('/ahrefs/view_data/<int:data_id>')
@login_required
def ahrefs_view_data(data_id):
    url_data = URLData.query.get_or_404(data_id)
    return jsonify({
        'url': url_data.url.url,
        'data': url_data.get_all_data(),
        'fetched_at': url_data.fetched_at.isoformat()
    })

@app.route('/ahrefs/delete_data/<int:data_id>', methods=['POST'])
@login_required
def ahrefs_delete_data(data_id):
    url_data = URLData.query.get_or_404(data_id)
    db.session.delete(url_data)
    db.session.commit()
    flash('Data deleted successfully', 'success')
    return redirect(url_for('ahrefs_data'))

@app.route('/outreach/config')
@login_required
def outreach_config():
    return render_template('outreach/config.html', config=outreach_bot.config)

@app.route('/outreach/urls')
@login_required
def outreach_urls():
    page = request.args.get('page', 1, type=int)
    search = request.args.get('search', '', type=str)
    status_filter = request.args.get('status', '', type=str)
    
    query = OutreachData.query
    if search:
        query = query.filter(OutreachData.url.contains(search))
    if status_filter:
        query = query.filter_by(status=status_filter)
    
    pagination = query.order_by(OutreachData.created_at.desc()).paginate(
        page=page, per_page=50, error_out=False
    )
    
    return render_template('outreach/urls.html', pagination=pagination, search=search, status_filter=status_filter)

@app.route('/outreach/execute')
@login_required
def outreach_execute():
    outreach_records = OutreachData.query.order_by(OutreachData.created_at.desc()).limit(100).all()
    config = outreach_bot.config
    return render_template('outreach/execute.html', outreach_records=outreach_records, config=config)

@app.route('/outreach/import-urls', methods=['POST'])
@login_required
def outreach_import_urls():
    data = request.get_json()
    source_type = data.get('source_type')
    source_filter = data.get('source_filter', 'all')
    selected_ids = data.get('selected_ids', [])
    search_term = data.get('search_term', '')
    csv_data = data.get('csv_data', '')
    manual_urls = data.get('manual_urls', '')
    
    added_count = 0
    
    if source_type == 'manual' and manual_urls:
        urls_list = [url.strip() for url in manual_urls.split('\n') if url.strip()]
        for url in urls_list:
            if not url.startswith('http'):
                url = 'https://' + url
            if not is_url_suppressed(url):
                existing = OutreachData.query.filter_by(url=url).first()
                if not existing:
                    outreach_record = OutreachData(url=url, status='pending')
                    db.session.add(outreach_record)
                    added_count += 1
    
    elif source_type == 'csv' and csv_data:
        try:
            csv_reader = csv.DictReader(StringIO(csv_data))
            for row in csv_reader:
                url = row.get('URL', '').strip()
                if url and not is_url_suppressed(url):
                    existing = OutreachData.query.filter_by(url=url).first()
                    if not existing:
                        outreach_record = OutreachData(url=url, status='pending')
                        db.session.add(outreach_record)
                        added_count += 1
        except Exception as e:
            return jsonify({'success': False, 'message': f'CSV import failed: {str(e)}'})
    
    elif source_type == 'scraped':
        query = ScrapedData.query
        if source_filter != 'all':
            query = query.filter_by(source=source_filter)
        if search_term:
            query = query.filter(ScrapedData.url.contains(search_term))
        if selected_ids:
            query = query.filter(ScrapedData.id.in_(selected_ids))
        
        scraped_items = query.all()
        for item in scraped_items:
            if not is_url_suppressed(item.url):
                existing = OutreachData.query.filter_by(url=item.url).first()
                if not existing:
                    outreach_record = OutreachData(url=item.url, status='pending')
                    db.session.add(outreach_record)
                    added_count += 1
    
    elif source_type == 'ahrefs_data':
        query = URLData.query.join(URL)
        if search_term:
            query = query.filter(URL.url.contains(search_term))
        if selected_ids:
            query = query.filter(URLData.id.in_(selected_ids))
        
        ahrefs_items = query.all()
        for item in ahrefs_items:
            if not is_url_suppressed(item.url.url):
                existing = OutreachData.query.filter_by(url=item.url.url).first()
                if not existing:
                    outreach_record = OutreachData(url=item.url.url, status='pending')
                    db.session.add(outreach_record)
                    added_count += 1
    
    db.session.commit()
    return jsonify({'success': True, 'message': f'Imported {added_count} URLs for outreach'})

@app.route('/outreach/delete-urls', methods=['POST'])
@login_required
def outreach_delete_urls():
    data = request.get_json()
    url_ids = data.get('ids', [])
    
    deleted_count = 0
    for url_id in url_ids:
        record = OutreachData.query.get(url_id)
        if record:
            db.session.delete(record)
            deleted_count += 1
    
    db.session.commit()
    return jsonify({'success': True, 'deleted': deleted_count})

@app.route('/outreach/run', methods=['POST'])
@login_required
def outreach_run():
    data = request.get_json()
    execution_mode = data.get('execution_mode', 'automatic')
    selected_urls = data.get('selected_urls', [])
    run_mode = data.get('run_mode', 'continuous')
    target_count = data.get('target_count', 0)
    custom_config = data.get('custom_config') if execution_mode == 'dynamic' else None
    extract_emails = data.get('extract_emails', False)
    
    success = outreach_bot.start_bot(
        run_mode=run_mode,
        target_count=target_count,
        selected_urls=selected_urls,
        execution_mode=execution_mode,
        custom_config=custom_config,
        app=app,
        extract_emails=extract_emails
    )
    
    return jsonify({'success': success, 'message': 'Bot started' if success else 'Bot already running'})

@app.route('/outreach/api/config')
@login_required
def outreach_get_config():
    return jsonify(outreach_bot.config)

@app.route('/outreach/api/config', methods=['POST'])
@login_required
def outreach_save_config():
    data = request.json
    outreach_bot.save_config(data)
    return jsonify({'success': True, 'message': 'Configuration saved'})

@app.route('/outreach/stats')
@login_required
def outreach_stats():
    total_urls = OutreachData.query.count()
    pending_urls = OutreachData.query.filter_by(status='pending').count()
    success_urls = OutreachData.query.filter_by(status='completed').count()
    error_urls = OutreachData.query.filter_by(status='error').count()
    form_found_not_submitted = OutreachData.query.filter_by(status='form_found_not_submitted').count()
    no_form_found = OutreachData.query.filter_by(status='no_form_found').count()
    processing_urls = OutreachData.query.filter_by(status='processing').count()
    
    success_rate = (success_urls / total_urls * 100) if total_urls > 0 else 0
    form_found_rate = ((success_urls + form_found_not_submitted) / total_urls * 100) if total_urls > 0 else 0
    
    recent_successes = OutreachData.query.filter_by(status='completed').order_by(OutreachData.created_at.desc()).limit(10).all()
    recent_errors = OutreachData.query.filter_by(status='error').order_by(OutreachData.created_at.desc()).limit(10).all()
    
    processed_urls = OutreachData.query.filter(
        OutreachData.status.in_(['completed', 'form_found_not_submitted', 'no_form_found', 'error'])
    ).order_by(OutreachData.created_at.desc()).limit(50).all()
    
    daily_stats = {}
    for record in OutreachData.query.all():
        date_key = record.created_at.strftime('%Y-%m-%d')
        if date_key not in daily_stats:
            daily_stats[date_key] = {'total': 0, 'success': 0, 'error': 0, 'form_found': 0}
        daily_stats[date_key]['total'] += 1
        if record.status == 'completed':
            daily_stats[date_key]['success'] += 1
        elif record.status == 'error':
            daily_stats[date_key]['error'] += 1
        if record.form_found:
            daily_stats[date_key]['form_found'] += 1
    
    execution_modes = {}
    for record in OutreachData.query.filter(OutreachData.execution_mode.isnot(None)).all():
        mode = record.execution_mode or 'automatic'
        if mode not in execution_modes:
            execution_modes[mode] = {'total': 0, 'success': 0}
        execution_modes[mode]['total'] += 1
        if record.status == 'completed':
            execution_modes[mode]['success'] += 1
    
    stats = {
        'total_urls': total_urls,
        'pending_urls': pending_urls,
        'success_urls': success_urls,
        'error_urls': error_urls,
        'form_found_not_submitted': form_found_not_submitted,
        'no_form_found': no_form_found,
        'processing_urls': processing_urls,
        'success_rate': round(success_rate, 2),
        'form_found_rate': round(form_found_rate, 2),
        'recent_successes': recent_successes,
        'recent_errors': recent_errors,
        'processed_urls': processed_urls,
        'bot_stats': outreach_bot.stats,
        'daily_stats': dict(sorted(daily_stats.items(), reverse=True)[:7]),
        'execution_modes': execution_modes
    }
    
    return render_template('outreach/stats.html', stats=stats)

@app.route('/outreach/screenshot/<int:record_id>')
@login_required
def outreach_screenshot(record_id):
    record = OutreachData.query.get_or_404(record_id)
    if record.screenshot_path and os.path.exists(record.screenshot_path):
        return send_file(record.screenshot_path, mimetype='image/png')
    else:
        return "Screenshot not found", 404

@app.route('/outreach/start', methods=['POST'])
@login_required
def outreach_start():
    data = request.json or {}
    run_mode = data.get('run_mode', 'continuous')
    target_count = data.get('target_count', 0)
    
    success = outreach_bot.start_bot(run_mode, target_count)
    return jsonify({'success': success, 'message': 'Bot started' if success else 'Bot already running'})

@app.route('/outreach/stop', methods=['POST'])
@login_required
def outreach_stop():
    success = outreach_bot.stop_bot()
    return jsonify({'success': success, 'message': 'Bot stopped' if success else 'Bot not running'})

@app.route('/outreach/api/stats')
@login_required
def outreach_api_stats():
    return jsonify(outreach_bot.stats)

@app.route('/export/outreach_data')
@login_required
def export_outreach_data():
    records = OutreachData.query.all()
    
    output = StringIO()
    writer = csv.writer(output)
    writer.writerow(['URL', 'Status', 'Form Found', 'Form Submitted', 'Execution Mode', 'Config Used', 'Error Message', 'Created At'])
    
    for record in records:
        writer.writerow([
            record.url,
            record.status,
            'Yes' if record.form_found else 'No',
            'Yes' if record.form_submitted else 'No',
            record.execution_mode or 'automatic',
            json.dumps(record.get_config_used()) if record.get_config_used() else '',
            record.error_message or '',
            record.created_at
        ])
    
    output.seek(0)
    return send_file(
        BytesIO(output.getvalue().encode()),
        mimetype='text/csv',
        as_attachment=True,
        download_name=f'outreach_data_export_{datetime.now().strftime("%Y%m%d_%H%M%S")}.csv'
    )

@app.route('/scraper/data')
@login_required
def scraper_data():
    page = request.args.get('page', 1, type=int)
    source_filter = request.args.get('source', '')
    search = request.args.get('search', '')
    
    query = ScrapedData.query
    
    if source_filter:
        query = query.filter_by(source=source_filter)
    
    if search:
        query = query.filter(ScrapedData.url.contains(search))
    
    pagination = query.order_by(ScrapedData.created_at.desc()).paginate(
        page=page, per_page=50, error_out=False
    )
    
    return render_template('scraper/data.html', pagination=pagination, source_filter=source_filter, search=search)

@app.route('/scraper/start-scraping', methods=['POST'])
@login_required
def scraper_start_scraping():
    if scraping_stats['is_running']:
        return jsonify({'success': False, 'message': 'Scraper is already running'})
    
    data = request.get_json()
    source = data.get('source')
    start_page = int(data.get('start_page', 1))
    pages_to_scrape = int(data.get('pages_to_scrape', 10))
    
    session = ScrapingSession(
        source=source,
        start_page=start_page,
        pages_to_scrape=pages_to_scrape
    )
    db.session.add(session)
    db.session.commit()
    
    scraping_stats['current_session'] = session.id
    
    thread = threading.Thread(target=run_scraper_thread, args=(source, start_page, pages_to_scrape, session.id))
    thread.daemon = True
    thread.start()
    
    return jsonify({'success': True, 'message': f'Started {source} scraper'})

@app.route('/scraper/stop-scraping', methods=['POST'])
@login_required
def scraper_stop_scraping():
    scraping_stats['is_running'] = False
    add_log("Scraping stopped by user")
    return jsonify({'success': True, 'message': 'Scraper stopped'})

@app.route('/scraper/api/stats')
@login_required
def scraper_api_stats():
    try:
        session_id = scraping_stats.get('current_session')
        current_session = None
        
        if session_id:
            current_session = ScrapingSession.query.get(session_id)
        
        return jsonify({
            'is_running': scraping_stats['is_running'],
            'current_session': {
                'id': current_session.id if current_session else None,
                'source': current_session.source if current_session else None,
                'current_page': current_session.current_page if current_session else 0,
                'records_scraped': current_session.records_scraped if current_session else 0,
                'start_page': current_session.start_page if current_session else 0,
                'pages_to_scrape': current_session.pages_to_scrape if current_session else 0
            } if current_session else None,
            'logs': scraping_stats['logs'][-10:]
        })
    except Exception as e:
        return jsonify({
            'is_running': False,
            'current_session': None,
            'logs': [{'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'), 'level': 'ERROR', 'message': f'Error fetching stats: {str(e)}'}]
        })

@app.route('/suppression')
@login_required
def suppression():
    page = request.args.get('page', 1, type=int)
    search = request.args.get('search', '', type=str)
    
    query = SuppressionList.query
    if search:
        query = query.filter(SuppressionList.url.contains(search))
    
    suppression_pagination = query.order_by(SuppressionList.created_at.desc()).paginate(
        page=page, per_page=50, error_out=False
    )
    
    return render_template('suppression.html', suppression=suppression_pagination, search=search)

@app.route('/suppression/add', methods=['POST'])
@login_required
def add_suppression():
    if request.is_json:
        data = request.get_json()
        urls = data.get('urls', [])
        reason = data.get('reason', '')
        
        added_count = 0
        for url in urls:
            url = clean_url_before_storage(url.strip())
            if url and not SuppressionList.query.filter_by(url=url).first():
                suppressed_url = SuppressionList(url=url, reason=reason)
                db.session.add(suppressed_url)
                added_count += 1
        
        db.session.commit()
        return jsonify({'success': True, 'message': f'Added {added_count} URLs to suppression list'})
    
    elif 'urls_text' in request.form:
        urls_text = request.form['urls_text']
        reason = request.form.get('reason', '')
        urls_list = [url.strip() for url in urls_text.split('\n') if url.strip()]
        
        added_count = 0
        for url in urls_list:
            clean_url = clean_url_before_storage(url)
            existing = SuppressionList.query.filter_by(url=clean_url).first()
            if not existing:
                suppressed_url = SuppressionList(url=clean_url, reason=reason)
                db.session.add(suppressed_url)
                added_count += 1
        
        db.session.commit()
        flash(f'Added {added_count} URLs to suppression list', 'success')
    
    elif 'csv_file' in request.files:
        file = request.files['csv_file']
        if file and (file.filename.endswith('.csv') or file.filename.endswith('.xlsx') or file.filename.endswith('.xls')):
            filename = secure_filename(file.filename)
            filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            
            os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
            file.save(filepath)
            
            added_count = 0
            
            # Handle Excel files
            if file.filename.endswith('.xlsx') or file.filename.endswith('.xls'):
                df = pd.read_excel(filepath)
                for _, row in df.iterrows():
                    if 'URL' in df.columns and pd.notna(row['URL']):
                        clean_url = clean_url_before_storage(str(row['URL']))
                        existing = SuppressionList.query.filter_by(url=clean_url).first()
                        if not existing:
                            reason = str(row.get('Reason', '')) if pd.notna(row.get('Reason')) else ''
                            suppressed_url = SuppressionList(url=clean_url, reason=reason)
                            db.session.add(suppressed_url)
                            added_count += 1
            # Handle CSV files
            else:
                with open(filepath, 'r', encoding='utf-8') as csvfile:
                    reader = csv.DictReader(csvfile)
                    for row in reader:
                        if 'URL' in row and row['URL']:
                            clean_url = clean_url_before_storage(row['URL'])
                            existing = SuppressionList.query.filter_by(url=clean_url).first()
                            if not existing:
                                reason = row.get('Reason', '')
                                suppressed_url = SuppressionList(url=clean_url, reason=reason)
                                db.session.add(suppressed_url)
                                added_count += 1
            
            db.session.commit()
            os.remove(filepath)
            flash(f'Added {added_count} URLs to suppression list from file', 'success')
    
    return redirect(url_for('suppression'))

@app.route('/suppression/delete/<int:suppression_id>', methods=['POST'])
@login_required
def delete_suppression(suppression_id):
    suppressed_url = SuppressionList.query.get_or_404(suppression_id)
    db.session.delete(suppressed_url)
    db.session.commit()
    flash('URL removed from suppression list', 'success')
    return redirect(url_for('suppression'))

@app.route('/suppression/bulk_delete', methods=['POST'])
@login_required
def bulk_delete_suppression():
    url_ids = request.json.get('ids', [])
    deleted_count = 0
    
    for url_id in url_ids:
        suppressed_url = SuppressionList.query.get(url_id)
        if suppressed_url:
            db.session.delete(suppressed_url)
            deleted_count += 1
    
    db.session.commit()
    return jsonify({'status': 'success', 'deleted': deleted_count})

@app.route('/export/ahrefs_urls')
@login_required
def export_ahrefs_urls():
    urls = URL.query.all()
    output = StringIO()
    writer = csv.writer(output)
    writer.writerow(['URL', 'Created At', 'Updated At', 'Has Data'])
    
    for url in urls:
        has_data = 'Yes' if URLData.query.filter_by(url_id=url.id).first() else 'No'
        writer.writerow([url.url, url.created_at, url.updated_at, has_data])
    
    output.seek(0)
    return send_file(
        BytesIO(output.getvalue().encode()),
        mimetype='text/csv',
        as_attachment=True,
        download_name=f'ahrefs_urls_export_{datetime.now().strftime("%Y%m%d_%H%M%S")}.csv'
    )

@app.route('/export/ahrefs_data')
@login_required
def export_ahrefs_data():
    data_records = URLData.query.join(URL).all()
    
    output = StringIO()
    writer = csv.writer(output)
    
    header = [
        'URL', 'Fetched At',
        'Org Keywords', 'Org Keywords 1-3', 'Org Traffic', 'Org Cost',
        'Domain Rating', 'Ahrefs Rank',
        'Live Backlinks', 'All Time Backlinks', 'Live Ref Domains', 'All Time Ref Domains',
        'Top Keywords', 'Country Percentages'
    ]
    
    yearly_data_by_record = {}
    all_years = set()
    
    for record in data_records:
        yearly_data_by_record[record.id] = {}
        historical_data = record.get_historical_metrics()
        if historical_data:
            for range_key, range_data in historical_data.items():
                if range_data and isinstance(range_data, dict) and 'metrics' in range_data:
                    if isinstance(range_data['metrics'], list):
                        for month_data in range_data['metrics']:
                            if isinstance(month_data, dict) and 'date' in month_data:
                                year = month_data['date'][:4]
                                all_years.add(year)
                                if year not in yearly_data_by_record[record.id]:
                                    yearly_data_by_record[record.id][year] = {'traffic': 0, 'cost': 0}
                                yearly_data_by_record[record.id][year]['traffic'] += month_data.get('org_traffic', 0) or 0
                                yearly_data_by_record[record.id][year]['cost'] += month_data.get('org_cost', 0) or 0
    
    sorted_years = sorted(list(all_years))
    
    for year in sorted_years:
        header.extend([f'{year} Traffic', f'{year} Value', f'{year} Avg Monthly Traffic'])
    
    writer.writerow(header)
    
    for record in data_records:
        row = [record.url.url, record.fetched_at]
        
        current_metrics = record.get_current_metrics()
        if current_metrics and 'metrics' in current_metrics:
            metrics = current_metrics['metrics']
            row.extend([
                metrics.get('org_keywords', ''),
                metrics.get('org_keywords_1_3', ''),
                metrics.get('org_traffic', ''),
                metrics.get('org_cost', '')
            ])
        else:
            row.extend(['', '', '', ''])
        
        domain_rating = record.get_domain_rating()
        if domain_rating and 'domain_rating' in domain_rating:
            dr_data = domain_rating['domain_rating']
            row.extend([
                dr_data.get('domain_rating', ''),
                dr_data.get('ahrefs_rank', '')
            ])
        else:
            row.extend(['', ''])
        
        backlinks_stats = record.get_backlinks_stats()
        if backlinks_stats and 'metrics' in backlinks_stats:
            bl_data = backlinks_stats['metrics']
            row.extend([
                bl_data.get('live', ''),
                bl_data.get('all_time', ''),
                bl_data.get('live_refdomains', ''),
                bl_data.get('all_time_refdomains', '')
            ])
        else:
            row.extend(['', '', '', ''])
        
        top_keywords_str = ''
        top_keywords = record.get_top_keywords()
        if top_keywords and 'keywords' in top_keywords:
            keywords_list = []
            for i, kw in enumerate(top_keywords['keywords'][:10]):
                keyword = kw.get('keyword', '')
                traffic = kw.get('sum_traffic', 0)
                keywords_list.append(f"{keyword} ({traffic})")
            top_keywords_str = '; '.join(keywords_list)
        row.append(top_keywords_str)
        
        country_percentages_str = ''
        country_data = record.get_country_metrics()
        if country_data and 'metrics' in country_data:
            total_traffic = sum(c.get('org_traffic', 0) for c in country_data['metrics'])
            if total_traffic > 0:
                country_list = []
                other_percentage = 0
                for country in country_data['metrics']:
                    country_name = country.get('country', '')
                    traffic = country.get('org_traffic', 0)
                    percentage = (traffic / total_traffic) * 100
                    if percentage >= 0.1 and country_name:
                        country_list.append(f"{country_name}: {percentage:.1f}%")
                    else:
                        other_percentage += percentage
                
                if other_percentage > 0:
                    country_list.append(f"Other: {other_percentage:.1f}%")
                
                country_percentages_str = '; '.join(country_list)
        row.append(country_percentages_str)
        
        for year in sorted_years:
            if year in yearly_data_by_record[record.id]:
                year_data = yearly_data_by_record[record.id][year]
                avg_monthly_traffic = year_data['traffic'] / 12 if year_data['traffic'] > 0 else 0
                row.extend([year_data['traffic'], year_data['cost'], round(avg_monthly_traffic, 2)])
            else:
                row.extend(['', '', ''])
        
        writer.writerow(row)
    
    output.seek(0)
    return send_file(
        BytesIO(output.getvalue().encode()),
        mimetype='text/csv',
        as_attachment=True,
        download_name=f'ahrefs_data_export_{datetime.now().strftime("%Y%m%d_%H%M%S")}.csv'
    )

@app.route('/export/scraper_data')
@login_required
def export_scraper_data():
    source_filter = request.args.get('source', '')
    
    query = ScrapedData.query
    if source_filter:
        query = query.filter_by(source=source_filter)
    
    records = query.all()
    
    output = StringIO()
    writer = csv.writer(output)
    
    writer.writerow([
        'URL', 'Categories', 'Language', 'Ahrefs_Traffic', 'Similarweb_Traffic', 
        'SemRush_Traffic', 'Ahrefs_DR', 'Referral_Domains', 'Content_Placement_Price',
        'Writing_Placement_Price', 'Moz_DA', 'SemRush_AS', 'Completion_Rate',
        'Link_Lifetime', 'TAT_Days', 'Link_Type', 'Sponsored_Required',
        'Content_Size', 'Spam_Score', 'Description'
    ])
    
    for record in records:
        writer.writerow([
            record.url,
            record.categories or '',
            record.language or '',
            record.ahrefs_traffic or '',
            record.similarweb_traffic or '',
            record.semrush_traffic or '',
            record.ahrefs_dr or '',
            record.referral_domains or '',
            record.content_placement_price or '',
            record.writing_placement_price or '',
            record.moz_da or '',
            record.semrush_as or '',
            record.completion_rate or '',
            record.link_lifetime or '',
            record.tat_days or '',
            record.link_type or '',
            record.sponsored_required or '',
            record.content_size or '',
            record.spam_score or '',
            record.description or ''
        ])
    
    output.seek(0)
    
    mem_file = BytesIO()
    mem_file.write(output.getvalue().encode('utf-8'))
    mem_file.seek(0)
    
    filename = f"scraped_data_{source_filter or 'all'}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    
    return send_file(
        mem_file,
        mimetype='text/csv',
        as_attachment=True,
        download_name=filename
    )

@app.route('/export/suppression')
@login_required
def export_suppression():
    suppression_list = SuppressionList.query.all()
    output = StringIO()
    writer = csv.writer(output)
    writer.writerow(['URL', 'Reason', 'Created At'])
    
    for item in suppression_list:
        writer.writerow([item.url, item.reason or '', item.created_at])
    
    output.seek(0)
    return send_file(
        BytesIO(output.getvalue().encode()),
        mimetype='text/csv',
        as_attachment=True,
        download_name=f'suppression_export_{datetime.now().strftime("%Y%m%d_%H%M%S")}.csv'
    )

@app.context_processor
def inject_user():
    return {
        'current_user': session.get('username'),
        'is_authenticated': check_auth(),
        'login_time': session.get('login_time')
    }

@app.errorhandler(404)
def not_found(error):
    if not check_auth():
        return redirect(url_for('login'))
    return render_template('404.html'), 404

@app.errorhandler(500)
def internal_error(error):
    db.session.rollback()
    if not check_auth():
        return redirect(url_for('login'))
    return render_template('500.html'), 500

@app.route('/scraper/execute')
@login_required
def scraper_execute():
    scraped_data = ScrapedData.query.order_by(ScrapedData.created_at.desc()).limit(100).all()
    recent_sessions = ScrapingSession.query.order_by(ScrapingSession.started_at.desc()).limit(10).all()
    
    return render_template('scraper/execute.html', 
                         scraped_data=scraped_data,
                         recent_sessions=recent_sessions,
                         scraping_stats=scraping_stats)

@app.route('/scraper/api/record/<int:record_id>')
@login_required
def scraper_api_record(record_id):
    record = ScrapedData.query.get_or_404(record_id)
    return jsonify({
        'success': True,
        'record': {
            'id': record.id,
            'url': record.url,
            'source': record.source,
            'categories': record.categories,
            'language': record.language,
            'monthly_traffic': record.monthly_traffic,
            'ahrefs_traffic': record.ahrefs_traffic,
            'similarweb_traffic': record.similarweb_traffic,
            'semrush_traffic': record.semrush_traffic,
            'ahrefs_dr': record.ahrefs_dr,
            'moz_da': record.moz_da,
            'referral_domains': record.referral_domains,
            'content_placement_price': record.content_placement_price,
            'writing_placement_price': record.writing_placement_price,
            'semrush_as': record.semrush_as,
            'completion_rate': record.completion_rate,
            'link_lifetime': record.link_lifetime,
            'tat_days': record.tat_days,
            'link_type': record.link_type,
            'sponsored_required': record.sponsored_required,
            'content_size': record.content_size,
            'spam_score': record.spam_score,
            'description': record.description,
            'created_at': record.created_at.isoformat()
        }
    })

@app.route('/scraper/delete-record', methods=['POST'])
@login_required
def scraper_delete_record():
    data = request.get_json()
    record_id = data.get('id')
    
    record = ScrapedData.query.get(record_id)
    if record:
        db.session.delete(record)
        db.session.commit()
        return jsonify({'success': True, 'message': 'Record deleted successfully'})
    else:
        return jsonify({'success': False, 'message': 'Record not found'})

@app.route('/scraper/bulk-remove', methods=['POST'])
@login_required
def scraper_bulk_remove():
    data = request.get_json()
    target = data.get('target')
    urls = data.get('urls', [])
    
    removed_count = 0
    
    if target == 'data':
        for url in urls:
            records = ScrapedData.query.filter_by(url=url).all()
            for record in records:
                db.session.delete(record)
                removed_count += 1
    elif target == 'suppression':
        for url in urls:
            suppressed = SuppressionList.query.filter_by(url=url).all()
            for item in suppressed:
                db.session.delete(item)
                removed_count += 1
    
    db.session.commit()
    return jsonify({'success': True, 'message': f'Removed {removed_count} items from {target}'})

@app.route('/scraper/clear-data', methods=['POST'])
@login_required
def scraper_clear_data():
    try:
        count = ScrapedData.query.count()
        ScrapedData.query.delete()
        db.session.commit()
        return jsonify({'success': True, 'message': f'Cleared {count} data records'})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': f'Error clearing data: {str(e)}'})

@app.route('/scraper/api/failed-sessions')
@login_required
def scraper_api_failed_sessions():
    failed_sessions = ScrapingSession.query.filter_by(status='failed').order_by(ScrapingSession.started_at.desc()).limit(20).all()
    
    sessions_data = []
    for session in failed_sessions:
        sessions_data.append({
            'id': session.id,
            'source': session.source,
            'start_page': session.start_page,
            'pages_to_scrape': session.pages_to_scrape,
            'records_scraped': session.records_scraped,
            'started_at': session.started_at.isoformat(),
            'error_message': session.error_message
        })
    
    return jsonify({'success': True, 'sessions': sessions_data})

@app.route('/scraper/retry-session', methods=['POST'])
@login_required
def scraper_retry_session():
    data = request.get_json()
    session_id = data.get('session_id')
    
    old_session = ScrapingSession.query.get(session_id)
    if not old_session:
        return jsonify({'success': False, 'message': 'Session not found'})
    
    if scraping_stats['is_running']:
        return jsonify({'success': False, 'message': 'Another scraper is already running'})
    
    new_session = ScrapingSession(
        source=old_session.source,
        start_page=old_session.start_page,
        pages_to_scrape=old_session.pages_to_scrape
    )
    db.session.add(new_session)
    db.session.commit()
    
    scraping_stats['current_session'] = new_session.id
    
    thread = threading.Thread(target=run_scraper_thread, args=(
        old_session.source, 
        old_session.start_page, 
        old_session.pages_to_scrape, 
        new_session.id
    ))
    thread.daemon = True
    thread.start()
    
    return jsonify({'success': True, 'message': 'Retry session started'})

@app.route('/api/suppression-stats')
@login_required
def api_suppression_stats():
    stats = get_suppression_stats()
    return jsonify(stats)

@app.route('/api/search-urls')
@login_required
def api_search_urls():
    source = request.args.get('source', '')
    search_term = request.args.get('term', '')
    
    try:
        urls = get_urls_from_source(source, search_term)
        return jsonify({'success': True, 'urls': urls[:100]})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

with app.app_context():
    db.create_all()
    create_admin_user()
    
    os.makedirs('static/screenshots', exist_ok=True)
    
    try:
        from database import OutreachConfig
        existing_config = OutreachConfig.query.filter_by(is_default=True).first()
        if not existing_config:
            default_config = OutreachConfig(is_default=True)
            default_config.set_config_data({
                'first_name': '',
                'last_name': '',
                'email': '',
                'message': '',
                'delay_between_requests': 3,
                'custom_fields': []
            })
            db.session.add(default_config)
            db.session.commit()
    except Exception as e:
        print(f"Migration error: {e}")
    
@app.route('/dupe-checker')
@login_required
def dupe_checker():
    return render_template('dupe_checker.html')

@app.route('/dupe-checker/process', methods=['POST'])
@login_required
def process_duplicates():
    try:
        data = request.get_json()
        primary_csv = data.get('primary_csv', '')
        secondary_csv = data.get('secondary_csv', '')
        
        if not primary_csv or not secondary_csv:
            return jsonify({'success': False, 'message': 'Both CSV files are required'})
        
        cleaned_data, removed_count, duplicate_urls = find_duplicates(primary_csv, secondary_csv)
        clean_csv = generate_clean_csv(cleaned_data)
        duplicates_csv = generate_clean_csv(duplicate_urls) if duplicate_urls else ''
        
        return jsonify({
            'success': True,
            'cleaned_csv': clean_csv,
            'duplicates_csv': duplicates_csv,
            'removed_count': removed_count,
            'final_count': len(cleaned_data)
        })
        
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})

@app.route('/ahrefs/sync-to-sheets', methods=['POST'])
@login_required
def sync_to_sheets():
    data = request.get_json()
    selected_ids = data.get('selected_ids', [])
    
    if not selected_ids:
        url_data_records = URLData.query.all()
    else:
        url_data_records = URLData.query.filter(URLData.id.in_(selected_ids)).all()
    
    success_count = 0
    for record in url_data_records:
        try:
            if sheets_api.update_ahrefs_data(record):
                success_count += 1
        except Exception:
            continue
    
    return jsonify({
        'success': True, 
        'message': f'Synced {success_count} records to Google Sheets'
    })

@app.route('/ahrefs/import-single-to-outreach', methods=['POST'])
@login_required
def ahrefs_import_single_to_outreach():
    data = request.get_json()
    url_data_id = data.get('url_data_id')
    
    url_data = URLData.query.get(url_data_id)
    if not url_data:
        return jsonify({'success': False, 'message': 'URL data not found'})
    
    url = url_data.url.url
    
    if is_url_suppressed(url):
        return jsonify({'success': False, 'message': 'URL is in suppression list'})
    
    existing = OutreachData.query.filter_by(url=url).first()
    if existing:
        return jsonify({'success': False, 'message': 'URL already exists in outreach'})
    
    outreach_record = OutreachData(url=url, status='pending')
    db.session.add(outreach_record)
    db.session.commit()
    
    return jsonify({'success': True, 'message': 'URL imported to outreach successfully'})

@app.route('/ahrefs/save-filters', methods=['POST'])
@login_required
def ahrefs_save_filters():
    data = request.get_json()
    filters = data.get('filters', [])
    
    session['ahrefs_data_filters'] = filters
    return jsonify({'success': True, 'message': 'Filters saved'})

@app.route('/ahrefs/get-filters')
@login_required
def ahrefs_get_filters():
    filters = session.get('ahrefs_data_filters', [])
    return jsonify({'success': True, 'filters': filters})

@app.route('/ahrefs/clear-filters', methods=['POST'])
@login_required
def ahrefs_clear_filters():
    session.pop('ahrefs_data_filters', None)
    return jsonify({'success': True, 'message': 'Filters cleared'})

@app.route('/email-extraction')
@login_required
def email_extraction():
    total_emails = ExtractedEmail.query.filter(ExtractedEmail.emails.isnot(None)).count()
    total_processed = ExtractedEmail.query.count()
    success_rate = round((total_emails / total_processed * 100), 1) if total_processed > 0 else 0
    
    last_record = ExtractedEmail.query.order_by(ExtractedEmail.created_at.desc()).first()
    last_run = last_record.created_at.strftime('%Y-%m-%d %H:%M') if last_record else 'Never'
    
    stats = {
        'total_emails': total_emails,
        'total_processed': total_processed,
        'success_rate': success_rate,
        'last_run': last_run
    }
    
    return render_template('email_extraction/execute.html', stats=stats)

@app.route('/email-extraction/import-urls', methods=['POST'])
@login_required
def email_extraction_import():
    data = request.get_json()
    source_type = data.get('source_type')
    manual_urls = data.get('manual_urls', '')
    csv_data = data.get('csv_data', '')
    source_filter = data.get('source_filter', 'all')
    search_term = data.get('search_term', '')
    
    urls = []
    
    if source_type == 'manual' and manual_urls:
        urls = [url.strip() for url in manual_urls.split('\n') if url.strip()]
    
    elif source_type == 'csv' and csv_data:
        try:
            csv_reader = csv.DictReader(StringIO(csv_data))
            for row in csv_reader:
                url = row.get('URL', '').strip()
                if url:
                    urls.append(url)
        except Exception as e:
            return jsonify({'success': False, 'message': f'CSV error: {str(e)}'})
    
    elif source_type == 'scraped':
        query = ScrapedData.query
        if source_filter != 'all':
            query = query.filter_by(source=source_filter)
        if search_term:
            query = query.filter(ScrapedData.url.contains(search_term))
        
        scraped_items = query.limit(500).all()
        urls = [item.url for item in scraped_items]
    
    elif source_type == 'ahrefs_data':
        query = URLData.query.join(URL)
        if search_term:
            query = query.filter(URL.url.contains(search_term))
        
        ahrefs_items = query.limit(500).all()
        urls = [item.url.url for item in ahrefs_items]
    
    urls = filter_urls_by_suppression(urls)
    return jsonify({'success': True, 'urls': urls, 'count': len(urls)})

@app.route('/email-extraction/start', methods=['POST'])
@login_required
def email_extraction_start():
    data = request.get_json()
    urls = data.get('urls', [])
    
    if not urls:
        return jsonify({'success': False, 'message': 'No URLs provided'})
    
    success = email_extractor.start_extraction(urls, app)
    return jsonify({'success': success, 'message': 'Extraction started' if success else 'Already running'})

@app.route('/email-extraction/stop', methods=['POST'])
@login_required
def email_extraction_stop():
    success = email_extractor.stop_extraction()
    return jsonify({'success': success, 'message': 'Extraction stopped' if success else 'Not running'})

@app.route('/email-extraction/stats')
@login_required
def email_extraction_stats_api():
    return jsonify(email_extractor.stats)

@app.route('/extracted-emails')
@login_required
def extracted_emails():
    page = request.args.get('page', 1, type=int)
    search = request.args.get('search', '', type=str)
    status_filter = request.args.get('status', '', type=str)
    
    query = ExtractedEmail.query
    
    if search:
        query = query.filter(
            db.or_(
                ExtractedEmail.url.contains(search),
                ExtractedEmail.email.contains(search)
            )
        )
    
    if status_filter:
        query = query.filter_by(status=status_filter)
    
    pagination = query.order_by(ExtractedEmail.created_at.desc()).paginate(
        page=page, per_page=50, error_out=False
    )
    
    return render_template('email_extraction/emails.html', pagination=pagination, search=search, status_filter=status_filter)

@app.route('/extracted-emails/delete', methods=['POST'])
@login_required
def delete_extracted_email():
    data = request.get_json()
    email_ids = data.get('ids', [])
    
    deleted_count = 0
    for email_id in email_ids:
        record = ExtractedEmail.query.get(email_id)
        if record:
            db.session.delete(record)
            deleted_count += 1
    
    db.session.commit()
    return jsonify({'success': True, 'deleted': deleted_count})

@app.route('/export/extracted_emails')
@login_required
def export_extracted_emails():
    records = ExtractedEmail.query.all()
    
    output = StringIO()
    writer = csv.writer(output)
    writer.writerow(['URL', 'Emails', 'Status', 'Error Message', 'Created At'])
    
    for record in records:
        emails = record.get_emails()
        emails_str = '; '.join(emails) if emails else ''
        writer.writerow([
            record.url,
            emails_str,
            record.status,
            record.error_message or '',
            record.created_at
        ])
    
    output.seek(0)
    return send_file(
        BytesIO(output.getvalue().encode()),
        mimetype='text/csv',
        as_attachment=True,
        download_name=f'extracted_emails_{datetime.now().strftime("%Y%m%d_%H%M%S")}.csv'
    )

@app.route('/email-extraction/start-hunter', methods=['POST'])
@login_required
def email_extraction_start_hunter():
    data = request.get_json()
    urls = data.get('urls', [])
    
    if not urls:
        return jsonify({'success': False, 'message': 'No URLs provided'})
    
    success = hunter_extractor.start_extraction(urls, app)
    return jsonify({'success': success, 'message': 'Hunter extraction started' if success else 'Already running'})

@app.route('/email-extraction/stop-hunter', methods=['POST'])
@login_required
def email_extraction_stop_hunter():
    success = hunter_extractor.stop_extraction()
    return jsonify({'success': success, 'message': 'Hunter extraction stopped' if success else 'Not running'})

@app.route('/email-extraction/stats-hunter')
@login_required
def email_extraction_stats_hunter():
    return jsonify(hunter_extractor.stats)

@app.route('/system-stats')
@login_required
def system_stats_page():
    return render_template('system_stats.html')

@app.route('/api/system-stats')
@login_required
def api_system_stats():
    try:
        stats = system_stats.get_all_stats()
        return jsonify({'success': True, 'stats': stats})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})
    
@app.route('/email-outreach')
@login_required
def email_outreach():
    total_emails = EmailOutreach.query.count()
    pending_emails = EmailOutreach.query.filter_by(status='pending').count()
    sent_emails = EmailOutreach.query.filter_by(status='sent').count()
    failed_emails = EmailOutreach.query.filter_by(status='failed').count()
    
    credentials = EmailCredentials.query.all()
    default_credentials = EmailCredentials.query.filter_by(is_default=True).first()
    
    stats = {
        'total_emails': total_emails,
        'pending_emails': pending_emails,
        'sent_emails': sent_emails,
        'failed_emails': failed_emails,
        'credentials_count': len(credentials),
        'has_default_credentials': default_credentials is not None
    }
    
    return render_template('email_outreach/execute.html', 
                         stats=stats, 
                         credentials=credentials,
                         email_sender_stats=email_sender.stats)

@app.route('/email-outreach/import-emails', methods=['POST'])
@login_required
def email_outreach_import():
    data = request.get_json()
    source_type = data.get('source_type')
    selected_ids = data.get('selected_ids', [])
    one_email_per_url = data.get('one_email_per_url', True)
    
    added_count = 0
    
    if source_type == 'extracted_emails':
        if selected_ids:
            extracted = ExtractedEmail.query.filter(ExtractedEmail.id.in_(selected_ids)).all()
        else:
            extracted = ExtractedEmail.query.filter(ExtractedEmail.emails.isnot(None)).all()
        
        for record in extracted:
            emails = record.get_emails()
            if one_email_per_url and emails:
                best_email = select_best_email(emails)
                emails = [best_email]
            
            for email in emails:
                if not is_url_suppressed(email):
                    existing = EmailOutreach.query.filter_by(email=email, url=record.url).first()
                    if not existing:
                        outreach_record = EmailOutreach(
                            email=email,
                            url=record.url,
                            subject='',
                            message='',
                            execution_mode='automatic',
                            status='pending'
                        )
                        db.session.add(outreach_record)
                        added_count += 1
    
    db.session.commit()
    return jsonify({'success': True, 'message': f'Imported {added_count} emails', 'count': added_count})

@app.route('/email-outreach/update-template', methods=['POST'])
@login_required
def email_outreach_update_template():
    data = request.get_json()
    email_ids = data.get('email_ids', [])
    subject = data.get('subject', '')
    message = data.get('message', '')
    
    if not email_ids:
        query = EmailOutreach.query.filter_by(status='pending')
    else:
        query = EmailOutreach.query.filter(EmailOutreach.id.in_(email_ids))
    
    updated = 0
    for record in query.all():
        record.subject = subject
        record.message = process_message_template(message, record.url)
        updated += 1
    
    db.session.commit()
    return jsonify({'success': True, 'message': f'Updated {updated} emails'})

@app.route('/email-outreach/update-email', methods=['POST'])
@login_required
def email_outreach_update():
    data = request.get_json()
    email_id = data.get('email_id')
    subject = data.get('subject')
    message = data.get('message')
    
    record = EmailOutreach.query.get(email_id)
    if record:
        record.subject = subject
        record.message = process_message_template(message, record.url)
        db.session.commit()
        return jsonify({'success': True, 'message': 'Email updated'})
    
    return jsonify({'success': False, 'message': 'Email not found'})

@app.route('/email-outreach/delete-emails', methods=['POST'])
@login_required
def email_outreach_delete():
    data = request.get_json()
    email_ids = data.get('ids', [])
    
    deleted_count = 0
    for email_id in email_ids:
        record = EmailOutreach.query.get(email_id)
        if record:
            db.session.delete(record)
            deleted_count += 1
    
    db.session.commit()
    return jsonify({'success': True, 'deleted': deleted_count})

@app.route('/email-outreach/get-emails', methods=['GET'])
@login_required
def email_outreach_get_emails():
    status = request.args.get('status', None)
    limit = request.args.get('limit', 50, type=int)
    
    query = EmailOutreach.query
    if status:
        query = query.filter_by(status=status)
    
    emails = query.order_by(EmailOutreach.id.desc()).limit(limit).all()
    
    email_list = []
    for email in emails:
        email_list.append({
            'id': email.id,
            'email': email.email,
            'url': email.url,
            'subject': email.subject,
            'message': email.message,
            'status': email.status,
            'sent_at': email.sent_at.isoformat() if email.sent_at else None
        })
    
    return jsonify({'success': True, 'emails': email_list})

@app.route('/email-outreach/import-from-file', methods=['POST'])
@login_required
def email_outreach_import_file():
    if 'email_file' not in request.files:
        return jsonify({'success': False, 'message': 'No file uploaded'})
    
    file = request.files['email_file']
    if not file or not (file.filename.endswith('.csv') or file.filename.endswith('.xlsx') or file.filename.endswith('.xls')):
        return jsonify({'success': False, 'message': 'Invalid file format. Please upload CSV or Excel file.'})
    
    filename = secure_filename(file.filename)
    filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
    
    os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
    file.save(filepath)
    
    added_count = 0
    skipped_count = 0
    
    try:
        # Handle Excel files
        if file.filename.endswith('.xlsx') or file.filename.endswith('.xls'):
            df = pd.read_excel(filepath)
            
            # Check for required columns (case-insensitive)
            df.columns = df.columns.str.strip()
            email_col = None
            url_col = None
            
            for col in df.columns:
                if col.lower() in ['email', 'emails']:
                    email_col = col
                if col.lower() in ['url', 'website', 'domain']:
                    url_col = col
            
            if not email_col:
                os.remove(filepath)
                return jsonify({'success': False, 'message': 'File must contain an "Email" column'})
            
            for _, row in df.iterrows():
                if pd.notna(row[email_col]):
                    email = str(row[email_col]).strip()
                    url = str(row[url_col]).strip() if url_col and pd.notna(row.get(url_col)) else ''
                    
                    if email and '@' in email:
                        existing = EmailOutreach.query.filter_by(email=email).first()
                        if not existing:
                            outreach_record = EmailOutreach(
                                email=email,
                                url=url,
                                subject='',
                                message='',
                                execution_mode='automatic',
                                status='pending'
                            )
                            db.session.add(outreach_record)
                            added_count += 1
                        else:
                            skipped_count += 1
        
        # Handle CSV files
        else:
            with open(filepath, 'r', encoding='utf-8') as csvfile:
                reader = csv.DictReader(csvfile)
                headers = [h.strip() for h in reader.fieldnames]
                
                email_col = None
                url_col = None
                
                for header in headers:
                    if header.lower() in ['email', 'emails']:
                        email_col = header
                    if header.lower() in ['url', 'website', 'domain']:
                        url_col = header
                
                if not email_col:
                    os.remove(filepath)
                    return jsonify({'success': False, 'message': 'File must contain an "Email" column'})
                
                for row in reader:
                    email = row.get(email_col, '').strip()
                    url = row.get(url_col, '').strip() if url_col else ''
                    
                    if email and '@' in email:
                        existing = EmailOutreach.query.filter_by(email=email).first()
                        if not existing:
                            outreach_record = EmailOutreach(
                                email=email,
                                url=url,
                                subject='',
                                message='',
                                execution_mode='automatic',
                                status='pending'
                            )
                            db.session.add(outreach_record)
                            added_count += 1
                        else:
                            skipped_count += 1
        
        db.session.commit()
        os.remove(filepath)
        
        message = f'Imported {added_count} emails'
        if skipped_count > 0:
            message += f' (skipped {skipped_count} duplicates)'
        
        return jsonify({'success': True, 'message': message, 'added': added_count, 'skipped': skipped_count})
    
    except Exception as e:
        if os.path.exists(filepath):
            os.remove(filepath)
        return jsonify({'success': False, 'message': f'Error processing file: {str(e)}'})

@app.route('/email-outreach/credentials', methods=['GET', 'POST'])
@login_required
def email_outreach_credentials():
    if request.method == 'POST':
        data = request.get_json()
        action = data.get('action')
        
        if action == 'add':
            email = data.get('email')
            password = data.get('password')
            smtp_server = data.get('smtp_server')
            smtp_port = data.get('smtp_port')
            is_default = data.get('is_default', False)
            
            if is_default:
                EmailCredentials.query.update({'is_default': False})
            
            credentials = EmailCredentials(
                email=email,
                password=password,
                smtp_server=smtp_server,
                smtp_port=smtp_port,
                is_default=is_default
            )
            db.session.add(credentials)
            db.session.commit()
            return jsonify({'success': True, 'message': 'Credentials added'})
        
        elif action == 'delete':
            cred_id = data.get('id')
            credentials = EmailCredentials.query.get(cred_id)
            if credentials:
                db.session.delete(credentials)
                db.session.commit()
                return jsonify({'success': True, 'message': 'Credentials deleted'})
        
        elif action == 'set_default':
            cred_id = data.get('id')
            EmailCredentials.query.update({'is_default': False})
            credentials = EmailCredentials.query.get(cred_id)
            if credentials:
                credentials.is_default = True
                db.session.commit()
                return jsonify({'success': True, 'message': 'Default credentials updated'})
    
    credentials = EmailCredentials.query.all()
    return jsonify({'success': True, 'credentials': [
        {
            'id': c.id,
            'email': c.email,
            'smtp_server': c.smtp_server,
            'smtp_port': c.smtp_port,
            'is_default': c.is_default
        } for c in credentials
    ]})

@app.route('/email-outreach/start-sending', methods=['POST'])
@login_required
def email_outreach_start():
    data = request.get_json()
    email_ids = data.get('email_ids', [])
    credentials_id = data.get('credentials_id')
    delay_seconds = data.get('delay_seconds', 5)
    
    # If no specific emails selected, get all pending emails
    if not email_ids:
        pending_emails = EmailOutreach.query.filter_by(status='pending').all()
        email_ids = [email.id for email in pending_emails]
        
        if not email_ids:
            return jsonify({'success': False, 'message': 'No pending emails to send'})
    
    if not credentials_id:
        default_cred = EmailCredentials.query.filter_by(is_default=True).first()
        if default_cred:
            credentials_id = default_cred.id
        else:
            return jsonify({'success': False, 'message': 'No email credentials found. Please add credentials first.'})
    
    success = email_sender.start_sending(email_ids, credentials_id, delay_seconds, app)
    
    if success:
        return jsonify({'success': True, 'message': f'Started sending {len(email_ids)} email(s)'})
    else:
        return jsonify({'success': False, 'message': 'Email sending is already running'})

@app.route('/email-outreach/stop-sending', methods=['POST'])
@login_required
def email_outreach_stop():
    success = email_sender.stop_sending()
    return jsonify({'success': success, 'message': 'Sending stopped'})

@app.route('/email-outreach/stats')
@login_required
def email_outreach_stats_api():
    return jsonify(email_sender.stats)

@app.route('/email-outreach/save-template', methods=['POST'])
@login_required
def email_outreach_save_template():
    data = request.get_json()
    template_name = data.get('template_name')
    subject = data.get('subject')
    message = data.get('message')
    
    template = EmailTemplate(
        name=template_name,
        subject=subject,
        message=message
    )
    db.session.add(template)
    db.session.commit()
    return jsonify({'success': True, 'message': 'Template saved'})

@app.route('/email-outreach/templates')
@login_required
def email_outreach_templates():
    templates = EmailTemplate.query.all()
    return jsonify({'success': True, 'templates': [
        {
            'id': t.id,
            'name': t.name,
            'subject': t.subject,
            'message': t.message
        } for t in templates
    ]})

@app.route('/email-outreach/delete-template/<int:template_id>', methods=['POST'])
@login_required
def email_outreach_delete_template(template_id):
    template = EmailTemplate.query.get(template_id)
    if template:
        db.session.delete(template)
        db.session.commit()
        return jsonify({'success': True, 'message': 'Template deleted'})
    return jsonify({'success': False, 'message': 'Template not found'})

@app.route('/export/email_outreach')
@login_required
def export_email_outreach():
    records = EmailOutreach.query.all()
    
    output = StringIO()
    writer = csv.writer(output)
    writer.writerow(['Email', 'URL', 'Subject', 'Message', 'Status', 'Execution Mode', 'Sent At', 'Error Message', 'Created At'])
    
    for record in records:
        writer.writerow([
            record.email,
            record.url,
            record.subject,
            record.message,
            record.status,
            record.execution_mode,
            record.sent_at or '',
            record.error_message or '',
            record.created_at
        ])
    
    output.seek(0)
    return send_file(
        BytesIO(output.getvalue().encode()),
        mimetype='text/csv',
        as_attachment=True,
        download_name=f'email_outreach_{datetime.now().strftime("%Y%m%d_%H%M%S")}.csv'
    )

def select_best_email(emails):
    priority_keywords = ['info', 'contact', 'hello', 'support', 'admin']
    
    for keyword in priority_keywords:
        for email in emails:
            if keyword in email.lower():
                return email
    
    return emails[0] if emails else None

def process_message_template(message, url):
    company_name = extract_company_name(url)
    
    replacements = {
        '(company)': company_name,
        '(Company)': company_name.capitalize(),
        '(COMPANY)': company_name.upper(),
        '(domain)': url.replace('http://', '').replace('https://', '').replace('www.', '').split('/')[0]
    }
    
    processed_message = message
    for placeholder, value in replacements.items():
        processed_message = processed_message.replace(placeholder, value)
    
    return processed_message

def extract_company_name(url):
    domain = url.replace('http://', '').replace('https://', '').replace('www.', '').split('/')[0]
    name = domain.split('.')[0]
    return name.replace('-', ' ').replace('_', ' ').title()

@app.route('/email-outreach/stats-page')
@login_required
def email_outreach_stats_page():
    return render_template('email_outreach/stats.html')

@app.route('/api/email-outreach-stats')
@login_required
def api_email_outreach_stats():
    from datetime import datetime, timedelta
    
    total = EmailOutreach.query.count()
    sent = EmailOutreach.query.filter_by(status='sent').count()
    failed = EmailOutreach.query.filter_by(status='failed').count()
    success_rate = f"{round((sent / total * 100), 1)}%" if total > 0 else "0%"
    
    today = datetime.now().date()
    today_sent = EmailOutreach.query.filter(
        EmailOutreach.status == 'sent',
        db.func.date(EmailOutreach.sent_at) == today
    ).count()
    
    week_ago = today - timedelta(days=7)
    week_sent = EmailOutreach.query.filter(
        EmailOutreach.status == 'sent',
        db.func.date(EmailOutreach.sent_at) >= week_ago
    ).count()
    
    month_ago = today - timedelta(days=30)
    month_sent = EmailOutreach.query.filter(
        EmailOutreach.status == 'sent',
        db.func.date(EmailOutreach.sent_at) >= month_ago
    ).count()
    
    avg_per_day = round(month_sent / 30, 1) if month_sent > 0 else 0
    
    return jsonify({
        'total': total,
        'sent': sent,
        'failed': failed,
        'success_rate': success_rate,
        'today_sent': today_sent,
        'week_sent': week_sent,
        'month_sent': month_sent,
        'avg_per_day': avg_per_day
    })

@app.route('/api/email-outreach-data')
@login_required
def api_email_outreach_data():
    page = request.args.get('page', 1, type=int)
    search = request.args.get('search', '', type=str)
    status = request.args.get('status', '', type=str)
    date = request.args.get('date', '', type=str)
    per_page = 50
    
    query = EmailOutreach.query
    
    if search:
        query = query.filter(
            db.or_(
                EmailOutreach.email.contains(search),
                EmailOutreach.url.contains(search)
            )
        )
    
    if status:
        query = query.filter_by(status=status)
    
    if date:
        query = query.filter(db.func.date(EmailOutreach.created_at) == date)
    
    pagination = query.order_by(EmailOutreach.created_at.desc()).paginate(
        page=page, per_page=per_page, error_out=False
    )
    
    records = []
    for record in pagination.items:
        records.append({
            'id': record.id,
            'email': record.email,
            'url': record.url,
            'subject': record.subject,
            'message': record.message,
            'status': record.status,
            'sent_at': record.sent_at.isoformat() if record.sent_at else None,
            'error_message': record.error_message,
            'created_at': record.created_at.isoformat()
        })
    
    return jsonify({
        'records': records,
        'total': pagination.total,
        'page': page,
        'per_page': per_page,
        'pages': pagination.pages
    })

@app.route('/ahrefs/archive-data', methods=['POST'])
@login_required
def ahrefs_archive_data():
    data = request.get_json()
    data_ids = data.get('ids', [])
    
    archived_count = 0
    for data_id in data_ids:
        url_data = URLData.query.get(data_id)
        if url_data:
            archived = ArchivedURLData(
                original_url_data_id=url_data.id,
                url=url_data.url.url,
                current_metrics=url_data.current_metrics,
                domain_rating=url_data.domain_rating,
                backlinks_stats=url_data.backlinks_stats,
                historical_metrics=url_data.historical_metrics,
                top_keywords=url_data.top_keywords,
                country_metrics=url_data.country_metrics,
                original_fetched_at=url_data.fetched_at
            )
            db.session.add(archived)
            db.session.delete(url_data)
            archived_count += 1
    
    db.session.commit()
    return jsonify({'success': True, 'archived': archived_count})

@app.route('/ahrefs/archived')
@login_required
def ahrefs_archived():
    page = request.args.get('page', 1, type=int)
    search = request.args.get('search', '', type=str)
    
    query = ArchivedURLData.query
    if search:
        query = query.filter(ArchivedURLData.url.contains(search))
    
    data_pagination = query.order_by(ArchivedURLData.archived_at.desc()).paginate(
        page=page, per_page=20, error_out=False
    )
    
    return render_template('ahrefs/archived.html', data=data_pagination, search=search)

@app.route('/ahrefs/view_archived/<int:data_id>')
@login_required
def ahrefs_view_archived(data_id):
    archived_data = ArchivedURLData.query.get_or_404(data_id)
    return jsonify({
        'url': archived_data.url,
        'data': archived_data.get_all_data(),
        'archived_at': archived_data.archived_at.isoformat(),
        'original_fetched_at': archived_data.original_fetched_at.isoformat() if archived_data.original_fetched_at else None
    })

@app.route('/ahrefs/restore-archived', methods=['POST'])
@login_required
def ahrefs_restore_archived():
    data = request.get_json()
    archived_ids = data.get('ids', [])
    
    restored_count = 0
    for archived_id in archived_ids:
        archived = ArchivedURLData.query.get(archived_id)
        if archived:
            url_obj = URL.query.filter_by(url=archived.url).first()
            if not url_obj:
                url_obj = URL(url=archived.url)
                db.session.add(url_obj)
                db.session.flush()
            
            existing_data = URLData.query.filter_by(url_id=url_obj.id).first()
            if not existing_data:
                restored = URLData(
                    url_id=url_obj.id,
                    current_metrics=archived.current_metrics,
                    domain_rating=archived.domain_rating,
                    backlinks_stats=archived.backlinks_stats,
                    historical_metrics=archived.historical_metrics,
                    top_keywords=archived.top_keywords,
                    country_metrics=archived.country_metrics,
                    fetched_at=archived.original_fetched_at or datetime.utcnow()
                )
                db.session.add(restored)
                db.session.delete(archived)
                restored_count += 1
    
    db.session.commit()
    return jsonify({'success': True, 'restored': restored_count})

@app.route('/ahrefs/delete-archived', methods=['POST'])
@login_required
def ahrefs_delete_archived():
    data = request.get_json()
    archived_ids = data.get('ids', [])
    
    deleted_count = 0
    for archived_id in archived_ids:
        archived = ArchivedURLData.query.get(archived_id)
        if archived:
            db.session.delete(archived)
            deleted_count += 1
    
    db.session.commit()
    return jsonify({'success': True, 'deleted': deleted_count})

@app.route('/export/archived_ahrefs_data')
@login_required
def export_archived_ahrefs_data():
    data_records = ArchivedURLData.query.all()
    
    output = StringIO()
    writer = csv.writer(output)
    
    header = [
        'URL', 'Original Fetched At', 'Archived At',
        'Org Keywords', 'Org Keywords 1-3', 'Org Traffic', 'Org Cost',
        'Domain Rating', 'Ahrefs Rank',
        'Live Backlinks', 'All Time Backlinks', 'Live Ref Domains', 'All Time Ref Domains'
    ]
    writer.writerow(header)
    
    for record in data_records:
        row = [
            record.url,
            record.original_fetched_at.strftime('%Y-%m-%d %H:%M:%S') if record.original_fetched_at else '',
            record.archived_at.strftime('%Y-%m-%d %H:%M:%S')
        ]
        
        current_metrics = record.get_current_metrics()
        if current_metrics and 'metrics' in current_metrics:
            metrics = current_metrics['metrics']
            row.extend([
                metrics.get('org_keywords', ''),
                metrics.get('org_keywords_1_3', ''),
                metrics.get('org_traffic', ''),
                metrics.get('org_cost', '')
            ])
        else:
            row.extend(['', '', '', ''])
        
        domain_rating = record.get_domain_rating()
        if domain_rating and 'domain_rating' in domain_rating:
            dr_data = domain_rating['domain_rating']
            row.extend([
                dr_data.get('domain_rating', ''),
                dr_data.get('ahrefs_rank', '')
            ])
        else:
            row.extend(['', ''])
        
        backlinks_stats = record.get_backlinks_stats()
        if backlinks_stats and 'metrics' in backlinks_stats:
            bl_data = backlinks_stats['metrics']
            row.extend([
                bl_data.get('live', ''),
                bl_data.get('all_time', ''),
                bl_data.get('live_refdomains', ''),
                bl_data.get('all_time_refdomains', '')
            ])
        else:
            row.extend(['', '', '', ''])
        
        writer.writerow(row)
    
    output.seek(0)
    return send_file(
        BytesIO(output.getvalue().encode()),
        mimetype='text/csv',
        as_attachment=True,
        download_name=f'archived_ahrefs_data_{datetime.now().strftime("%Y%m%d_%H%M%S")}.csv'
    )

@app.route('/ahrefs/delete-data', methods=['POST'])
@login_required
def ahrefs_delete_data_bulk():
    data = request.get_json()
    data_ids = data.get('ids', [])
    
    deleted_count = 0
    for data_id in data_ids:
        url_data = URLData.query.get(data_id)
        if url_data:
            db.session.delete(url_data)
            deleted_count += 1
    
    db.session.commit()
    return jsonify({'success': True, 'deleted': deleted_count})

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5005)