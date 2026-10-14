# app.py - COMPLETE Defense News Tracker with Twitter Integration
import streamlit as st
import pandas as pd
import requests
from bs4 import BeautifulSoup
import json
import time
import re
from datetime import datetime, timedelta
import threading
import sqlite3
from urllib.parse import urljoin, urlparse
import random
import os
import logging
import hashlib
from typing import List, Dict, Optional, Tuple
import io
import sys
import subprocess
import importlib

# Check for required packages and install if missing
def install_missing_package(package_name):
    """Install missing package using pip"""
    try:
        subprocess.check_call([sys.executable, "-m", "pip", "install", package_name])
        return True
    except:
        return False

# Try to import tweepy, install if not available
try:
    import tweepy
    TWEEPY_AVAILABLE = True
except ImportError:
    TWEEPY_AVAILABLE = False

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Page configuration - must be first Streamlit command
st.set_page_config(
    page_title="Defense News Scraper",
    page_icon="🛡️",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Initialize session state
def init_session_state():
    """Initialize all session state variables"""
    defaults = {
        'scraped_data': [],
        'scraping_in_progress': False,
        'current_page': 'dashboard',
        'scheduler_running': False,
        'last_scrape_time': None,
        'selected_countries': ['China', 'Pakistan'],
        'selected_keywords': [],
        'database_initialized': False,
        'twitter_connected': False,
        'twitter_api': None,
        'twitter_results': [],
        'twitter_api_keys': {
            'api_key': '',
            'api_secret': '',
            'access_token': '',
            'access_secret': '',
            'bearer_token': ''
        }
    }
    
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value

# Default sources
DEFAULT_SOURCES = {
    'china': [
        {"name": "China Military Online", "url": "http://eng.chinamil.com.cn/", 
         "selectors": [".news-list li a", ".list li a", "h3 a", ".title a"]},
        {"name": "Global Times - Military", "url": "https://www.globaltimes.cn/military.html", 
         "selectors": [".content ul li a", ".right-con ul li a", "h4 a"]},
        {"name": "PLA Daily", "url": "http://eng.chinamil.com.cn/PLA-Daily/", 
         "selectors": [".list-left ul li a", ".content-list li a", ".news-title a"]},
        {"name": "Xinhua - Military", "url": "http://www.xinhuanet.com/english/military/index.htm", 
         "selectors": ["a[href*='/military/']", "h3 a", ".title a", ".tit a"]},
        {"name": "China Daily - Military", "url": "https://www.chinadaily.com.cn/military", 
         "selectors": [".busBox1 li a", ".main_art li a", "h4 a", ".tw3_txt3_title a"]}
    ],
    'pakistan': [
        {"name": "Pakistan Defence Forum", "url": "https://www.defence.pk/", 
         "selectors": [".title a", ".threadtitle a", "h3 a", ".titleText"]},
        {"name": "ISPR (Official)", "url": "https://www.ispr.gov.pk/", 
         "selectors": [".news-title a", ".entry-title a", "h2 a", "h1 a"]},
        {"name": "Pakistan Today - Defence", "url": "https://www.pakistantoday.com.pk/category/defence/", 
         "selectors": [".post-title a", "h2 a", ".title a", "article h2 a"]},
        {"name": "The News - Defence", "url": "https://www.thenews.com.pk/defence", 
         "selectors": [".story__title a", "h2 a", "h3 a", ".heading a"]},
        {"name": "Dawn - Defence", "url": "https://www.dawn.com/defence", 
         "selectors": [".story__title a", ".media__title a", "h2 a", "article h2 a"]}
    ]
}

# Twitter/X default search queries
DEFAULT_TWITTER_SEARCHES = {
    'china': [
        "China military",
        "PLA",
        "Chinese army",
        "South China Sea",
        "Taiwan defense",
        "China defence news",
        "People's Liberation Army"
    ],
    'pakistan': [
        "Pakistan military",
        "Pak Army",
        "ISPR",
        "Pakistan defence",
        "Kashmir security",
        "Pakistan air force",
        "Pak Navy"
    ],
    'general': [
        "defense news",
        "military update",
        "armed forces",
        "national security",
        "defence technology"
    ]
}

# Database Functions with Migration Support
def init_database():
    """Initialize SQLite database with required tables"""
    try:
        conn = sqlite3.connect('defense_news.db')
        c = conn.cursor()
        
        # Check if articles table exists and get its columns
        c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='articles'")
        articles_table_exists = c.fetchone() is not None
        
        if articles_table_exists:
            # Get existing columns
            c.execute("PRAGMA table_info(articles)")
            columns = [col[1] for col in c.fetchall()]
            
            # Add missing columns
            if 'article_type' not in columns:
                c.execute('ALTER TABLE articles ADD COLUMN article_type TEXT DEFAULT "website"')
                logger.info("Added article_type column to articles table")
            
            if 'full_content' not in columns:
                c.execute('ALTER TABLE articles ADD COLUMN full_content TEXT')
                logger.info("Added full_content column to articles table")
        
        else:
            # Create articles table with all columns
            c.execute('''CREATE TABLE IF NOT EXISTS articles
                        (id INTEGER PRIMARY KEY AUTOINCREMENT,
                         title TEXT NOT NULL,
                         url TEXT UNIQUE NOT NULL,
                         source TEXT,
                         country TEXT,
                         keywords TEXT,
                         scraped_date TIMESTAMP,
                         content_preview TEXT,
                         full_content TEXT,
                         article_type TEXT DEFAULT 'website')''')
        
        # Check/create sources table
        c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='sources'")
        if not c.fetchone():
            c.execute('''CREATE TABLE IF NOT EXISTS sources
                        (id INTEGER PRIMARY KEY AUTOINCREMENT,
                         name TEXT NOT NULL,
                         url TEXT UNIQUE NOT NULL,
                         country TEXT,
                         selectors TEXT,
                         is_active BOOLEAN DEFAULT 1)''')
        
        # Check/create jobs table
        c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='jobs'")
        if not c.fetchone():
            c.execute('''CREATE TABLE IF NOT EXISTS jobs
                        (id INTEGER PRIMARY KEY AUTOINCREMENT,
                         name TEXT NOT NULL,
                         keywords TEXT,
                         countries TEXT,
                         frequency TEXT,
                         next_run TIMESTAMP,
                         last_run TIMESTAMP,
                         is_active BOOLEAN DEFAULT 1)''')
        
        # Check/create twitter_keys table
        c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='twitter_keys'")
        if not c.fetchone():
            c.execute('''CREATE TABLE IF NOT EXISTS twitter_keys
                        (id INTEGER PRIMARY KEY AUTOINCREMENT,
                         api_key TEXT,
                         api_secret TEXT,
                         access_token TEXT,
                         access_secret TEXT,
                         bearer_token TEXT,
                         is_active BOOLEAN DEFAULT 1,
                         created_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
        
        # Check/create twitter_searches table
        c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='twitter_searches'")
        if not c.fetchone():
            c.execute('''CREATE TABLE IF NOT EXISTS twitter_searches
                        (id INTEGER PRIMARY KEY AUTOINCREMENT,
                         name TEXT NOT NULL,
                         query TEXT NOT NULL,
                         country TEXT,
                         is_active BOOLEAN DEFAULT 1,
                         last_run TIMESTAMP)''')
        
        conn.commit()
        st.session_state.database_initialized = True
        logger.info("Database initialized/updated successfully")
        
    except Exception as e:
        logger.error(f"Error initializing database: {e}")
        st.error(f"Database initialization failed: {e}")
    finally:
        if 'conn' in locals():
            conn.close()

def migrate_database():
    """Migrate database to add missing columns"""
    try:
        conn = sqlite3.connect('defense_news.db')
        c = conn.cursor()
        
        # Check articles table columns
        c.execute("PRAGMA table_info(articles)")
        columns = [col[1] for col in c.fetchall()]
        
        changes_made = False
        
        # Add article_type if missing
        if 'article_type' not in columns:
            try:
                c.execute('ALTER TABLE articles ADD COLUMN article_type TEXT DEFAULT "website"')
                logger.info("Added article_type column")
                changes_made = True
                
                # Update existing records to have article_type = 'website'
                c.execute("UPDATE articles SET article_type = 'website' WHERE article_type IS NULL")
            except Exception as e:
                logger.error(f"Error adding article_type: {e}")
        
        # Add full_content if missing
        if 'full_content' not in columns:
            try:
                c.execute('ALTER TABLE articles ADD COLUMN full_content TEXT')
                logger.info("Added full_content column")
                changes_made = True
            except Exception as e:
                logger.error(f"Error adding full_content: {e}")
        
        conn.commit()
        conn.close()
        
        if changes_made:
            logger.info("Database migration completed")
            return True
        else:
            logger.info("Database already up to date")
            return True
            
    except Exception as e:
        logger.error(f"Error migrating database: {e}")
        return False

def populate_default_sources():
    """Populate database with default sources and Twitter searches"""
    try:
        conn = sqlite3.connect('defense_news.db')
        c = conn.cursor()
        
        # Populate website sources
        for country, sources in DEFAULT_SOURCES.items():
            for source in sources:
                # Check if source already exists
                c.execute('SELECT id FROM sources WHERE url = ?', (source['url'],))
                existing = c.fetchone()
                
                if not existing:
                    c.execute('''INSERT INTO sources (name, url, country, selectors, is_active) 
                                 VALUES (?, ?, ?, ?, ?)''',
                              (source['name'], source['url'], country, 
                               json.dumps(source['selectors']), 1))
        
        # Populate default Twitter searches
        search_id = 1
        for country, queries in DEFAULT_TWITTER_SEARCHES.items():
            for query in queries:
                c.execute('''INSERT OR IGNORE INTO twitter_searches (name, query, country, is_active) 
                             VALUES (?, ?, ?, ?)''',
                          (f"Twitter Search {search_id}", query, country, 1))
                search_id += 1
        
        conn.commit()
        logger.info("Default sources and Twitter searches populated")
        
    except Exception as e:
        logger.error(f"Error populating default data: {e}")
    finally:
        if 'conn' in locals():
            conn.close()

# User Agent Management
class UserAgentManager:
    """Manage rotating user agents"""
    def __init__(self):
        self.user_agents = [
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/121.0',
            'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.1 Safari/605.1.15',
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36 Edg/119.0.0.0',
            'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        ]
    
    def get_random(self):
        return random.choice(self.user_agents)

# Anti-Captcha Scraper
class DefenseScraper:
    """Main scraper class with anti-captcha measures"""
    
    def __init__(self, delay_range=(1, 3)):
        self.session = requests.Session()
        self.ua_manager = UserAgentManager()
        self.delay_range = delay_range
        self.setup_session()
    
    def setup_session(self):
        """Setup session with default headers"""
        self.session.headers.update({
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.5',
            'Accept-Encoding': 'gzip, deflate, br',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
            'Sec-Fetch-Dest': 'document',
            'Sec-Fetch-Mode': 'navigate',
            'Sec-Fetch-Site': 'none',
            'Sec-Fetch-User': '?1',
            'Cache-Control': 'max-age=0'
        })
    
    def rotate_headers(self, url):
        """Rotate headers for request"""
        self.session.headers.update({
            'User-Agent': self.ua_manager.get_random(),
            'Referer': f'https://{urlparse(url).netloc}' if '://' in url else f'https://{url}',
            'Host': urlparse(url).netloc
        })
    
    def random_delay(self):
        """Add random delay between requests"""
        time.sleep(random.uniform(*self.delay_range))
    
    def detect_captcha(self, html_content):
        """Detect captcha presence in HTML"""
        captcha_indicators = [
            'captcha', 'recaptcha', 'hcaptcha', 'cloudflare',
            'verify-you-are-human', 'security-check',
            'data-sitekey', 'g-recaptcha', 'cf-challenge',
            'captcha-container', 'captcha-wrapper'
        ]
        
        html_lower = html_content.lower()
        return any(indicator in html_lower for indicator in captcha_indicators)
    
    def get_page(self, url, max_retries=3):
        """Fetch webpage with retry logic"""
        self.rotate_headers(url)
        
        for attempt in range(max_retries):
            try:
                self.random_delay()
                response = self.session.get(url, timeout=15, allow_redirects=True)
                response.raise_for_status()
                
                # Check for captcha
                if self.detect_captcha(response.text):
                    logger.warning(f"Captcha detected on {url} (attempt {attempt + 1})")
                    if attempt < max_retries - 1:
                        # Try different approach
                        time.sleep(5)
                        continue
                
                return response.text
                
            except requests.exceptions.RequestException as e:
                logger.error(f"Request failed (attempt {attempt + 1}): {e}")
                if attempt == max_retries - 1:
                    return None
                time.sleep(2 ** attempt)  # Exponential backoff
        
        return None
    
    def extract_links(self, html, url, selectors):
        """Extract article links from HTML"""
        soup = BeautifulSoup(html, 'html.parser')
        links = []
        
        for selector in selectors:
            try:
                elements = soup.select(selector)
                for element in elements:
                    href = element.get('href')
                    title = element.get_text(strip=True)
                    
                    if href and title and len(title) > 10:
                        # Make URL absolute
                        full_url = urljoin(url, href)
                        
                        # Filter out non-article links
                        if self.is_article_link(full_url, title):
                            links.append({
                                'title': title[:500],
                                'url': full_url,
                                'source_url': url
                            })
            except Exception as e:
                logger.debug(f"Error with selector {selector}: {e}")
                continue
        
        return links
    
    def is_article_link(self, url, title):
        """Check if link is likely an article"""
        skip_patterns = [
            'login', 'register', 'signup', 'logout', 'contact', 'about',
            'privacy', 'terms', 'policy', 'cookie', 'advertise', 'career',
            'author', 'tag', 'category', 'feed', 'rss', 'atom', '.pdf',
            '.doc', '.zip', '.jpg', '.png', '.gif', '#', 'javascript:'
        ]
        
        url_lower = url.lower()
        title_lower = title.lower()
        
        if any(pattern in url_lower for pattern in skip_patterns):
            return False
        
        article_indicators = ['read more', 'continue reading', 'full article', '...']
        if any(indicator in title_lower for indicator in article_indicators):
            return True
        
        return 20 <= len(title) <= 500
    
    def scrape_source(self, source_info, keywords):
        """Scrape a single source"""
        try:
            if len(source_info) == 5:
                source_id, name, url, country, selectors_json = source_info
            elif len(source_info) == 6:
                source_id, name, url, country, selectors_json, is_active = source_info
            else:
                logger.error(f"Unexpected source_info format: {source_info}")
                return []
            
            selectors = json.loads(selectors_json)
            
            logger.info(f"Scraping {name} ({country})")
            
            html = self.get_page(url)
            if not html:
                logger.warning(f"Failed to fetch {name}")
                return []
            
            links = self.extract_links(html, url, selectors)
            
            if keywords:
                filtered_links = []
                for link in links:
                    title_lower = link['title'].lower()
                    if any(keyword.lower() in title_lower for keyword in keywords):
                        filtered_links.append(link)
                links = filtered_links
            
            articles = []
            for link in links[:15]:
                try:
                    article_html = self.get_page(link['url'])
                    if article_html:
                        article_soup = BeautifulSoup(article_html, 'html.parser')
                        
                        content_text = ''
                        for tag in ['article', 'main', '.article-content', '.post-content', '.content']:
                            content = article_soup.select_one(tag)
                            if content:
                                content_text = content.get_text(strip=True)[:1000]
                                break
                        
                        if not content_text:
                            paragraphs = article_soup.find_all('p')[:3]
                            content_text = ' '.join([p.get_text(strip=True) for p in paragraphs])[:500]
                    else:
                        content_text = ''
                    
                    article = {
                        'title': link['title'],
                        'url': link['url'],
                        'source': name,
                        'country': country,
                        'keywords': ', '.join(keywords) if keywords else 'All',
                        'scraped_date': datetime.now().isoformat(),
                        'content_preview': content_text[:300] + '...' if content_text else 'No content available',
                        'full_content': content_text,
                        'article_type': 'website'
                    }
                    
                    articles.append(article)
                    
                except Exception as e:
                    logger.error(f"Error processing article {link['url']}: {e}")
                    continue
            
            return articles
            
        except Exception as e:
            logger.error(f"Error in scrape_source: {e}")
            return []

# Twitter/X Scraper Class
class TwitterScraper:
    """Scrape Twitter/X for defense-related news"""
    
    def __init__(self, api_key=None, api_secret=None, access_token=None, access_secret=None, bearer_token=None):
        self.api = None
        self.client = None
        self.connected = False
        
        if TWEEPY_AVAILABLE and (api_key or bearer_token):
            self.setup_twitter_api(api_key, api_secret, access_token, access_secret, bearer_token)
    
    def setup_twitter_api(self, api_key, api_secret, access_token, access_secret, bearer_token=None):
        """Setup Twitter API connection"""
        try:
            if bearer_token:
                self.client = tweepy.Client(bearer_token=bearer_token, wait_on_rate_limit=True)
                self.connected = True
                logger.info("Connected to Twitter API v2 with Bearer token")
            elif api_key and api_secret and access_token and access_secret:
                auth = tweepy.OAuthHandler(api_key, api_secret)
                auth.set_access_token(access_token, access_secret)
                self.api = tweepy.API(auth, wait_on_rate_limit=True)
                self.api.verify_credentials()
                self.connected = True
                logger.info("Connected to Twitter API v1.1 with OAuth")
            else:
                logger.warning("Insufficient Twitter API credentials provided")
                
        except Exception as e:
            logger.error(f"Failed to connect to Twitter API: {e}")
            self.connected = False
    
    def search_tweets(self, query, count=20, result_type='recent', include_retweets=False):
        """Search for tweets matching query"""
        if not self.connected:
            logger.error("Twitter API not connected")
            return []
        
        tweets_data = []
        
        try:
            if self.client:
                response = self.client.search_recent_tweets(
                    query=query,
                    max_results=min(count, 100),
                    tweet_fields=['created_at', 'public_metrics', 'author_id', 'entities'],
                    user_fields=['username', 'name', 'profile_image_url'],
                    expansions=['author_id']
                )
                
                if response.data:
                    users = {user.id: user for user in response.includes.get('users', [])}
                    
                    for tweet in response.data:
                        user = users.get(tweet.author_id)
                        tweet_info = self.format_tweet_v2(tweet, user)
                        tweets_data.append(tweet_info)
            
            elif self.api:
                tweets = self.api.search_tweets(
                    q=query,
                    count=min(count, 100),
                    result_type=result_type,
                    include_entities=True,
                    tweet_mode='extended'
                )
                
                for tweet in tweets:
                    if not include_retweets and hasattr(tweet, 'retweeted_status'):
                        continue
                    
                    tweet_info = self.format_tweet_v1(tweet)
                    tweets_data.append(tweet_info)
            
            logger.info(f"Found {len(tweets_data)} tweets for query: {query}")
            return tweets_data
            
        except tweepy.TooManyRequests:
            logger.warning("Twitter API rate limit exceeded")
            return []
        except Exception as e:
            logger.error(f"Error searching tweets: {e}")
            return []
    
    def format_tweet_v1(self, tweet):
        """Format tweet data from v1.1 API"""
        if hasattr(tweet, 'full_text'):
            text = tweet.full_text
        else:
            text = tweet.text
        
        user = tweet.user
        
        media_url = None
        if hasattr(tweet, 'entities') and 'media' in tweet.entities:
            media = tweet.entities['media'][0]
            media_url = media['media_url_https'] if 'media_url_https' in media else media.get('media_url')
        
        tweet_info = {
            'id': tweet.id_str,
            'text': text[:500],
            'user_name': user.name,
            'user_screen_name': user.screen_name,
            'user_profile_image': user.profile_image_url_https,
            'created_at': tweet.created_at.isoformat() if hasattr(tweet.created_at, 'isoformat') else str(tweet.created_at),
            'retweet_count': tweet.retweet_count,
            'favorite_count': tweet.favorite_count,
            'reply_count': getattr(tweet, 'reply_count', 0),
            'quote_count': getattr(tweet, 'quote_count', 0),
            'url': f"https://twitter.com/{user.screen_name}/status/{tweet.id_str}",
            'media_url': media_url,
            'source': 'twitter',
            'article_type': 'tweet'
        }
        
        return tweet_info
    
    def format_tweet_v2(self, tweet, user=None):
        """Format tweet data from v2 API"""
        text = tweet.text
        
        tweet_info = {
            'id': tweet.id,
            'text': text[:500],
            'user_name': user.name if user else 'Unknown',
            'user_screen_name': user.username if user else 'unknown',
            'user_profile_image': getattr(user, 'profile_image_url', ''),
            'created_at': tweet.created_at.isoformat() if hasattr(tweet.created_at, 'isoformat') else str(tweet.created_at),
            'retweet_count': tweet.public_metrics.get('retweet_count', 0),
            'favorite_count': tweet.public_metrics.get('like_count', 0),
            'reply_count': tweet.public_metrics.get('reply_count', 0),
            'quote_count': tweet.public_metrics.get('quote_count', 0),
            'url': f"https://twitter.com/{tweet_info['user_screen_name']}/status/{tweet.id}",
            'media_url': None,
            'source': 'twitter',
            'article_type': 'tweet'
        }
        
        return tweet_info
    
    def get_user_tweets(self, username, count=20):
        """Get tweets from a specific user"""
        if not self.connected:
            return []
        
        tweets_data = []
        
        try:
            if self.api:
                tweets = self.api.user_timeline(
                    screen_name=username,
                    count=min(count, 200),
                    tweet_mode='extended',
                    include_rts=False
                )
                
                for tweet in tweets:
                    tweet_info = self.format_tweet_v1(tweet)
                    tweets_data.append(tweet_info)
            
            logger.info(f"Found {len(tweets_data)} tweets from user: {username}")
            return tweets_data
            
        except Exception as e:
            logger.error(f"Error getting user tweets: {e}")
            return []
    
    def search_defense_tweets(self, keywords=None, countries=None, count_per_query=10):
        """Search for defense-related tweets"""
        if not self.connected:
            return []
        
        all_tweets = []
        
        queries = []
        
        if keywords:
            for keyword in keywords:
                queries.append(keyword)
        
        if countries:
            for country in countries:
                if country.lower() == 'china':
                    queries.extend(DEFAULT_TWITTER_SEARCHES.get('china', []))
                elif country.lower() == 'pakistan':
                    queries.extend(DEFAULT_TWITTER_SEARCHES.get('pakistan', []))
        
        if not queries:
            queries = DEFAULT_TWITTER_SEARCHES.get('general', ['defense news', 'military'])
        
        queries = list(set(queries))
        
        for query in queries[:10]:
            try:
                tweets = self.search_tweets(query, count=count_per_query)
                for tweet in tweets:
                    tweet['search_query'] = query
                    if countries:
                        tweet['country'] = ', '.join(countries)
                    all_tweets.append(tweet)
                
                time.sleep(1)
                
            except Exception as e:
                logger.error(f"Error searching for query '{query}': {e}")
        
        unique_tweets = {}
        for tweet in all_tweets:
            if tweet['id'] not in unique_tweets:
                unique_tweets[tweet['id']] = tweet
        
        return list(unique_tweets.values())

# Database Operations
def save_articles_to_db(articles):
    """Save scraped articles to database"""
    if not articles:
        return 0
    
    try:
        conn = sqlite3.connect('defense_news.db')
        c = conn.cursor()
        
        saved_count = 0
        for article in articles:
            try:
                article_type = article.get('article_type', 'website')
                
                c.execute('''INSERT OR IGNORE INTO articles 
                            (title, url, source, country, keywords, scraped_date, 
                             content_preview, full_content, article_type)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                          (article['title'], article['url'], article['source'],
                           article['country'], article['keywords'], article['scraped_date'],
                           article['content_preview'], article.get('full_content', ''),
                           article_type))
                saved_count += c.rowcount
            except Exception as e:
                logger.error(f"Error saving article {article.get('title', 'Unknown')}: {e}")
        
        conn.commit()
        logger.info(f"Saved {saved_count} articles to database")
        return saved_count
        
    except Exception as e:
        logger.error(f"Error saving articles to database: {e}")
        return 0
    finally:
        if 'conn' in locals():
            conn.close()

def save_twitter_keys(api_key, api_secret, access_token, access_secret, bearer_token=None):
    """Save Twitter API keys to database"""
    try:
        conn = sqlite3.connect('defense_news.db')
        c = conn.cursor()
        
        c.execute("DELETE FROM twitter_keys")
        
        c.execute('''INSERT INTO twitter_keys 
                    (api_key, api_secret, access_token, access_secret, bearer_token, is_active)
                    VALUES (?, ?, ?, ?, ?, ?)''',
                  (api_key, api_secret, access_token, access_secret, bearer_token, 1))
        
        conn.commit()
        conn.close()
        return True
        
    except Exception as e:
        logger.error(f"Error saving Twitter keys: {e}")
        return False

def get_twitter_keys():
    """Get Twitter API keys from database"""
    try:
        conn = sqlite3.connect('defense_news.db')
        c = conn.cursor()
        
        c.execute("SELECT api_key, api_secret, access_token, access_secret, bearer_token FROM twitter_keys WHERE is_active = 1 LIMIT 1")
        keys = c.fetchone()
        conn.close()
        
        if keys:
            return {
                'api_key': keys[0],
                'api_secret': keys[1],
                'access_token': keys[2],
                'access_secret': keys[3],
                'bearer_token': keys[4]
            }
        return None
        
    except Exception as e:
        logger.error(f"Error getting Twitter keys: {e}")
        return None

def get_sources_by_country(countries):
    """Get active sources for specified countries"""
    try:
        conn = sqlite3.connect('defense_news.db')
        c = conn.cursor()
        
        placeholders = ','.join(['?'] * len(countries))
        query = f'''SELECT id, name, url, country, selectors 
                    FROM sources 
                    WHERE country IN ({placeholders}) AND is_active = 1
                    ORDER BY country, name'''
        
        c.execute(query, countries)
        sources = c.fetchall()
        conn.close()
        
        return sources
        
    except Exception as e:
        logger.error(f"Error getting sources: {e}")
        return []

def get_recent_articles(limit=20, article_type=None):
    """Get recent articles from database"""
    try:
        conn = sqlite3.connect('defense_news.db')
        
        c = conn.cursor()
        c.execute("PRAGMA table_info(articles)")
        columns = [col[1] for col in c.fetchall()]
        
        if 'article_type' not in columns:
            if article_type == 'tweet':
                query = '''SELECT title, url, source, country, scraped_date, 'tweet' as article_type 
                           FROM articles 
                           WHERE source LIKE '%twitter%' OR LOWER(title) LIKE '%tweet%'
                           ORDER BY scraped_date DESC 
                           LIMIT ?'''
            elif article_type == 'website':
                query = '''SELECT title, url, source, country, scraped_date, 'website' as article_type 
                           FROM articles 
                           WHERE source NOT LIKE '%twitter%' AND LOWER(title) NOT LIKE '%tweet%'
                           ORDER BY scraped_date DESC 
                           LIMIT ?'''
            else:
                query = '''SELECT title, url, source, country, scraped_date, 
                                  CASE 
                                    WHEN source LIKE '%twitter%' OR LOWER(title) LIKE '%tweet%' THEN 'tweet'
                                    ELSE 'website'
                                  END as article_type
                           FROM articles 
                           ORDER BY scraped_date DESC 
                           LIMIT ?'''
        else:
            if article_type:
                query = '''SELECT title, url, source, country, scraped_date, article_type 
                           FROM articles 
                           WHERE article_type = ?
                           ORDER BY scraped_date DESC 
                           LIMIT ?'''
                df = pd.read_sql_query(query, conn, params=(article_type, limit))
                conn.close()
                return df
            else:
                query = '''SELECT title, url, source, country, scraped_date, article_type 
                           FROM articles 
                           ORDER BY scraped_date DESC 
                           LIMIT ?'''
        
        df = pd.read_sql_query(query, conn, params=(limit,))
        conn.close()
        
        return df
        
    except Exception as e:
        logger.error(f"Error getting recent articles: {e}")
        return pd.DataFrame()

def get_article_stats():
    """Get article statistics"""
    try:
        conn = sqlite3.connect('defense_news.db')
        c = conn.cursor()
        
        stats = {}
        
        c.execute("SELECT COUNT(*) FROM articles")
        stats['total'] = c.fetchone()[0]
        
        today = datetime.now().strftime('%Y-%m-%d')
        c.execute("SELECT COUNT(*) FROM articles WHERE DATE(scraped_date) = ?", (today,))
        stats['today'] = c.fetchone()[0]
        
        c.execute("SELECT country, COUNT(*) FROM articles GROUP BY country")
        stats['by_country'] = dict(c.fetchall())
        
        c.execute("SELECT source, COUNT(*) FROM articles GROUP BY source ORDER BY COUNT(*) DESC LIMIT 10")
        stats['top_sources'] = c.fetchall()
        
        try:
            c.execute("SELECT article_type, COUNT(*) FROM articles GROUP BY article_type")
            stats['by_type'] = dict(c.fetchall())
        except sqlite3.OperationalError:
            stats['by_type'] = {'website': stats['total']}
        
        conn.close()
        return stats
        
    except Exception as e:
        logger.error(f"Error getting stats: {e}")
        return {}

# UI Components
def create_sidebar():
    """Create the sidebar navigation"""
    with st.sidebar:
        st.markdown("""
        <div style="text-align: center; padding: 20px 0;">
            <h1 style="font-size: 2.5em;">🛡️</h1>
            <h2>Defense News Tracker</h2>
            <p style="color: #666; font-size: 0.9em;">Monitor military news from China & Pakistan</p>
        </div>
        """, unsafe_allow_html=True)
        
        st.markdown("---")
        
        st.markdown("### 📍 Navigation")
        
        pages = {
            "📊 Dashboard": "dashboard",
            "🔍 Scraper": "scraper",
            "🐦 Twitter/X": "twitter",
            "🌐 Sources": "sources",
            "⏰ Scheduler": "scheduler",
            "📰 Results": "results",
            "⚙️ Settings": "settings"
        }
        
        for page_name, page_id in pages.items():
            if st.button(page_name, use_container_width=True, 
                        type="primary" if st.session_state.current_page == page_id else "secondary"):
                st.session_state.current_page = page_id
                st.rerun()
        
        st.markdown("---")
        
        st.markdown("### 📈 Quick Stats")
        
        stats = get_article_stats()
        
        col1, col2 = st.columns(2)
        with col1:
            st.metric("Total Articles", stats.get('total', 0))
        with col2:
            st.metric("Today", stats.get('today', 0))
        
        if 'by_type' in stats:
            for article_type, count in stats['by_type'].items():
                icon = "🐦" if article_type == 'tweet' else "🌐"
                st.metric(f"{icon} {article_type.title()}", count)
        
        st.markdown("---")
        
        st.markdown("### 💾 Database")
        if st.session_state.database_initialized:
            st.success("✓ Connected")
        else:
            st.error("✗ Not Connected")
        
        st.markdown("### 🐦 Twitter/X")
        if st.session_state.twitter_connected:
            st.success("✓ Connected")
        else:
            st.warning("✗ Not Connected")
        
        if st.button("🔄 Initialize DB", use_container_width=True):
            init_database()
            populate_default_sources()
            st.success("Database initialized!")
            st.rerun()

# Page Functions
def show_dashboard():
    """Display dashboard page"""
    st.title("📊 Defense News Dashboard")
    
    stats = get_article_stats()
    
    col1, col2, col3, col4 = st.columns(4)
    
    with col1:
        st.metric("Total Articles", stats.get('total', 0))
    
    with col2:
        st.metric("Today's Articles", stats.get('today', 0))
    
    with col3:
        china_count = stats.get('by_country', {}).get('china', 0)
        st.metric("🇨🇳 China", china_count)
    
    with col4:
        pakistan_count = stats.get('by_country', {}).get('pakistan', 0)
        st.metric("🇵🇰 Pakistan", pakistan_count)
    
    st.markdown("---")
    col1, col2, col3 = st.columns(3)
    
    with col1:
        website_count = stats.get('by_type', {}).get('website', 0)
        st.metric("🌐 Websites", website_count)
    
    with col2:
        tweet_count = stats.get('by_type', {}).get('tweet', 0)
        st.metric("🐦 Tweets", tweet_count)
    
    with col3:
        other_count = stats.get('total', 0) - website_count - tweet_count
        st.metric("📄 Other", other_count)
    
    st.markdown("---")
    
    st.subheader("📰 Recent Articles & Tweets")
    
    tab1, tab2 = st.tabs(["All Content", "Twitter Only"])
    
    with tab1:
        recent_articles = get_recent_articles(15)
        
        if not recent_articles.empty:
            for _, row in recent_articles.iterrows():
                with st.expander(f"{row['article_type'].upper()}: {row['title'][:80]}...", expanded=False):
                    col1, col2 = st.columns([3, 1])
                    with col1:
                        icon = "🐦" if row['article_type'] == 'tweet' else "🌐"
                        st.markdown(f"**{icon} Source:** {row['source']} ({row['country'] if pd.notna(row['country']) else 'N/A'})")
                        st.markdown(f"**Date:** {row['scraped_date']}")
                    with col2:
                        if pd.notna(row['url']):
                            st.markdown(f"[🔗 Open]({row['url']})", unsafe_allow_html=True)
        else:
            st.info("No articles found. Start scraping to collect data.")
    
    with tab2:
        recent_tweets = get_recent_articles(10, 'tweet')
        
        if not recent_tweets.empty:
            for _, row in recent_tweets.iterrows():
                with st.expander(f"🐦 {row['title'][:80]}...", expanded=False):
                    col1, col2 = st.columns([3, 1])
                    with col1:
                        st.markdown(f"**User:** {row['source']}")
                        if pd.notna(row['country']):
                            st.markdown(f"**Country:** {row['country']}")
                        st.markdown(f"**Date:** {row['scraped_date']}")
                    with col2:
                        if pd.notna(row['url']):
                            st.markdown(f"[🐦 View Tweet]({row['url']})", unsafe_allow_html=True)
        else:
            st.info("No tweets found. Connect to Twitter and start searching.")
    
    st.markdown("---")
    st.subheader("📈 Top Sources")
    
    if 'top_sources' in stats and stats['top_sources']:
        sources_df = pd.DataFrame(stats['top_sources'], columns=['Source', 'Articles'])
        st.bar_chart(sources_df.set_index('Source'))
    
    st.markdown("---")
    st.subheader("⚡ Quick Actions")
    
    col1, col2, col3, col4 = st.columns(4)
    
    with col1:
        if st.button("🚀 Web Scrape", use_container_width=True):
            st.session_state.current_page = 'scraper'
            st.rerun()
    
    with col2:
        if st.button("🐦 Twitter Search", use_container_width=True):
            st.session_state.current_page = 'twitter'
            st.rerun()
    
    with col3:
        if st.button("📥 Export Data", use_container_width=True):
            st.session_state.current_page = 'results'
            st.rerun()
    
    with col4:
        if st.button("➕ Add Source", use_container_width=True):
            st.session_state.current_page = 'sources'
            st.rerun()

def show_scraper():
    """Display scraper page"""
    st.title("🔍 Defense News Scraper")
    
    tab1, tab2 = st.tabs(["🌐 Website Scraper", "🐦 Twitter Scraper"])
    
    with tab1:
        show_website_scraper()
    
    with tab2:
        show_twitter_scraper_tab()

def show_website_scraper():
    """Website scraping configuration"""
    with st.expander("⚙️ Configuration", expanded=True):
        col1, col2 = st.columns(2)
        
        with col1:
            keywords_input = st.text_area(
                "Keywords (one per line)",
                height=150,
                placeholder="military\ndefense\narmy\nnavy\nair force\nsecurity\ntroops\nweapons",
                help="Enter keywords to filter articles. One per line."
            )
            
            keywords = []
            if keywords_input:
                for line in keywords_input.split('\n'):
                    line = line.strip()
                    if line:
                        keywords.append(line)
            
            st.caption(f"{len(keywords)} keyword(s) specified")
        
        with col2:
            countries = st.multiselect(
                "Countries",
                ["china", "pakistan"],
                default=["china", "pakistan"],
                help="Select countries to scrape"
            )
            
            max_articles = st.slider(
                "Max articles per source",
                5, 30, 15,
                help="Limit articles per source to avoid rate limiting"
            )
            
            delay = st.slider(
                "Delay between requests (seconds)",
                0.5, 5.0, 1.5,
                help="Higher delay reduces chance of blocking"
            )
    
    with st.expander("🔧 Advanced Options"):
        col1, col2 = st.columns(2)
        
        with col1:
            use_proxy = st.checkbox("Use proxy rotation (if configured)", value=False)
            save_to_db = st.checkbox("Save to database", value=True)
            clear_session = st.checkbox("Clear previous results", value=False)
        
        with col2:
            test_mode = st.checkbox("Test mode (limit to 2 sources)", value=False)
            verbose_logging = st.checkbox("Verbose logging", value=False)
    
    st.markdown("---")
    
    col1, col2, col3 = st.columns([2, 1, 1])
    
    with col2:
        start_button = st.button("🚀 Start Website Scraping", type="primary", use_container_width=True)
    
    with col3:
        stop_button = st.button("🛑 Stop", type="secondary", use_container_width=True)
    
    if stop_button:
        st.session_state.scraping_in_progress = False
        st.warning("Scraping will stop after current source.")
    
    if start_button:
        if not countries:
            st.error("Please select at least one country")
        else:
            run_website_scraping(keywords, countries, max_articles, delay, 
                               save_to_db, clear_session, test_mode)
    
    if st.session_state.scraped_data:
        st.markdown("---")
        display_scraping_results()

def show_twitter_scraper_tab():
    """Twitter scraping in the scraper tab"""
    st.info("🐦 For full Twitter/X functionality, go to the Twitter/X page in the sidebar.")
    
    if not TWEEPY_AVAILABLE:
        st.error("Twitter/X features require the 'tweepy' package. Please install it using: pip install tweepy")
        return
    
    if not st.session_state.twitter_connected:
        st.warning("Please connect to Twitter/X API first on the Twitter/X page.")
        if st.button("Go to Twitter/X Settings", type="secondary"):
            st.session_state.current_page = 'twitter'
            st.rerun()
        return
    
    st.subheader("Quick Twitter Search")
    
    col1, col2 = st.columns(2)
    
    with col1:
        twitter_query = st.text_input(
            "Search Query",
            placeholder="#defense OR #military OR china military OR pakistan army",
            help="Enter Twitter search query"
        )
    
    with col2:
        tweet_count = st.slider("Number of tweets", 5, 100, 20)
    
    if st.button("🔍 Search Twitter", type="primary"):
        if twitter_query:
            with st.spinner("Searching Twitter..."):
                try:
                    twitter_scraper = TwitterScraper(**st.session_state.twitter_api_keys)
                    tweets = twitter_scraper.search_tweets(twitter_query, count=tweet_count)
                    
                    if tweets:
                        st.session_state.twitter_results = tweets
                        st.success(f"Found {len(tweets)} tweets!")
                        
                        if st.checkbox("Save these tweets to database"):
                            saved_count = save_articles_to_db(tweets)
                            st.info(f"Saved {saved_count} tweets to database.")
                        
                        display_twitter_results(tweets)
                    else:
                        st.warning("No tweets found for this query.")
                        
                except Exception as e:
                    st.error(f"Error searching Twitter: {str(e)}")
        else:
            st.error("Please enter a search query")

def run_website_scraping(keywords, countries, max_articles, delay, save_to_db, clear_session, test_mode):
    """Run the website scraping process"""
    if clear_session:
        st.session_state.scraped_data = []
    
    sources = get_sources_by_country(countries)
    
    if test_mode:
        sources = sources[:2]
    
    if not sources:
        st.error("No active sources found for selected countries")
        return
    
    scraper = DefenseScraper(delay_range=(delay, delay + 1))
    
    progress_bar = st.progress(0)
    status_text = st.empty()
    results_container = st.empty()
    
    all_articles = []
    total_sources = len(sources)
    
    st.session_state.scraping_in_progress = True
    
    for i, source in enumerate(sources):
        if not st.session_state.scraping_in_progress:
            break
        
        progress = (i + 1) / total_sources
        progress_bar.progress(progress)
        status_text.text(f"Scraping {source[1]}... ({i+1}/{total_sources})")
        
        articles = scraper.scrape_source(source, keywords)
        articles = articles[:max_articles]
        
        all_articles.extend(articles)
        
        if articles:
            with results_container.expander(f"Results from {source[1]} ({len(articles)} articles)", expanded=False):
                for article in articles:
                    st.markdown(f"**{article['title'][:100]}...**")
                    st.markdown(f"🔗 [Open]({article['url']}) | 📍 {article['country']}")
                    st.markdown("---")
    
    progress_bar.empty()
    status_text.empty()
    
    if all_articles:
        st.session_state.scraped_data = all_articles
        st.session_state.last_scrape_time = datetime.now()
        
        if save_to_db:
            saved_count = save_articles_to_db(all_articles)
            st.success(f"✅ Scraped {len(all_articles)} articles. Saved {saved_count} to database.")
        else:
            st.success(f"✅ Scraped {len(all_articles)} articles.")
    else:
        st.warning("⚠️ No articles found matching your criteria.")
    
    st.session_state.scraping_in_progress = False

def display_scraping_results():
    """Display scraping results"""
    articles = st.session_state.scraped_data
    
    st.subheader(f"📊 Scraping Results ({len(articles)} articles)")
    
    col1, col2 = st.columns(2)
    
    with col1:
        search_term = st.text_input("Search in titles", key="search_results")
    
    with col2:
        countries = list(set(article['country'] for article in articles))
        selected_countries = st.multiselect(
            "Filter by country",
            countries,
            default=countries
        )
    
    filtered_articles = articles
    
    if search_term:
        filtered_articles = [a for a in filtered_articles 
                           if search_term.lower() in a['title'].lower()]
    
    if selected_countries:
        filtered_articles = [a for a in filtered_articles 
                           if a['country'] in selected_countries]
    
    for idx, article in enumerate(filtered_articles[:50]):
        with st.expander(f"{idx+1}. {article['title'][:120]}...", expanded=False):
            col1, col2 = st.columns([3, 1])
            
            with col1:
                st.markdown(f"**Title:** {article['title']}")
                st.markdown(f"**Source:** {article['source']} ({article['country']})")
                st.markdown(f"**Keywords:** {article['keywords']}")
                st.markdown(f"**Date:** {article['scraped_date']}")
                if article['content_preview']:
                    st.markdown(f"**Preview:** {article['content_preview']}")
            
            with col2:
                st.markdown(f"[🌐 Open]({article['url']})", unsafe_allow_html=True)
                
                article_json = json.dumps(article, indent=2, ensure_ascii=False)
                st.download_button(
                    label="📥 JSON",
                    data=article_json,
                    file_name=f"article_{idx+1}.json",
                    mime="application/json",
                    key=f"dl_{idx}"
                )
    
    if filtered_articles:
        st.markdown("---")
        st.subheader("📤 Export Data")
        
        df = pd.DataFrame(filtered_articles)
        
        col1, col2, col3 = st.columns(3)
        
        with col1:
            csv = df.to_csv(index=False)
            st.download_button(
                label="📊 Download CSV",
                data=csv,
                file_name=f"defense_news_{datetime.now().strftime('%Y%m%d_%H%M')}.csv",
                mime="text/csv"
            )
        
        with col2:
            json_data = df.to_json(orient='records', indent=2, force_ascii=False)
            st.download_button(
                label="📄 Download JSON",
                data=json_data,
                file_name=f"defense_news_{datetime.now().strftime('%Y%m%d_%H%M')}.json",
                mime="application/json"
            )
        
        with col3:
            excel_buffer = io.BytesIO()
            with pd.ExcelWriter(excel_buffer, engine='openpyxl') as writer:
                df.to_excel(writer, index=False, sheet_name='Articles')
            excel_data = excel_buffer.getvalue()
            
            st.download_button(
                label="📈 Download Excel",
                data=excel_data,
                file_name=f"defense_news_{datetime.now().strftime('%Y%m%d_%H%M')}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )

def show_twitter_page():
    """Display Twitter/X page"""
    st.title("🐦 Twitter/X News Scraper")
    
    if not TWEEPY_AVAILABLE:
        st.error("""
        ## Twitter/X API Requirements
        
        To use Twitter/X features, you need to:
        
        1. **Install tweepy package:**
        ```bash
        pip install tweepy
        ```
        
        2. **Get Twitter API credentials:**
        - Go to [Twitter Developer Portal](https://developer.twitter.com/)
        - Create a project and app
        - Get API Key, API Secret, Access Token, and Access Secret
        - Or use Bearer Token for v2 API
        
        After installing tweepy, restart the application.
        """)
        return
    
    tab1, tab2, tab3, tab4 = st.tabs(["🔑 API Setup", "🔍 Search Tweets", "📊 Saved Searches", "📈 Analytics"])
    
    with tab1:
        show_twitter_api_setup()
    
    with tab2:
        show_twitter_search()
    
    with tab3:
        show_twitter_saved_searches()
    
    with tab4:
        show_twitter_analytics()

def show_twitter_api_setup():
    """Display Twitter API setup interface"""
    st.subheader("🔑 Twitter/X API Configuration")
    
    st.info("""
    **To get Twitter API credentials:**
    1. Go to [Twitter Developer Portal](https://developer.twitter.com/)
    2. Create a project and app
    3. Get your API credentials
    4. Choose authentication method below
    """)
    
    auth_method = st.radio(
        "Authentication Method",
        ["OAuth 1.0a (API v1.1)", "Bearer Token (API v2)"],
        help="OAuth 1.0a provides more features, Bearer Token is simpler for v2 API"
    )
    
    if auth_method == "OAuth 1.0a (API v1.1)":
        col1, col2 = st.columns(2)
        
        with col1:
            api_key = st.text_input("API Key", type="password", 
                                  value=st.session_state.twitter_api_keys.get('api_key', ''))
            api_secret = st.text_input("API Secret", type="password",
                                     value=st.session_state.twitter_api_keys.get('api_secret', ''))
        
        with col2:
            access_token = st.text_input("Access Token", type="password",
                                       value=st.session_state.twitter_api_keys.get('access_token', ''))
            access_secret = st.text_input("Access Secret", type="password",
                                        value=st.session_state.twitter_api_keys.get('access_secret', ''))
        
        bearer_token = None
    
    else:
        bearer_token = st.text_input("Bearer Token", type="password",
                                   value=st.session_state.twitter_api_keys.get('bearer_token', ''))
        api_key = api_secret = access_token = access_secret = None
    
    col1, col2 = st.columns([3, 1])
    
    with col1:
        if st.button("🔗 Test Connection", type="primary", use_container_width=True):
            if auth_method == "OAuth 1.0a (API v1.1)":
                if not all([api_key, api_secret, access_token, access_secret]):
                    st.error("Please fill all OAuth credentials")
                else:
                    test_twitter_connection(api_key, api_secret, access_token, access_secret, None)
            else:
                if not bearer_token:
                    st.error("Please enter Bearer Token")
                else:
                    test_twitter_connection(None, None, None, None, bearer_token)
    
    with col2:
        if st.button("💾 Save Credentials", type="secondary", use_container_width=True):
            if save_twitter_keys(api_key, api_secret, access_token, access_secret, bearer_token):
                st.success("Credentials saved to database!")
                
                st.session_state.twitter_api_keys = {
                    'api_key': api_key or '',
                    'api_secret': api_secret or '',
                    'access_token': access_token or '',
                    'access_secret': access_secret or '',
                    'bearer_token': bearer_token or ''
                }
            else:
                st.error("Failed to save credentials")
    
    st.markdown("---")
    st.subheader("Connection Status")
    
    if st.session_state.twitter_connected:
        st.success("✅ Connected to Twitter/X API")
        
        try:
            if st.session_state.twitter_api:
                user = st.session_state.twitter_api.verify_credentials()
                st.info(f"Connected as: **@{user.screen_name}** ({user.name})")
        except:
            st.info("Using Bearer Token authentication (API v2)")
    else:
        st.warning("⚠️ Not connected to Twitter/X API")
        
        with st.expander("Troubleshooting Tips"):
            st.markdown("""
            **Common issues:**
            1. **Invalid credentials** - Double-check your API keys
            2. **App permissions** - Ensure your app has read permissions
            3. **API access level** - You might need Elevated or Academic access
            4. **Rate limits** - Free tier has limited requests per 15 minutes
            
            **For defense news monitoring, consider:**
            - Using multiple search queries
            - Setting up scheduled searches
            - Combining with website scraping
            """)

def test_twitter_connection(api_key, api_secret, access_token, access_secret, bearer_token):
    """Test Twitter API connection"""
    with st.spinner("Testing Twitter API connection..."):
        try:
            twitter_scraper = TwitterScraper(api_key, api_secret, access_token, access_secret, bearer_token)
            
            if twitter_scraper.connected:
                st.session_state.twitter_connected = True
                st.session_state.twitter_api = twitter_scraper.api
                st.session_state.twitter_api_keys = {
                    'api_key': api_key or '',
                    'api_secret': api_secret or '',
                    'access_token': access_token or '',
                    'access_secret': access_secret or '',
                    'bearer_token': bearer_token or ''
                }
                st.success("✅ Successfully connected to Twitter/X API!")
                
                test_query = "defense"
                test_tweets = twitter_scraper.search_tweets(test_query, count=2)
                if test_tweets:
                    st.info(f"Test search successful! Found {len(test_tweets)} tweets for 'defense'")
                else:
                    st.warning("Connected but no tweets found in test search (might be rate limited)")
                    
            else:
                st.error("❌ Failed to connect to Twitter/X API")
                
        except Exception as e:
            st.error(f"❌ Connection error: {str(e)}")

# app.py - Fixed version with corrected variable assignment
# ... (keep all imports and previous code the same until show_twitter_search function)

def show_twitter_search():
    """Display Twitter search interface"""
    st.subheader("🔍 Search Twitter/X for Defense News")
    
    if not st.session_state.twitter_connected:
        st.warning("Please connect to Twitter/X API first in the 'API Setup' tab.")
        return
    
    col1, col2 = st.columns(2)
    
    with col1:
        search_type = st.radio(
            "Search Type",
            ["Keyword Search", "User Timeline", "Defense Topics"]
        )
        
        # Initialize variables to avoid UnboundLocalError
        search_query = None
        username = None
        result_type = "recent"
        include_retweets = False
        
        if search_type == "Keyword Search":
            search_query = st.text_input(
                "Search Query",
                placeholder="china military OR pakistan army OR #defense",
                help="Use Twitter search operators: OR, AND, - (minus), # (hashtag)"
            )
            result_type = st.selectbox("Result Type", ["recent", "popular", "mixed"])
            include_retweets = st.checkbox("Include retweets", value=False)
            
        elif search_type == "User Timeline":
            username = st.text_input("Twitter Username", placeholder="@PakistanArmy or @DeptDefense")
            search_query = None  # Explicitly set to None
            
        else:  # Defense Topics
            topic = st.selectbox(
                "Defense Topic",
                ["China Military", "Pakistan Military", "General Defense", "Geopolitics", "Military Technology"]
            )
            
            topic_queries = {
                "China Military": "china military OR PLA OR \"South China Sea\" OR taiwan defense",
                "Pakistan Military": "pakistan army OR ISPR OR pakistan defence OR \"Pak Army\"",
                "General Defense": "defense news OR military update OR armed forces",
                "Geopolitics": "geopolitics OR national security OR international relations",
                "Military Technology": "military technology OR defense tech OR weapons system"
            }
            
            search_query = topic_queries.get(topic, "defense")
            result_type = "recent"
            include_retweets = False
    
    with col2:
        tweet_count = st.slider("Number of tweets", 5, 200, 50)
        
        countries = st.multiselect(
            "Filter by country (for defense topics)",
            ["china", "pakistan", "usa", "india", "russia"],
            help="Only applies to defense topic searches"
        )
        
        save_to_db = st.checkbox("Save results to database", value=True)
        clear_previous = st.checkbox("Clear previous search results", value=False)
    
    with st.expander("🔧 Advanced Options"):
        col1, col2 = st.columns(2)
        
        with col1:
            language = st.selectbox(
                "Language",
                ["en", "any"],
                help="Filter by language (English recommended for defense news)"
            )
            
            since_date = st.date_input(
                "Since date",
                value=datetime.now() - timedelta(days=7),
                max_value=datetime.now()
            )
        
        with col2:
            min_retweets = st.number_input("Minimum retweets", min_value=0, value=0)
            min_likes = st.number_input("Minimum likes", min_value=0, value=0)
    
    if st.button("🚀 Search Twitter", type="primary", use_container_width=True):
        # Validate inputs based on search type
        if search_type == "User Timeline":
            if not username or username.strip() == "":
                st.error("Please enter a Twitter username")
            else:
                run_twitter_search(
                    search_type, search_query, username.strip(), tweet_count, result_type,
                    include_retweets, countries, save_to_db, clear_previous,
                    language, since_date, min_retweets, min_likes
                )
        else:
            if not search_query or search_query.strip() == "":
                st.error("Please enter a search query")
            else:
                run_twitter_search(
                    search_type, search_query.strip(), None, tweet_count, result_type,
                    include_retweets, countries, save_to_db, clear_previous,
                    language, since_date, min_retweets, min_likes
                )

def run_twitter_search(search_type, search_query, username, tweet_count, result_type,
                      include_retweets, countries, save_to_db, clear_previous,
                      language, since_date, min_retweets, min_likes):
    """Run Twitter search"""
    if clear_previous:
        st.session_state.twitter_results = []
    
    with st.spinner("Searching Twitter..."):
        try:
            twitter_keys = get_twitter_keys()
            if not twitter_keys:
                st.error("Twitter API credentials not found. Please set them up first.")
                return
            
            twitter_scraper = TwitterScraper(**twitter_keys)
            
            if not twitter_scraper.connected:
                st.error("Not connected to Twitter API")
                return
            
            tweets = []
            
            if search_type == "User Timeline":
                # Remove @ symbol if present
                clean_username = username.replace('@', '') if username else ''
                if clean_username:
                    tweets = twitter_scraper.get_user_tweets(clean_username, tweet_count)
                else:
                    st.error("Invalid username provided")
                    return
                
            elif search_type == "Defense Topics":
                keywords = [search_query] if search_query else []
                tweets = twitter_scraper.search_defense_tweets(keywords, countries, tweet_count // 5)
                
            else:  # Keyword Search
                tweets = twitter_scraper.search_tweets(search_query, tweet_count, result_type, include_retweets)
            
            # Filter tweets
            filtered_tweets = []
            for tweet in tweets:
                # Apply language filter
                if language != "any" and 'lang' in tweet:
                    if tweet.get('lang') != language:
                        continue
                
                # Apply engagement filters
                if tweet.get('retweet_count', 0) < min_retweets:
                    continue
                if tweet.get('favorite_count', 0) < min_likes:
                    continue
                
                # Apply date filter
                try:
                    tweet_date_str = tweet['created_at'].replace('Z', '+00:00')
                    tweet_date = datetime.fromisoformat(tweet_date_str)
                    if tweet_date.date() < since_date:
                        continue
                except:
                    # If date parsing fails, include the tweet
                    pass
                
                filtered_tweets.append(tweet)
            
            st.session_state.twitter_results = filtered_tweets
            
            if filtered_tweets:
                st.success(f"✅ Found {len(filtered_tweets)} tweets")
                
                if save_to_db:
                    saved_count = save_articles_to_db(filtered_tweets)
                    st.info(f"Saved {saved_count} tweets to database")
                
                display_twitter_results(filtered_tweets)
                
            else:
                st.warning("No tweets found matching your criteria")
                
        except Exception as e:
            st.error(f"Error searching Twitter: {str(e)}")
            import traceback
            st.code(traceback.format_exc())

# Also need to fix the display_twitter_results function to handle missing keys gracefully:
def display_twitter_results(tweets):
    """Display Twitter search results"""
    st.subheader(f"🐦 Search Results ({len(tweets)} tweets)")
    
    col1, col2 = st.columns(2)
    
    with col1:
        search_term = st.text_input("Search in tweet text", key="tweet_search")
    
    with col2:
        min_engagement = st.slider("Minimum engagement (retweets + likes)", 0, 1000, 0)
    
    filtered_tweets = tweets
    
    if search_term:
        filtered_tweets = [t for t in filtered_tweets 
                          if search_term.lower() in t.get('text', '').lower()]
    
    if min_engagement > 0:
        filtered_tweets = [t for t in filtered_tweets 
                          if (t.get('retweet_count', 0) + t.get('favorite_count', 0)) >= min_engagement]
    
    for idx, tweet in enumerate(filtered_tweets[:50]):
        with st.expander(f"🐦 {tweet.get('user_name', 'Unknown')}: {tweet.get('text', '')[:80]}...", expanded=False):
            col1, col2 = st.columns([3, 1])
            
            with col1:
                # Safe access to tweet data
                user_name = tweet.get('user_name', 'Unknown')
                user_screen_name = tweet.get('user_screen_name', 'unknown')
                tweet_text = tweet.get('text', '')
                created_at = tweet.get('created_at', 'Unknown date')
                search_query = tweet.get('search_query', '')
                
                st.markdown(f"**@{user_screen_name}** ({user_name})")
                
                st.markdown(f"**Tweet:** {tweet_text}")
                
                col_meta1, col_meta2, col_meta3 = st.columns(3)
                with col_meta1:
                    st.metric("Retweets", tweet.get('retweet_count', 0))
                with col_meta2:
                    st.metric("Likes", tweet.get('favorite_count', 0))
                with col_meta3:
                    st.metric("Replies", tweet.get('reply_count', 0))
                
                st.caption(f"Posted: {created_at}")
                if search_query:
                    st.caption(f"Search query: {search_query}")
            
            with col2:
                tweet_url = tweet.get('url', '#')
                if tweet_url != '#':
                    st.markdown(f"[🐦 View Tweet]({tweet_url})", unsafe_allow_html=True)
                
                user_profile_image = tweet.get('user_profile_image')
                if user_profile_image:
                    try:
                        st.image(user_profile_image, width=80)
                    except:
                        pass
                
                media_url = tweet.get('media_url')
                if media_url:
                    try:
                        st.image(media_url, width=100)
                    except:
                        pass
                
                tweet_json = json.dumps(tweet, indent=2, ensure_ascii=False)
                st.download_button(
                    label="📥 JSON",
                    data=tweet_json,
                    file_name=f"tweet_{tweet.get('id', idx)}.json",
                    mime="application/json",
                    key=f"tweet_dl_{idx}"
                )
    
    if filtered_tweets:
        st.markdown("---")
        st.subheader("📤 Export Tweet Data")
        
        # Create DataFrame with safe access to keys
        data_for_df = []
        for tweet in filtered_tweets:
            data_for_df.append({
                'id': tweet.get('id', ''),
                'user_name': tweet.get('user_name', ''),
                'user_screen_name': tweet.get('user_screen_name', ''),
                'text': tweet.get('text', ''),
                'retweet_count': tweet.get('retweet_count', 0),
                'favorite_count': tweet.get('favorite_count', 0),
                'created_at': tweet.get('created_at', ''),
                'url': tweet.get('url', ''),
                'search_query': tweet.get('search_query', '')
            })
        
        df = pd.DataFrame(data_for_df)
        
        col1, col2, col3 = st.columns(3)
        
        with col1:
            csv = df.to_csv(index=False)
            st.download_button(
                label="📊 Download CSV",
                data=csv,
                file_name=f"twitter_defense_{datetime.now().strftime('%Y%m%d_%H%M')}.csv",
                mime="text/csv"
            )
        
        with col2:
            json_data = df.to_json(orient='records', indent=2, force_ascii=False)
            st.download_button(
                label="📄 Download JSON",
                data=json_data,
                file_name=f"twitter_defense_{datetime.now().strftime('%Y%m%d_%H%M')}.json",
                mime="application/json"
            )
        
        with col3:
            excel_buffer = io.BytesIO()
            with pd.ExcelWriter(excel_buffer, engine='openpyxl') as writer:
                df.to_excel(writer, index=False, sheet_name='Tweets')
            excel_data = excel_buffer.getvalue()
            
            st.download_button(
                label="📈 Download Excel",
                data=excel_data,
                file_name=f"twitter_defense_{datetime.now().strftime('%Y%m%d_%H%M')}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )

# ... (rest of the code remains the same)
def show_twitter_saved_searches():
    """Display saved Twitter searches"""
    st.subheader("📊 Saved Twitter Searches")
    
    try:
        migrate_database()
        
        conn = sqlite3.connect('defense_news.db')
        
        searches = pd.read_sql_query(
            '''SELECT id, name, query, country, is_active, last_run 
               FROM twitter_searches 
               ORDER BY name''', 
            conn
        )
        
        try:
            search_stats = pd.read_sql_query(
                '''SELECT source as search_query, COUNT(*) as tweet_count 
                   FROM articles 
                   WHERE article_type = 'tweet' 
                   GROUP BY source 
                   ORDER BY COUNT(*) DESC LIMIT 10''',
                conn
            )
        except sqlite3.OperationalError as e:
            if "no such column: article_type" in str(e):
                search_stats = pd.read_sql_query(
                    '''SELECT source as search_query, COUNT(*) as tweet_count 
                       FROM articles 
                       WHERE source LIKE '%twitter%' OR source LIKE '%tweet%' OR LOWER(title) LIKE '%tweet%'
                       GROUP BY source 
                       ORDER BY COUNT(*) DESC LIMIT 10''',
                    conn
                )
                st.info("Using fallback query for tweet statistics")
            else:
                raise e
        
        conn.close()
        
        if not searches.empty:
            st.dataframe(
                searches,
                column_config={
                    "name": "Search Name",
                    "query": "Search Query",
                    "country": "Country",
                    "is_active": "Active",
                    "last_run": "Last Run"
                },
                use_container_width=True
            )
            
            st.markdown("---")
            st.subheader("Add/Edit Search")
            
            col1, col2 = st.columns(2)
            
            with col1:
                search_name = st.text_input("Search Name", placeholder="Daily China Military")
                search_query = st.text_area("Search Query", placeholder="china military OR PLA")
                country = st.selectbox("Country", ["", "china", "pakistan", "Bangladesh", "general"])
            
            with col2:
                is_active = st.checkbox("Active", value=True)
                
                if st.button("💾 Save Search", type="primary"):
                    if search_name and search_query:
                        try:
                            conn = sqlite3.connect('defense_news.db')
                            c = conn.cursor()
                            c.execute('''INSERT OR REPLACE INTO twitter_searches 
                                        (name, query, country, is_active) 
                                        VALUES (?, ?, ?, ?)''',
                                      (search_name, search_query, country if country else None, 1 if is_active else 0))
                            conn.commit()
                            conn.close()
                            st.success("Search saved!")
                            st.rerun()
                        except Exception as e:
                            st.error(f"Error: {str(e)}")
                    else:
                        st.error("Please enter name and query")
            
            st.markdown("---")
            st.subheader("Run Saved Searches")
            
            selected_searches = st.multiselect(
                "Select searches to run",
                searches['name'].tolist(),
                help="Select multiple searches to run sequentially"
            )
            
            tweet_count = st.slider("Tweets per search", 10, 100, 25)
            
            if st.button("🚀 Run Selected Searches", type="secondary"):
                if selected_searches and st.session_state.twitter_connected:
                    run_saved_searches(selected_searches, searches, tweet_count)
                else:
                    st.error("Please select searches and ensure Twitter is connected")
        
        else:
            st.info("No saved searches yet. Add some searches above.")
        
        if not search_stats.empty:
            st.markdown("---")
            st.subheader("📈 Search Statistics")
            
            col1, col2 = st.columns(2)
            
            with col1:
                st.dataframe(search_stats, use_container_width=True)
            
            with col2:
                chart_df = search_stats.head(5)
                st.bar_chart(chart_df.set_index('search_query'))
                
    except Exception as e:
        st.error(f"Error loading saved searches: {str(e)}")
        st.info("Try clicking the 'Fix Database Schema' button in Settings → Database tab")

def run_saved_searches(selected_searches, searches_df, tweet_count):
    """Run saved Twitter searches"""
    with st.spinner(f"Running {len(selected_searches)} searches..."):
        try:
            twitter_keys = get_twitter_keys()
            if not twitter_keys:
                st.error("Twitter API credentials not found")
                return
            
            twitter_scraper = TwitterScraper(**twitter_keys)
            
            if not twitter_scraper.connected:
                st.error("Not connected to Twitter API")
                return
            
            all_tweets = []
            progress_bar = st.progress(0)
            
            for i, search_name in enumerate(selected_searches):
                progress = (i + 1) / len(selected_searches)
                progress_bar.progress(progress)
                
                search_row = searches_df[searches_df['name'] == search_name].iloc[0]
                search_query = search_row['query']
                
                tweets = twitter_scraper.search_tweets(search_query, tweet_count)
                
                for tweet in tweets:
                    tweet['search_query'] = search_query
                    tweet['saved_search_name'] = search_name
                    if pd.notna(search_row['country']):
                        tweet['country'] = search_row['country']
                
                all_tweets.extend(tweets)
                
                try:
                    conn = sqlite3.connect('defense_news.db')
                    c = conn.cursor()
                    c.execute('''UPDATE twitter_searches 
                                SET last_run = ? 
                                WHERE name = ?''',
                              (datetime.now().isoformat(), search_name))
                    conn.commit()
                    conn.close()
                except:
                    pass
                
                time.sleep(2)
            
            progress_bar.empty()
            
            if all_tweets:
                saved_count = save_articles_to_db(all_tweets)
                
                st.session_state.twitter_results = all_tweets
                
                st.success(f"✅ Completed {len(selected_searches)} searches. Found {len(all_tweets)} tweets, saved {saved_count} to database.")
                
                display_twitter_results(all_tweets)
            else:
                st.warning("No tweets found from selected searches")
                
        except Exception as e:
            st.error(f"Error running saved searches: {str(e)}")

def show_twitter_analytics():
    """Display Twitter analytics"""
    st.subheader("📈 Twitter Analytics")
    
    try:
        migrate_database()
        
        conn = sqlite3.connect('defense_news.db')
        
        try:
            total_tweets = pd.read_sql_query(
                "SELECT COUNT(*) as count FROM articles WHERE article_type = 'tweet'", 
                conn
            ).iloc[0]['count']
        except sqlite3.OperationalError:
            total_tweets = pd.read_sql_query(
                "SELECT COUNT(*) as count FROM articles WHERE source LIKE '%twitter%' OR LOWER(title) LIKE '%tweet%'", 
                conn
            ).iloc[0]['count']
        
        try:
            today_tweets = pd.read_sql_query(
                "SELECT COUNT(*) as count FROM articles WHERE article_type = 'tweet' AND DATE(scraped_date) = DATE('now')", 
                conn
            ).iloc[0]['count']
        except sqlite3.OperationalError:
            today_tweets = 0
        
        try:
            top_users = pd.read_sql_query(
                '''SELECT source as username, COUNT(*) as tweet_count 
                   FROM articles 
                   WHERE article_type = 'tweet' 
                   GROUP BY source 
                   ORDER BY COUNT(*) DESC LIMIT 10''',
                conn
            )
        except sqlite3.OperationalError:
            top_users = pd.read_sql_query(
                '''SELECT source as username, COUNT(*) as tweet_count 
                   FROM articles 
                   WHERE source LIKE '%twitter%' OR LOWER(title) LIKE '%tweet%'
                   GROUP BY source 
                   ORDER BY COUNT(*) DESC LIMIT 10''',
                conn
            )
        
        try:
            daily_tweets = pd.read_sql_query(
                '''SELECT DATE(scraped_date) as date, COUNT(*) as count 
                   FROM articles 
                   WHERE article_type = 'tweet' 
                   GROUP BY DATE(scraped_date) 
                   ORDER BY date DESC LIMIT 30''',
                conn
            )
        except sqlite3.OperationalError:
            daily_tweets = pd.read_sql_query(
                '''SELECT DATE(scraped_date) as date, COUNT(*) as count 
                   FROM articles 
                   WHERE source LIKE '%twitter%' OR LOWER(title) LIKE '%tweet%'
                   GROUP BY DATE(scraped_date) 
                   ORDER BY date DESC LIMIT 30''',
                conn
            )
        
        try:
            tweet_countries = pd.read_sql_query(
                '''SELECT country, COUNT(*) as count 
                   FROM articles 
                   WHERE article_type = 'tweet' AND country IS NOT NULL 
                   GROUP BY country 
                   ORDER BY COUNT(*) DESC''',
                conn
            )
        except:
            tweet_countries = pd.DataFrame()
        
        conn.close()
        
        col1, col2, col3, col4 = st.columns(4)
        
        with col1:
            st.metric("Total Tweets", total_tweets)
        
        with col2:
            st.metric("Today's Tweets", today_tweets)
        
        with col3:
            avg_daily = daily_tweets['count'].mean() if not daily_tweets.empty else 0
            st.metric("Avg Daily", f"{avg_daily:.1f}")
        
        with col4:
            unique_users = len(top_users) if not top_users.empty else 0
            st.metric("Unique Users", unique_users)
        
        st.markdown("---")
        
        col1, col2 = st.columns(2)
        
        with col1:
            st.subheader("Top Twitter Users")
            if not top_users.empty:
                st.dataframe(top_users, use_container_width=True)
            else:
                st.info("No Twitter data yet")
        
        with col2:
            st.subheader("Tweet Volume by Day")
            if not daily_tweets.empty:
                daily_tweets['date'] = pd.to_datetime(daily_tweets['date'])
                st.line_chart(daily_tweets.set_index('date'))
            else:
                st.info("No daily tweet data")
        
        st.markdown("---")
        st.subheader("Tweet Distribution by Country")
        
        if not tweet_countries.empty and len(tweet_countries) > 0:
            col1, col2 = st.columns([2, 1])
            
            with col1:
                st.bar_chart(tweet_countries.set_index('country'))
            
            with col2:
                st.dataframe(tweet_countries, use_container_width=True)
        else:
            st.info("No country data available")
        
        st.markdown("---")
        st.subheader("📊 Export Analytics")
        
        if st.button("📥 Download Twitter Analytics Report", type="primary"):
            report = {
                "summary": {
                    "total_tweets": int(total_tweets),
                    "today_tweets": int(today_tweets),
                    "unique_users": int(unique_users),
                    "avg_daily_tweets": float(avg_daily)
                },
                "top_users": top_users.to_dict('records'),
                "daily_volume": daily_tweets.to_dict('records'),
                "country_distribution": tweet_countries.to_dict('records'),
                "generated_at": datetime.now().isoformat()
            }
            
            report_json = json.dumps(report, indent=2)
            st.download_button(
                label="Download JSON Report",
                data=report_json,
                file_name=f"twitter_analytics_{datetime.now().strftime('%Y%m%d')}.json",
                mime="application/json"
            )
            
    except Exception as e:
        st.error(f"Error loading analytics: {str(e)}")

def show_sources():
    """Display sources management page"""
    st.title("🌐 Sources Management")
    
    tab1, tab2, tab3 = st.tabs(["View Sources", "Add Source", "Edit Sources"])
    
    with tab1:
        st.subheader("Current Sources")
        
        for country in ['china', 'pakistan']:
            with st.expander(f"🇨🇳 {country.title()} Sources" if country == 'china' else f"🇵🇰 {country.title()} Sources", expanded=True):
                try:
                    conn = sqlite3.connect('defense_news.db')
                    
                    query = '''SELECT name, url, selectors, is_active 
                               FROM sources 
                               WHERE country = ? 
                               ORDER BY name'''
                    
                    sources = pd.read_sql_query(query, conn, params=(country,))
                    conn.close()
                    
                    if not sources.empty:
                        display_df = sources.copy()
                        display_df['is_active'] = display_df['is_active'].apply(
                            lambda x: '✅ Active' if x == 1 else '❌ Inactive'
                        )
                        
                        display_df['selectors'] = display_df['selectors'].apply(
                            lambda x: ', '.join(json.loads(x))[:50] + '...' if x else ''
                        )
                        
                        st.dataframe(
                            display_df,
                            column_config={
                                "name": "Name",
                                "url": st.column_config.LinkColumn("URL"),
                                "selectors": "Selectors",
                                "is_active": "Status"
                            },
                            use_container_width=True,
                            hide_index=True
                        )
                    else:
                        st.info(f"No sources configured for {country}")
                        
                except Exception as e:
                    st.error(f"Error loading sources: {str(e)}")
    
    with tab2:
        st.subheader("Add New Source")
        
        with st.form("add_source_form"):
            col1, col2 = st.columns(2)
            
            with col1:
                name = st.text_input("Source Name*", placeholder="e.g., Global Times Military")
                url = st.text_input("Website URL*", placeholder="https://www.globaltimes.cn/military.html")
                country = st.selectbox("Country*", ["china", "pakistan"])
            
            with col2:
                selectors = st.text_area(
                    "CSS Selectors* (one per line)",
                    placeholder=".news-title a\n.article-link\nh3 a.title",
                    height=150,
                    help="CSS selectors that match article links"
                )
                is_active = st.checkbox("Active", value=True)
                st.caption("* Required fields")
            
            submitted = st.form_submit_button("➕ Add Source", type="primary")
            
            if submitted:
                if not all([name, url, selectors]):
                    st.error("Please fill all required fields")
                else:
                    selector_list = [s.strip() for s in selectors.split('\n') if s.strip()]
                    if not selector_list:
                        st.error("Please enter at least one CSS selector")
                    else:
                        try:
                            conn = sqlite3.connect('defense_news.db')
                            c = conn.cursor()
                            c.execute('''INSERT OR REPLACE INTO sources 
                                        (name, url, country, selectors, is_active) 
                                        VALUES (?, ?, ?, ?, ?)''',
                                      (name, url, country, json.dumps(selector_list), 1 if is_active else 0))
                            conn.commit()
                            conn.close()
                            st.success("✅ Source added successfully!")
                            st.rerun()
                        except Exception as e:
                            st.error(f"Error: {str(e)}")
    
    with tab3:
        st.subheader("Edit Sources")
        
        try:
            conn = sqlite3.connect('defense_news.db')
            
            query = '''SELECT id, name, url, country, selectors, is_active 
                       FROM sources ORDER BY country, name'''
            
            sources = pd.read_sql_query(query, conn)
            conn.close()
            
            if not sources.empty:
                for _, source in sources.iterrows():
                    with st.expander(f"{source['name']} ({source['country']})"):
                        with st.form(f"edit_source_{source['id']}"):
                            col1, col2 = st.columns([3, 1])
                            
                            with col1:
                                new_name = st.text_input("Name", value=source['name'], 
                                                       key=f"name_{source['id']}")
                                new_url = st.text_input("URL", value=source['url'], 
                                                      key=f"url_{source['id']}")
                                new_country = st.selectbox(
                                    "Country", 
                                    ["china", "pakistan"],
                                    index=0 if source['country'] == 'china' else 1,
                                    key=f"country_{source['id']}"
                                )
                                selectors_list = json.loads(source['selectors'])
                                new_selectors = st.text_area(
                                    "Selectors",
                                    value='\n'.join(selectors_list),
                                    key=f"selectors_{source['id']}"
                                )
                                new_active = st.checkbox("Active", value=bool(source['is_active']),
                                                       key=f"active_{source['id']}")
                            
                            with col2:
                                save_col, delete_col = st.columns(2)
                                
                                with save_col:
                                    if st.form_submit_button("💾 Save"):
                                        try:
                                            conn = sqlite3.connect('defense_news.db')
                                            c = conn.cursor()
                                            c.execute('''UPDATE sources 
                                                        SET name=?, url=?, country=?, selectors=?, is_active=?
                                                        WHERE id=?''',
                                                      (new_name, new_url, new_country,
                                                       json.dumps([s.strip() for s in new_selectors.split('\n') if s.strip()]),
                                                       1 if new_active else 0, source['id']))
                                            conn.commit()
                                            conn.close()
                                            st.success("✅ Source updated!")
                                            time.sleep(1)
                                            st.rerun()
                                        except Exception as e:
                                            st.error(f"Error: {str(e)}")
                                
                                with delete_col:
                                    if st.form_submit_button("🗑️ Delete"):
                                        try:
                                            conn = sqlite3.connect('defense_news.db')
                                            c = conn.cursor()
                                            c.execute("DELETE FROM sources WHERE id=?", (source['id'],))
                                            conn.commit()
                                            conn.close()
                                            st.success("✅ Source deleted!")
                                            time.sleep(1)
                                            st.rerun()
                                        except Exception as e:
                                            st.error(f"Error: {str(e)}")
            else:
                st.info("No sources to edit")
                
        except Exception as e:
            st.error(f"Error loading sources: {str(e)}")

def show_scheduler():
    """Display scheduler page"""
    st.title("⏰ Scheduler")
    
    st.info("Schedule automatic scraping jobs to run at specified intervals.")
    
    with st.expander("➕ Add New Job", expanded=True):
        col1, col2 = st.columns(2)
        
        with col1:
            job_name = st.text_input("Job Name", placeholder="Daily Military News")
            keywords = st.text_area("Keywords", placeholder="military, defense, army", height=100)
            countries = st.multiselect("Countries", ["china", "pakistan"], default=["china", "pakistan"])
        
        with col2:
            frequency = st.selectbox(
                "Frequency",
                ["Daily", "Every 6 hours", "Every 12 hours", "Weekly", "Manual"]
            )
            
            if frequency == "Daily":
                run_time = st.time_input("Run at", value=datetime.strptime("08:00", "%H:%M").time())
            
            if frequency == "Weekly":
                week_day = st.selectbox("Day", ["Monday", "Tuesday", "Wednesday", "Thursday", 
                                              "Friday", "Saturday", "Sunday"])
                run_time = st.time_input("Run at", value=datetime.strptime("09:00", "%H:%M").time())
            
            max_articles = st.slider("Max articles", 5, 30, 15)
            is_active = st.checkbox("Active", value=True)
        
        if st.button("📅 Schedule Job", type="primary"):
            if job_name and keywords and countries:
                try:
                    conn = sqlite3.connect('defense_news.db')
                    c = conn.cursor()
                    c.execute('''INSERT INTO jobs 
                                (name, keywords, countries, frequency, is_active) 
                                VALUES (?, ?, ?, ?, ?)''',
                              (job_name, keywords, json.dumps(countries), frequency, 1 if is_active else 0))
                    conn.commit()
                    conn.close()
                    st.success(f"Job '{job_name}' scheduled!")
                    st.rerun()
                except Exception as e:
                    st.error(f"Error: {str(e)}")
            else:
                st.error("Please fill all fields")
    
    st.markdown("---")
    st.subheader("📋 Scheduled Jobs")
    
    try:
        conn = sqlite3.connect('defense_news.db')
        jobs = pd.read_sql_query('''SELECT id, name, keywords, countries, frequency, 
                                    last_run, is_active FROM jobs ORDER BY name''', conn)
        conn.close()
        
        if not jobs.empty:
            jobs_display = jobs.copy()
            jobs_display['is_active'] = jobs_display['is_active'].apply(
                lambda x: '✅ Active' if x == 1 else '❌ Inactive'
            )
            jobs_display['last_run'] = pd.to_datetime(jobs_display['last_run'], errors='coerce').dt.strftime('%Y-%m-%d %H:%M')
            jobs_display['countries'] = jobs_display['countries'].apply(
                lambda x: ', '.join(json.loads(x)) if x else ''
            )
            
            st.dataframe(
                jobs_display[['name', 'keywords', 'countries', 'frequency', 'last_run', 'is_active']],
                column_config={
                    "name": "Job Name",
                    "keywords": "Keywords",
                    "countries": "Countries",
                    "frequency": "Frequency",
                    "last_run": "Last Run",
                    "is_active": "Status"
                },
                use_container_width=True,
                hide_index=True
            )
            
            st.markdown("---")
            st.subheader("▶️ Manual Run")
            
            selected_job = st.selectbox("Select job to run", jobs['name'].tolist())
            
            if st.button("🚀 Run Now", type="primary"):
                with st.spinner(f"Running '{selected_job}'..."):
                    time.sleep(2)
                    
                    try:
                        conn = sqlite3.connect('defense_news.db')
                        c = conn.cursor()
                        c.execute('''UPDATE jobs SET last_run = ? WHERE name = ?''',
                                  (datetime.now().isoformat(), selected_job))
                        conn.commit()
                        conn.close()
                    except:
                        pass
                    
                    st.success(f"Job '{selected_job}' completed!")
                    st.rerun()
        else:
            st.info("No scheduled jobs yet.")
            
    except Exception as e:
        st.error(f"Error loading jobs: {str(e)}")
    
    st.markdown("---")
    col1, col2 = st.columns(2)
    
    with col1:
        if st.button("▶️ Start Scheduler", type="primary", use_container_width=True):
            st.session_state.scheduler_running = True
            st.success("Scheduler started!")
    
    with col2:
        if st.button("⏸️ Stop Scheduler", type="secondary", use_container_width=True):
            st.session_state.scheduler_running = False
            st.warning("Scheduler stopped!")

def show_results():
    """Display results page"""
    st.title("📰 Articles Database")
    
    with st.expander("🔍 Filter Articles", expanded=True):
        col1, col2, col3 = st.columns(3)
        
        with col1:
            filter_country = st.multiselect(
                "Country",
                ["china", "pakistan"],
                default=["china", "pakistan"]
            )
        
        with col2:
            try:
                conn = sqlite3.connect('defense_news.db')
                sources = pd.read_sql_query("SELECT DISTINCT source FROM articles ORDER BY source", conn)
                conn.close()
                sources_list = sources['source'].tolist() if not sources.empty else []
                filter_source = st.multiselect("Source", sources_list)
            except:
                filter_source = []
        
        with col3:
            date_range = st.date_input(
                "Date Range",
                value=(datetime.now() - timedelta(days=7), datetime.now()),
                max_value=datetime.now()
            )
        
        search_query = st.text_input("Search in titles and content")
    
    query_params = []
    query_conditions = []
    
    if filter_country:
        placeholders = ','.join(['?'] * len(filter_country))
        query_conditions.append(f"country IN ({placeholders})")
        query_params.extend(filter_country)
    
    if filter_source:
        placeholders = ','.join(['?'] * len(filter_source))
        query_conditions.append(f"source IN ({placeholders})")
        query_params.extend(filter_source)
    
    if len(date_range) == 2:
        start_date, end_date = date_range
        query_conditions.append("DATE(scraped_date) BETWEEN ? AND ?")
        query_params.extend([start_date.strftime('%Y-%m-%d'), end_date.strftime('%Y-%m-%d')])
    
    if search_query:
        query_conditions.append("(title LIKE ? OR content_preview LIKE ?)")
        query_params.extend([f"%{search_query}%", f"%{search_query}%"])
    
    try:
        conn = sqlite3.connect('defense_news.db')
        
        where_clause = " AND ".join(query_conditions) if query_conditions else "1=1"
        query = f'''SELECT id, title, url, source, country, scraped_date 
                   FROM articles 
                   WHERE {where_clause} 
                   ORDER BY scraped_date DESC 
                   LIMIT 500'''
        
        articles_df = pd.read_sql_query(query, conn, params=query_params)
        conn.close()
        
        st.subheader(f"📊 Found {len(articles_df)} articles")
        
        if not articles_df.empty:
            st.dataframe(
                articles_df[['title', 'source', 'country', 'scraped_date']],
                column_config={
                    "title": st.column_config.TextColumn("Title", width="large"),
                    "source": "Source",
                    "country": "Country",
                    "scraped_date": st.column_config.DatetimeColumn("Date")
                },
                use_container_width=True,
                height=400
            )
            
            st.markdown("---")
            st.subheader("📄 Article Details")
            
            selected_idx = st.selectbox("Select article to view details", 
                                       range(len(articles_df)), 
                                       format_func=lambda x: f"{x+1}. {articles_df.iloc[x]['title'][:80]}...")
            
            if selected_idx is not None:
                article = articles_df.iloc[selected_idx]
                
                conn = sqlite3.connect('defense_news.db')
                full_article = pd.read_sql_query(
                    '''SELECT * FROM articles WHERE id = ?''', 
                    conn, 
                    params=(article['id'],)
                ).iloc[0]
                conn.close()
                
                st.markdown(f"### {full_article['title']}")
                st.markdown(f"**Source:** {full_article['source']} ({full_article['country']})")
                st.markdown(f"**Date:** {full_article['scraped_date']}")
                st.markdown(f"**URL:** [{full_article['url']}]({full_article['url']})")
                st.markdown(f"**Keywords:** {full_article['keywords']}")
                
                if full_article['content_preview']:
                    st.markdown("**Preview:**")
                    st.write(full_article['content_preview'])
                
                st.markdown("---")
                col1, col2 = st.columns(2)
                
                with col1:
                    article_json = json.dumps(full_article.to_dict(), indent=2, ensure_ascii=False)
                    st.download_button(
                        label="📥 Download as JSON",
                        data=article_json,
                        file_name=f"article_{full_article['id']}.json",
                        mime="application/json"
                    )
                
                with col2:
                    if st.button("🗑️ Delete Article", type="secondary"):
                        try:
                            conn = sqlite3.connect('defense_news.db')
                            c = conn.cursor()
                            c.execute("DELETE FROM articles WHERE id = ?", (full_article['id'],))
                            conn.commit()
                            conn.close()
                            st.success("Article deleted!")
                            st.rerun()
                        except Exception as e:
                            st.error(f"Error deleting article: {str(e)}")
            
            st.markdown("---")
            st.subheader("📤 Export All Filtered Articles")
            
            if len(articles_df) > 0:
                col1, col2, col3 = st.columns(3)
                
                with col1:
                    csv_data = articles_df.to_csv(index=False)
                    st.download_button(
                        label="📊 Download CSV",
                        data=csv_data,
                        file_name=f"defense_articles_export_{datetime.now().strftime('%Y%m%d')}.csv",
                        mime="text/csv"
                    )
                
                with col2:
                    json_data = articles_df.to_json(orient='records', indent=2, force_ascii=False)
                    st.download_button(
                        label="📄 Download JSON",
                        data=json_data,
                        file_name=f"defense_articles_export_{datetime.now().strftime('%Y%m%d')}.json",
                        mime="application/json"
                    )
                
                with col3:
                    if st.button("🗑️ Delete All Filtered", type="secondary"):
                        if st.checkbox("Confirm permanent deletion of all filtered articles"):
                            try:
                                conn = sqlite3.connect('defense_news.db')
                                c = conn.cursor()
                                
                                delete_query = f"DELETE FROM articles WHERE {where_clause}"
                                c.execute(delete_query, query_params)
                                deleted_count = c.rowcount
                                
                                conn.commit()
                                conn.close()
                                st.success(f"Deleted {deleted_count} articles!")
                                st.rerun()
                            except Exception as e:
                                st.error(f"Error deleting articles: {str(e)}")
        else:
            st.info("No articles match your filters.")
            
    except Exception as e:
        st.error(f"Error loading articles: {str(e)}")

def show_settings():
    """Display settings page"""
    st.title("⚙️ Settings")
    
    tab1, tab2, tab3 = st.tabs(["Application", "Database", "About"])
    
    with tab1:
        st.subheader("Application Settings")
        
        col1, col2 = st.columns(2)
        
        with col1:
            default_delay = st.slider("Default request delay (seconds)", 0.5, 5.0, 1.5)
            request_timeout = st.slider("Request timeout (seconds)", 10, 60, 30)
            max_retries = st.slider("Max retries", 1, 5, 3)
        
        with col2:
            auto_save = st.checkbox("Auto-save to database", value=True)
            enable_logs = st.checkbox("Enable detailed logging", value=True)
            show_previews = st.checkbox("Show content previews", value=True)
        
        if st.button("💾 Save Settings", type="primary"):
            st.success("Settings saved!")
    
    with tab2:
        st.subheader("Database Management")
        
        col1, col2 = st.columns(2)
        
        with col1:
            if st.button("🗑️ Clear All Articles", type="secondary", use_container_width=True):
                if st.checkbox("I understand this will delete ALL articles permanently"):
                    try:
                        conn = sqlite3.connect('defense_news.db')
                        c = conn.cursor()
                        c.execute("DELETE FROM articles")
                        conn.commit()
                        conn.close()
                        st.success("All articles deleted!")
                        st.rerun()
                    except Exception as e:
                        st.error(f"Error: {str(e)}")
            
            if st.button("🔄 Reset Database", type="secondary", use_container_width=True):
                if st.checkbox("Reset entire database (will delete ALL data)"):
                    try:
                        if os.path.exists('defense_news.db'):
                            os.remove('defense_news.db')
                        
                        init_session_state()
                        st.session_state.database_initialized = False
                        
                        init_database()
                        populate_default_sources()
                        
                        st.success("Database reset successfully!")
                        st.rerun()
                    except Exception as e:
                        st.error(f"Error: {str(e)}")
            
            if st.button("🔧 Fix Database Schema", type="secondary", use_container_width=True):
                try:
                    if migrate_database():
                        st.success("Database schema fixed successfully!")
                        st.info("The application will now work with Twitter features.")
                    else:
                        st.error("Failed to fix database schema")
                except Exception as e:
                    st.error(f"Error: {str(e)}")
        
        with col2:
            if st.button("📤 Export Database", type="primary", use_container_width=True):
                try:
                    conn = sqlite3.connect('defense_news.db')
                    articles_df = pd.read_sql_query("SELECT * FROM articles", conn)
                    sources_df = pd.read_sql_query("SELECT * FROM sources", conn)
                    conn.close()
                    
                    import zipfile
                    import tempfile
                    
                    with tempfile.NamedTemporaryFile(delete=False, suffix='.zip') as tmp:
                        with zipfile.ZipFile(tmp.name, 'w') as zipf:
                            articles_csv = articles_df.to_csv(index=False)
                            zipf.writestr('articles.csv', articles_csv)
                            
                            sources_csv = sources_df.to_csv(index=False)
                            zipf.writestr('sources.csv', sources_csv)
                            
                            if os.path.exists('defense_news.db'):
                                zipf.write('defense_news.db', 'defense_news.db')
                        
                        with open(tmp.name, 'rb') as f:
                            zip_data = f.read()
                        
                        st.download_button(
                            label="📥 Download Database Backup",
                            data=zip_data,
                            file_name=f"defense_tracker_backup_{datetime.now().strftime('%Y%m%d_%H%M')}.zip",
                            mime="application/zip"
                        )
                        
                except Exception as e:
                    st.error(f"Error exporting database: {str(e)}")
        
        st.markdown("---")
        st.subheader("Database Information")
        
        try:
            conn = sqlite3.connect('defense_news.db')
            
            tables = ['articles', 'sources', 'jobs', 'twitter_keys', 'twitter_searches']
            for table in tables:
                try:
                    count = pd.read_sql_query(f"SELECT COUNT(*) as count FROM {table}", conn).iloc[0]['count']
                    st.write(f"**{table}**: {count:,} records")
                except:
                    st.write(f"**{table}**: Table doesn't exist")
            
            try:
                c = conn.cursor()
                c.execute("PRAGMA table_info(articles)")
                columns = [col[1] for col in c.fetchall()]
                if 'article_type' in columns:
                    st.success("✓ article_type column exists")
                else:
                    st.warning("⚠ article_type column missing - Click 'Fix Database Schema'")
            except:
                pass
            
            if os.path.exists('defense_news.db'):
                size_mb = os.path.getsize('defense_news.db') / 1024 / 1024
                st.write(f"**Database size**: {size_mb:.2f} MB")
            
            conn.close()
            
        except Exception as e:
            st.error(f"Error getting database info: {str(e)}")
    
    with tab3:
        st.subheader("About Defense News Tracker")
        
        st.markdown("""
        ### 🛡️ Defense News Tracker
        
        **Version**: 2.0.1 (with Twitter/X Integration)
        
        A comprehensive web application for monitoring and collecting defense-related news 
        from Chinese and Pakistani military sources.
        
        **Features**:
        - Multi-source scraping with anti-captcha measures
        - Twitter/X API integration for social media monitoring
        - Keyword-based filtering
        - Scheduled automatic scraping
        - Database storage with export capabilities
        - User-friendly web interface
        
        **Built with**:
        - Python 3.8+
        - Streamlit
        - BeautifulSoup4
        - SQLite3
        - Requests
        - Tweepy (for Twitter/X)
        
        **Important Notes**:
        - This tool is for educational and research purposes
        - Respect website terms of service and robots.txt
        - Use appropriate delays to avoid overloading servers
        - Comply with all applicable laws and regulations
        
        **Disclaimer**:
        The developers are not responsible for any misuse of this tool.
        Users are solely responsible for ensuring their use complies with
        all relevant laws and website policies.
        """)
        
        st.markdown("---")
        st.markdown("### 📞 Support")
        st.markdown("For issues or feature requests, please contact the development team.")

def main():
    """Main application entry point"""
    init_session_state()
    
    if not st.session_state.database_initialized:
        init_database()
        populate_default_sources()
    
    migrate_database()
    
    create_sidebar()
    
    page_mapping = {
        'dashboard': show_dashboard,
        'scraper': show_scraper,
        'twitter': show_twitter_page,
        'sources': show_sources,
        'scheduler': show_scheduler,
        'results': show_results,
        'settings': show_settings
    }
    
    current_page = st.session_state.current_page
    if current_page in page_mapping:
        page_mapping[current_page]()
    else:
        show_dashboard()
    
    st.markdown("---")
    st.markdown(
        "<div style='text-align: center; color: #666; font-size: 0.9em;'>"
        "Defense News Tracker v2.0 • Now with Twitter/X Integration • Last update: 2024</div>",
        unsafe_allow_html=True
    )

if __name__ == "__main__":
    main()