import smtplib
import threading
import time
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime
from database import db, EmailOutreach, EmailCredentials

class EmailSender:
    def __init__(self):
        self.is_running = False
        self.stats = {
            'is_running': False,
            'total_emails': 0,
            'sent': 0,
            'failed': 0,
            'current_email': None,
            'started_at': None
        }
        self.thread = None
    
    def start_sending(self, email_ids, credentials_id, delay_seconds, app):
        if self.is_running:
            return False
        
        self.is_running = True
        self.stats['is_running'] = True
        self.stats['started_at'] = datetime.now().isoformat()
        
        self.thread = threading.Thread(
            target=self._send_emails_thread,
            args=(email_ids, credentials_id, delay_seconds, app)
        )
        self.thread.daemon = True
        self.thread.start()
        return True
    
    def stop_sending(self):
        self.is_running = False
        self.stats['is_running'] = False
        return True
    
    def _send_emails_thread(self, email_ids, credentials_id, delay_seconds, app):
        with app.app_context():
            try:
                credentials = EmailCredentials.query.get(credentials_id)
                if not credentials:
                    return
                
                emails = EmailOutreach.query.filter(
                    EmailOutreach.id.in_(email_ids),
                    EmailOutreach.status == 'pending'
                ).all()
                
                self.stats['total_emails'] = len(emails)
                
                for email_record in emails:
                    if not self.is_running:
                        break
                    
                    self.stats['current_email'] = email_record.email
                    
                    try:
                        self._send_single_email(email_record, credentials)
                        email_record.status = 'sent'
                        email_record.sent_at = datetime.utcnow()
                        self.stats['sent'] += 1
                    except Exception as e:
                        email_record.status = 'failed'
                        email_record.error_message = str(e)
                        self.stats['failed'] += 1
                    
                    db.session.commit()
                    
                    if self.is_running and email_record != emails[-1]:
                        time.sleep(delay_seconds)
                
            except Exception as e:
                print(f"Email sending error: {e}")
            finally:
                self.is_running = False
                self.stats['is_running'] = False
                self.stats['current_email'] = None
    
    def _send_single_email(self, email_record, credentials):
        msg = MIMEMultipart()
        msg['From'] = credentials.email
        msg['To'] = email_record.email
        msg['Subject'] = email_record.subject
        
        msg.attach(MIMEText(email_record.message, 'plain'))
        
        server = smtplib.SMTP(credentials.smtp_server, credentials.smtp_port)
        server.starttls()
        server.login(credentials.email, credentials.password)
        server.send_message(msg)
        server.quit()