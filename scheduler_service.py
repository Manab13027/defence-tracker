# scheduler_service.py (Background scheduler service)
import schedule
import time
import threading
from datetime import datetime
import sqlite3
import json
from app import scrape_website, AntiCaptchaScraper, save_to_database
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class SchedulerService:
    def __init__(self):
        self.running = False
        self.thread = None
    
    def run_scheduled_job(self, job_config):
        """Run a scheduled scraping job"""
        logger.info(f"Running scheduled job: {job_config['name']}")
        
        # Get sources from database
        conn = sqlite3.connect('defense_news.db')
        sources = []
        
        for country in job_config['countries']:
            country_sources = conn.execute(
                "SELECT name, url, country, selectors FROM sources WHERE country=? AND is_active=1",
                (country.lower(),)
            ).fetchall()
            sources.extend(country_sources)
        
        conn.close()
        
        # Initialize scraper
        scraper = AntiCaptchaScraper()
        
        # Scrape each source
        all_articles = []
        keywords = [k.strip() for k in job_config['keywords'].split(',')]
        
        for source in sources:
            name, url, country, selectors = source
            
            source_dict = {
                'name': name,
                'url': url,
                'country': country,
                'selectors': selectors
            }
            
            articles = scrape_website(source_dict, keywords, scraper)
            all_articles.extend(articles[:job_config.get('max_articles', 10)])
        
        # Save to database
        if all_articles:
            save_to_database(all_articles)
            logger.info(f"Saved {len(all_articles)} articles from job {job_config['name']}")
        
        return len(all_articles)
    
    def start(self):
        """Start the scheduler in a background thread"""
        self.running = True
        
        def run_scheduler():
            while self.running:
                schedule.run_pending()
                time.sleep(60)  # Check every minute
        
        self.thread = threading.Thread(target=run_scheduler)
        self.thread.daemon = True
        self.thread.start()
        logger.info("Scheduler service started")
    
    def stop(self):
        """Stop the scheduler"""
        self.running = False
        if self.thread:
            self.thread.join()
        logger.info("Scheduler service stopped")

# Example of scheduling a job
def add_daily_job():
    """Add a daily scraping job"""
    job_config = {
        'name': 'Daily Defense News',
        'keywords': 'defense, military, army',
        'countries': ['china', 'pakistan'],
        'max_articles': 15
    }
    
    # Schedule to run daily at 8:00 AM
    schedule.every().day.at("08:00").do(
        SchedulerService().run_scheduled_job,
        job_config=job_config
    )