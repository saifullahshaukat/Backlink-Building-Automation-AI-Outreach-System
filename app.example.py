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

# IMPORTANT: Copy this file to app.py and change these credentials
# Default credentials - Change these in your app.py file
USERS = {
    'admin': generate_password_hash('admin123'),  # Change default password
    'user2': generate_password_hash('changeme')   # Add or remove users as needed
}

app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=30)
app.config['SESSION_PERMANENT'] = False
hunter_extractor = HunterExtractor(app.config['HUNTER_API_KEY'])

# NOTE: This is a template file showing the structure.
# Copy this to app.py and add your actual credentials in the USERS dictionary above.
# The rest of the application code should be copied from the original app.py file.

# For security:
# 1. Copy this file: cp app.example.py app.py
# 2. Edit app.py and update the USERS dictionary with your actual credentials
# 3. Never commit app.py to version control (it's in .gitignore)
