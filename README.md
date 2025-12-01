# Backlink Building Automation & AI Outreach System

A comprehensive Flask-based web application for automating backlink building, email outreach campaigns, and SEO data management. This system integrates with multiple APIs and provides tools for web scraping, email extraction, and automated outreach.

## Features

### 1. **Ahrefs API Integration**
- Fetch domain metrics, backlinks stats, and historical data
- Track domain rating and SEO performance over time
- Export data to Google Sheets
- Archive and manage URL data

### 2. **Email Outreach System**
- Import emails from CSV/Excel files or extracted sources
- Create and save email templates with variable substitution
- Automated email sending with configurable delays
- Track email status (pending, sent, failed)
- SMTP integration with multiple credential support

### 3. **Email Extraction**
- Selenium-based web scraping for email discovery
- Extract emails from contact pages and website content
- Hunter.io API integration for domain-based email search
- Bulk URL processing with progress tracking

### 4. **Web Scrapers**
- **Adsy Scraper**: Automated login and data extraction
- **Icopify Scraper**: Publisher data collection with retry logic
- Session management and rate limiting

### 5. **Outreach Bot**
- Automated contact form submissions
- Email extraction during outreach
- Configurable form field mapping
- URL suppression list support

### 6. **Data Management**
- URL deduplication and normalization
- Suppression list management
- Bulk import/export functionality
- Advanced filtering and search

### 7. **System Monitoring**
- Real-time CPU, memory, and disk usage statistics
- Network I/O monitoring
- Process management dashboard

## Prerequisites

- **Python 3.8+**
- **Chrome/Chromium Browser** (for Selenium)
- **Git**

## Installation

### 1. Clone the Repository

```bash
git clone https://github.com/saifullahshaukat/Backlink-Building-Automation-AI-Outreach-System.git
cd Backlink-Building-Automation-AI-Outreach-System
```

### 2. Install Dependencies

```bash
pip install -r requirements.txt
```

Required packages:
- Flask
- flask-sqlalchemy
- Werkzeug
- pandas
- requests
- beautifulsoup4
- selenium
- webdriver-manager
- psutil
- openpyxl

### 3. Configure Environment Variables

Create a `config.py` file or set environment variables:

```python
SECRET_KEY = 'your-secret-key-here'
AHREFS_TOKEN = 'your-ahrefs-api-token'
HUNTER_API_KEY = 'your-hunter-io-api-key'
```

**IMPORTANT**: Never commit API keys or credentials to the repository!

### 4. Initialize Database

The application will automatically create the SQLite database on first run.

### 5. Run the Application

```bash
python app.py
```

The application will be available at:
- Local: `http://127.0.0.1:5005`
- Network: `http://YOUR_IP:5005`

## 🔐 Default Login Credentials

- **Username**: `admin`
- **Password**: `admin123`

**⚠️ IMPORTANT: Change these credentials immediately after first login!**

## Project Structure

```
merged_app/
├── app.py                      # Main Flask application
├── config.py                   # Configuration settings
├── database.py                 # Database models and schema
├── ahrefs_api.py              # Ahrefs API integration
├── email_sender.py            # Email sending functionality
├── email_extractor.py         # Email extraction logic
├── hunter_extractor.py        # Hunter.io API wrapper
├── outreach_bot.py            # Automated outreach bot
├── sheets_api.py              # Google Sheets integration
├── system_stats.py            # System monitoring
├── dupe_utils.py              # URL deduplication utilities
├── suppression_utils.py       # Suppression list management
├── scrapers/
│   ├── adsy_scraper.py        # Adsy platform scraper
│   └── icopify_scraper.py     # Icopify platform scraper
├── templates/                  # HTML templates
│   ├── base.html
│   ├── dashboard.html
│   ├── login.html
│   ├── ahrefs/                # Ahrefs-related pages
│   ├── email_extraction/      # Email extraction pages
│   ├── email_outreach/        # Email outreach pages
│   ├── outreach/              # Outreach bot pages
│   └── scraper/               # Scraper pages
├── static/
│   └── css/
│       └── styles.css         # Custom styles
└── instance/                   # Instance-specific files (gitignored)
```

## Usage

### Email Outreach Workflow

1. **Import Emails**
   - Upload CSV/Excel file with "Email" and "URL" columns
   - Or import from extracted emails database

2. **Create Template**
   - Design email subject and body
   - Use variables: `(company)`, `(domain)`
   - Save templates for reuse

3. **Configure SMTP**
   - Add email credentials (Gmail, Outlook, etc.)
   - For Gmail: Use App Passwords (not regular password)
   - Set as default for automatic selection

4. **Send Emails**
   - Set delay between emails (recommended: 5-10 seconds)
   - Click "Start Sending" to begin campaign
   - Monitor progress in real-time

### Email Extraction

1. Upload CSV with URLs
2. Select extraction method (Selenium or Hunter.io)
3. Start extraction process
4. Review and export results

### Ahrefs Data Collection

1. Add target URLs
2. Fetch metrics (domain rating, backlinks, traffic)
3. View historical data and trends
4. Export to Google Sheets or CSV

## Configuration

### SMTP Settings (Gmail Example)

1. Enable 2-Step Verification: https://myaccount.google.com/security
2. Generate App Password: https://myaccount.google.com/apppasswords
3. Use these settings:
   - SMTP Server: `smtp.gmail.com`
   - Port: `587`
   - Password: Your 16-character app password

### API Keys

- **Ahrefs**: https://ahrefs.com/api
- **Hunter.io**: https://hunter.io/api

## Database

The application uses SQLite by default. Database models include:

- **URL**: Target URLs for processing
- **URLData**: Ahrefs metrics and data
- **ExtractedEmail**: Discovered email addresses
- **EmailOutreach**: Outreach campaign emails
- **EmailCredentials**: SMTP credentials
- **EmailTemplate**: Saved email templates
- **SuppressionList**: URLs to exclude
- **OutreachData**: Outreach campaign results
- **ScrapedData**: Web scraping results

## Important Security Notes

1. **Never commit**:
   - API keys or tokens
   - Email credentials
   - Database files with real data
   - Configuration files with secrets

2. **Use environment variables** for sensitive data
3. **Change default passwords** before deployment
4. **Enable HTTPS** in production
5. **Regular backups** of your database

## Troubleshooting

### Chrome Driver Issues
- The app uses `webdriver-manager` to auto-install ChromeDriver
- Ensure Chrome/Chromium browser is installed

### Gmail Authentication Errors
- Verify 2-Step Verification is enabled
- Use App Password, not regular password
- Check SMTP settings (server: smtp.gmail.com, port: 587)

### Import Errors
- Ensure CSV/Excel files have proper column headers
- Check file encoding (UTF-8 recommended)

## License

This project is provided as-is for educational and business purposes.

## Contributing

Contributions are welcome! Please:
1. Fork the repository
2. Create a feature branch
3. Commit your changes
4. Push to the branch
5. Open a Pull Request

## Disclaimer

This tool is for legitimate business outreach purposes only. Always:
- Comply with CAN-SPAM Act and GDPR
- Obtain proper consent for email communications
- Respect website terms of service when scraping
- Use reasonable rate limits to avoid overwhelming servers

## Support

For issues and questions, please open an issue on GitHub.

---

**Built with ❤️ for SEO professionals and digital marketers**
