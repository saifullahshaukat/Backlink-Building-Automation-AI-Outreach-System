import smtplib
import threading
import time
import logging
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime
from database import db, EmailOutreach, EmailCredentials

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

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
            smtp_server = None
            emails_sent_count = 0
            max_emails_per_connection = 50  # Reconnect after every 50 emails
            
            try:
                credentials = EmailCredentials.query.get(credentials_id)
                if not credentials:
                    logger.error("Email credentials not found")
                    return
                
                emails = EmailOutreach.query.filter(
                    EmailOutreach.id.in_(email_ids),
                    EmailOutreach.status == 'pending'
                ).all()
                
                self.stats['total_emails'] = len(emails)
                logger.info(f"Starting to send {len(emails)} emails")
                
                # Create initial SMTP connection
                smtp_server = self._create_smtp_connection(credentials)
                if not smtp_server:
                    logger.error("Failed to establish initial SMTP connection")
                    return
                
                for idx, email_record in enumerate(emails):
                    if not self.is_running:
                        logger.info("Email sending stopped by user")
                        break
                    
                    self.stats['current_email'] = email_record.email
                    
                    # Reconnect after max_emails_per_connection or if connection is dead
                    if emails_sent_count >= max_emails_per_connection or not self._is_smtp_alive(smtp_server):
                        logger.info(f"Reconnecting to SMTP server (sent {emails_sent_count} emails so far)")
                        try:
                            smtp_server.quit()
                        except:
                            pass
                        
                        smtp_server = self._create_smtp_connection(credentials)
                        if not smtp_server:
                            logger.error("Failed to reconnect to SMTP server, aborting")
                            break
                        
                        emails_sent_count = 0
                    
                    # Try to send email with retry logic
                    max_retries = 3
                    retry_count = 0
                    email_sent = False
                    
                    while retry_count < max_retries and not email_sent:
                        try:
                            self._send_single_email_with_server(email_record, credentials, smtp_server)
                            email_record.status = 'sent'
                            email_record.sent_at = datetime.utcnow()
                            email_record.error_message = None
                            self.stats['sent'] += 1
                            emails_sent_count += 1
                            email_sent = True
                            logger.info(f"Email sent successfully to {email_record.email} ({self.stats['sent']}/{len(emails)})")
                        except Exception as e:
                            retry_count += 1
                            logger.warning(f"Failed to send email to {email_record.email} (attempt {retry_count}/{max_retries}): {e}")
                            
                            # If connection error, try to reconnect
                            if retry_count < max_retries and ("connection" in str(e).lower() or "timeout" in str(e).lower()):
                                logger.info("Connection issue detected, attempting to reconnect...")
                                try:
                                    smtp_server.quit()
                                except:
                                    pass
                                
                                smtp_server = self._create_smtp_connection(credentials)
                                if not smtp_server:
                                    logger.error("Failed to reconnect, marking email as failed")
                                    break
                                
                                time.sleep(2)  # Brief pause before retry
                            elif retry_count >= max_retries:
                                # Max retries reached, mark as failed
                                email_record.status = 'failed'
                                email_record.error_message = str(e)[:500]
                                self.stats['failed'] += 1
                                logger.error(f"Failed to send email to {email_record.email} after {max_retries} attempts")
                    
                    # Commit to database
                    try:
                        db.session.commit()
                    except Exception as db_error:
                        logger.error(f"Database commit error: {db_error}")
                        try:
                            db.session.rollback()
                        except:
                            pass
                    
                    # Sleep between emails (but not after the last one)
                    if self.is_running and idx < len(emails) - 1:
                        time.sleep(delay_seconds)
                
                logger.info(f"Email sending completed. Sent: {self.stats['sent']}, Failed: {self.stats['failed']}")
                
            except Exception as e:
                logger.error(f"Critical email sending error: {e}", exc_info=True)
                try:
                    db.session.rollback()
                except:
                    pass
            finally:
                # Close SMTP connection
                if smtp_server:
                    try:
                        smtp_server.quit()
                        logger.info("SMTP connection closed")
                    except:
                        pass
                
                self.is_running = False
                self.stats['is_running'] = False
                self.stats['current_email'] = None
    
    def _send_single_email(self, email_record, credentials):
        """Legacy method - creates new connection for each email (not recommended)"""
        msg = MIMEMultipart()
        msg['From'] = credentials.email
        msg['To'] = email_record.email
        msg['Subject'] = email_record.subject
        
        msg.attach(MIMEText(email_record.message, 'plain'))
        
        server = smtplib.SMTP(credentials.smtp_server, credentials.smtp_port, timeout=30)
        server.starttls()
        server.login(credentials.email, credentials.password)
        server.send_message(msg)
        server.quit()
    
    def _create_smtp_connection(self, credentials):
        """Create and return a new SMTP connection"""
        try:
            smtp_server = smtplib.SMTP(credentials.smtp_server, credentials.smtp_port, timeout=30)
            smtp_server.starttls()
            smtp_server.login(credentials.email, credentials.password)
            logger.info("SMTP connection established successfully")
            return smtp_server
        except Exception as e:
            logger.error(f"Failed to connect to SMTP server: {e}")
            return None
    
    def _is_smtp_alive(self, smtp_server):
        """Check if SMTP connection is still alive"""
        try:
            status = smtp_server.noop()[0]
            return status == 250
        except:
            return False
    
    def _send_single_email_with_server(self, email_record, credentials, smtp_server):
        """Efficient method - reuses existing SMTP connection"""
        # Import here to avoid circular dependency
        from app import process_message_template
        
        # Get custom fields if available
        custom_fields = email_record.get_custom_fields() if hasattr(email_record, 'get_custom_fields') else {}
        
        # Process templates with custom fields
        processed_subject = process_message_template(email_record.subject, email_record.url, custom_fields)
        processed_message = process_message_template(email_record.message, email_record.url, custom_fields)
        
        msg = MIMEMultipart()
        msg['From'] = credentials.email
        msg['To'] = email_record.email
        msg['Subject'] = processed_subject
        
        msg.attach(MIMEText(processed_message, 'plain'))
        
        # Send using existing connection
        smtp_server.send_message(msg)