import asyncio
import aiohttp

import os
import json
import time
import random
from datetime import datetime
from urllib.parse import quote_plus, urlparse
import re
from concurrent.futures import ThreadPoolExecutor
from typing import List, Dict, Optional, Tuple
import logging
from dataclasses import dataclass
from abc import ABC, abstractmethod
import aiofiles
import aiofiles.os
from bs4 import BeautifulSoup
import ssl
from fake_useragent import UserAgent

# Telegram imports
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, Document
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, ContextTypes, filters
from telegram.constants import ParseMode

# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Configuration
CONFIG = {
    "telegram_token": os.environ.get("TELEGRAM_TOKEN", "8658937403:AAHVNDzbKXUhjKKDRvdcqAxdWtJo-JRay3A"),
    "max_concurrent_searches": 10,
    "default_results_per_engine": 50,
    "timeout": 30,
    "max_file_size": 5 * 1024 * 1024,  # 5MB
    "proxy_list": [
        # Add your proxies here in format: "http://user:pass@host:port" or "socks5://user:pass@host:port"
    ],
    "request_delay": (1, 3),  # Random delay between requests in seconds
    "max_retries": 3,
    "use_tor": False,  # Set to True if you want to use Tor
    "tor_port": 9050
}

@dataclass
class SearchResult:
    title: str
    url: str
    snippet: str
    engine: str

@dataclass
class SearchProgress:
    total: int
    completed: int
    current_engine: str
    message_id: int

class SearchEngine(ABC):
    """Abstract base class for search engines"""
    
    @abstractmethod
    async def search(self, query: str, num_results: int = 50, proxy: Optional[str] = None) -> List[SearchResult]:
        pass

class GoogleSearchEngine(SearchEngine):
    """Google search implementation using scraping"""
    
    def __init__(self):
        self.base_url = "https://www.google.com/search"
        self.ua = UserAgent()
    
    async def search(self, query: str, num_results: int = 50, proxy: Optional[str] = None) -> List[SearchResult]:
        results = []
        headers = {
            "User-Agent": self.ua.random,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.5",
            "Referer": "https://www.google.com/",
            "DNT": "1",
            "Connection": "keep-alive",
            "Upgrade-Insecure-Requests": "1"
        }
        
        # Configure proxy if provided
        proxy_config = None
        if proxy:
            proxy_config = proxy
        elif CONFIG["use_tor"]:
            proxy_config = f"socks5://127.0.0.1:{CONFIG['tor_port']}"
        
        connector = None
        if proxy_config:
            connector = aiohttp.TCPConnector()
        
        async with aiohttp.ClientSession(connector=connector) as session:
            # Calculate number of pages needed
            results_per_page = 10
            pages_needed = min((num_results + results_per_page - 1) // results_per_page, 5)  # Max 5 pages
            
            for page in range(pages_needed):
                start = page * 10
                params = {
                    "q": query,
                    "start": start,
                    "num": results_per_page,
                    "hl": "en",
                    "gl": "us",
                    "ie": "utf8",
                    "oe": "utf8"
                }
                
                retries = 0
                while retries < CONFIG["max_retries"]:
                    try:
                        # Random delay to avoid detection
                        await asyncio.sleep(random.uniform(*CONFIG["request_delay"]))
                        
                        async with session.get(
                            self.base_url,
                            params=params,
                            headers=headers,
                            proxy=proxy_config,
                            timeout=aiohttp.ClientTimeout(total=CONFIG["timeout"]),
                            ssl=False
                        ) as response:
                            if response.status != 200:
                                logger.warning(f"Google returned status {response.status}")
                                retries += 1
                                continue
                            
                            html = await response.text()
                            soup = BeautifulSoup(html, 'html.parser')
                            
                            # Parse search results
                            search_divs = soup.find_all('div', class_='g')
                            
                            for div in search_divs:
                                # Extract title and URL
                                title_elem = div.find('h3')
                                if not title_elem:
                                    continue
                                
                                title = title_elem.get_text()
                                
                                # Extract URL
                                link_elem = div.find('a')
                                if not link_elem or not link_elem.has_attr('href'):
                                    continue
                                
                                url = link_elem['href']
                                if url.startswith('/url?q='):
                                    url = url.split('/url?q=')[1].split('&sa=')[0]
                                
                                # Extract snippet
                                snippet_elem = div.find('span', {'data-ved': True})
                                if not snippet_elem:
                                    snippet_elem = div.find('div', class_='VwiC3b')
                                
                                snippet = snippet_elem.get_text() if snippet_elem else ""
                                
                                results.append(SearchResult(
                                    title=title,
                                    url=url,
                                    snippet=snippet,
                                    engine="Google"
                                ))
                                
                                if len(results) >= num_results:
                                    return results
                            
                            # If we got results, break the retry loop
                            break
                            
                    except Exception as e:
                        logger.error(f"Error searching Google: {e}")
                        retries += 1
                        await asyncio.sleep(2 ** retries)  # Exponential backoff
        
        return results

class BingSearchEngine(SearchEngine):
    """Bing search implementation using scraping"""
    
    def __init__(self):
        self.base_url = "https://www.bing.com/search"
        self.ua = UserAgent()
    
    async def search(self, query: str, num_results: int = 50, proxy: Optional[str] = None) -> List[SearchResult]:
        results = []
        headers = {
            "User-Agent": self.ua.random,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.5",
            "Referer": "https://www.bing.com/",
            "DNT": "1",
            "Connection": "keep-alive",
            "Upgrade-Insecure-Requests": "1"
        }
        
        # Configure proxy if provided
        proxy_config = None
        if proxy:
            proxy_config = proxy
        elif CONFIG["use_tor"]:
            proxy_config = f"socks5://127.0.0.1:{CONFIG['tor_port']}"
        
        connector = None
        if proxy_config:
            connector = aiohttp.TCPConnector()
        
        async with aiohttp.ClientSession(connector=connector) as session:
            # Calculate number of pages needed
            results_per_page = 10
            pages_needed = min((num_results + results_per_page - 1) // results_per_page, 5)  # Max 5 pages
            
            for page in range(pages_needed):
                offset = page * 10
                params = {
                    "q": query,
                    "first": offset + 1,
                    "count": results_per_page,
                    "FORM": "PERE"
                }
                
                retries = 0
                while retries < CONFIG["max_retries"]:
                    try:
                        # Random delay to avoid detection
                        await asyncio.sleep(random.uniform(*CONFIG["request_delay"]))
                        
                        async with session.get(
                            self.base_url,
                            params=params,
                            headers=headers,
                            proxy=proxy_config,
                            timeout=aiohttp.ClientTimeout(total=CONFIG["timeout"]),
                            ssl=False
                        ) as response:
                            if response.status != 200:
                                logger.warning(f"Bing returned status {response.status}")
                                retries += 1
                                continue
                            
                            html = await response.text()
                            soup = BeautifulSoup(html, 'html.parser')
                            
                            # Parse search results
                            search_divs = soup.find_all('li', class_='b_algo')
                            
                            for div in search_divs:
                                # Extract title and URL
                                title_elem = div.find('h2')
                                if not title_elem:
                                    continue
                                
                                title = title_elem.get_text()
                                
                                # Extract URL
                                link_elem = div.find('a')
                                if not link_elem or not link_elem.has_attr('href'):
                                    continue
                                
                                url = link_elem['href']
                                
                                # Extract snippet
                                snippet_elem = div.find('p') or div.find('div', class_='b_caption')
                                snippet = snippet_elem.get_text() if snippet_elem else ""
                                
                                results.append(SearchResult(
                                    title=title,
                                    url=url,
                                    snippet=snippet,
                                    engine="Bing"
                                ))
                                
                                if len(results) >= num_results:
                                    return results
                            
                            # If we got results, break the retry loop
                            break
                            
                    except Exception as e:
                        logger.error(f"Error searching Bing: {e}")
                        retries += 1
                        await asyncio.sleep(2 ** retries)  # Exponential backoff
        
        return results

class YahooSearchEngine(SearchEngine):
    """Yahoo search implementation using scraping"""
    
    def __init__(self):
        self.base_url = "https://search.yahoo.com/search"
        self.ua = UserAgent()
    
    async def search(self, query: str, num_results: int = 50, proxy: Optional[str] = None) -> List[SearchResult]:
        results = []
        headers = {
            "User-Agent": self.ua.random,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.5",
            "Referer": "https://search.yahoo.com/",
            "DNT": "1",
            "Connection": "keep-alive",
            "Upgrade-Insecure-Requests": "1"
        }
        
        # Configure proxy if provided
        proxy_config = None
        if proxy:
            proxy_config = proxy
        elif CONFIG["use_tor"]:
            proxy_config = f"socks5://127.0.0.1:{CONFIG['tor_port']}"
        
        connector = None
        if proxy_config:
            connector = aiohttp.TCPConnector()
        
        async with aiohttp.ClientSession(connector=connector) as session:
            # Calculate number of pages needed
            results_per_page = 10
            pages_needed = min((num_results + results_per_page - 1) // results_per_page, 5)  # Max 5 pages
            
            for page in range(pages_needed):
                start = page * 10
                params = {
                    "p": query,
                    "b": start + 1,
                    "pz": results_per_page,
                    "ei": "UTF-8"
                }
                
                retries = 0
                while retries < CONFIG["max_retries"]:
                    try:
                        # Random delay to avoid detection
                        await asyncio.sleep(random.uniform(*CONFIG["request_delay"]))
                        
                        async with session.get(
                            self.base_url,
                            params=params,
                            headers=headers,
                            proxy=proxy_config,
                            timeout=aiohttp.ClientTimeout(total=CONFIG["timeout"]),
                            ssl=False
                        ) as response:
                            if response.status != 200:
                                logger.warning(f"Yahoo returned status {response.status}")
                                retries += 1
                                continue
                            
                            html = await response.text()
                            soup = BeautifulSoup(html, 'html.parser')
                            
                            # Parse search results
                            search_divs = soup.find_all('div', class_='algo')
                            
                            for div in search_divs:
                                # Extract title and URL
                                title_elem = div.find('h3')
                                if not title_elem:
                                    continue
                                
                                title = title_elem.get_text()
                                
                                # Extract URL
                                link_elem = div.find('a')
                                if not link_elem or not link_elem.has_attr('href'):
                                    continue
                                
                                url = link_elem['href']
                                
                                # Extract snippet
                                snippet_elem = div.find('p', class_='lh-16')
                                snippet = snippet_elem.get_text() if snippet_elem else ""
                                
                                results.append(SearchResult(
                                    title=title,
                                    url=url,
                                    snippet=snippet,
                                    engine="Yahoo"
                                ))
                                
                                if len(results) >= num_results:
                                    return results
                            
                            # If we got results, break the retry loop
                            break
                            
                    except Exception as e:
                        logger.error(f"Error searching Yahoo: {e}")
                        retries += 1
                        await asyncio.sleep(2 ** retries)  # Exponential backoff
        
        return results

class YandexSearchEngine(SearchEngine):
    """Yandex search implementation using scraping"""
    
    def __init__(self):
        self.base_url = "https://yandex.com/search/touch"
        self.ua = UserAgent()
    
    async def search(self, query: str, num_results: int = 50, proxy: Optional[str] = None) -> List[SearchResult]:
        results = []
        headers = {
            "User-Agent": self.ua.random,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.5",
            "Referer": "https://yandex.com/",
            "DNT": "1",
            "Connection": "keep-alive",
            "Upgrade-Insecure-Requests": "1"
        }
        
        # Configure proxy if provided
        proxy_config = None
        if proxy:
            proxy_config = proxy
        elif CONFIG["use_tor"]:
            proxy_config = f"socks5://127.0.0.1:{CONFIG['tor_port']}"
        
        connector = None
        if proxy_config:
            connector = aiohttp.TCPConnector()
        
        async with aiohttp.ClientSession(connector=connector) as session:
            # Calculate number of pages needed
            results_per_page = 10
            pages_needed = min((num_results + results_per_page - 1) // results_per_page, 5)  # Max 5 pages
            
            for page in range(pages_needed):
                start = page * 10
                params = {
                    "text": query,
                    "p": start,
                    "numdoc": results_per_page
                }
                
                retries = 0
                while retries < CONFIG["max_retries"]:
                    try:
                        # Random delay to avoid detection
                        await asyncio.sleep(random.uniform(*CONFIG["request_delay"]))
                        
                        async with session.get(
                            self.base_url,
                            params=params,
                            headers=headers,
                            proxy=proxy_config,
                            timeout=aiohttp.ClientTimeout(total=CONFIG["timeout"]),
                            ssl=False
                        ) as response:
                            if response.status != 200:
                                logger.warning(f"Yandex returned status {response.status}")
                                retries += 1
                                continue
                            
                            html = await response.text()
                            soup = BeautifulSoup(html, 'html.parser')
                            
                            # Parse search results
                            search_divs = soup.find_all('li', class_='serp-item')
                            
                            for div in search_divs:
                                # Extract title and URL
                                title_elem = div.find('h2')
                                if not title_elem:
                                    continue
                                
                                title = title_elem.get_text()
                                
                                # Extract URL
                                link_elem = div.find('a')
                                if not link_elem or not link_elem.has_attr('href'):
                                    continue
                                
                                url = link_elem['href']
                                
                                # Extract snippet
                                snippet_elem = div.find('div', class_='organic__content-wrapper')
                                snippet = snippet_elem.get_text() if snippet_elem else ""
                                
                                results.append(SearchResult(
                                    title=title,
                                    url=url,
                                    snippet=snippet,
                                    engine="Yandex"
                                ))
                                
                                if len(results) >= num_results:
                                    return results
                            
                            # If we got results, break the retry loop
                            break
                            
                    except Exception as e:
                        logger.error(f"Error searching Yandex: {e}")
                        retries += 1
                        await asyncio.sleep(2 ** retries)  # Exponential backoff
        
        return results

class DuckDuckGoSearchEngine(SearchEngine):
    """DuckDuckGo search implementation using scraping"""
    
    def __init__(self):
        self.base_url = "https://html.duckduckgo.com/html/"
        self.ua = UserAgent()
    
    async def search(self, query: str, num_results: int = 50, proxy: Optional[str] = None) -> List[SearchResult]:
        results = []
        headers = {
            "User-Agent": self.ua.random,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.5",
            "Referer": "https://duckduckgo.com/",
            "DNT": "1",
            "Connection": "keep-alive",
            "Upgrade-Insecure-Requests": "1"
        }
        
        # Configure proxy if provided
        proxy_config = None
        if proxy:
            proxy_config = proxy
        elif CONFIG["use_tor"]:
            proxy_config = f"socks5://127.0.0.1:{CONFIG['tor_port']}"
        
        connector = None
        if proxy_config:
            connector = aiohttp.TCPConnector()
        
        async with aiohttp.ClientSession(connector=connector) as session:
            # Calculate number of pages needed
            results_per_page = 30
            pages_needed = min((num_results + results_per_page - 1) // results_per_page, 5)  # Max 5 pages
            
            for page in range(pages_needed):
                s = page * results_per_page
                params = {
                    "q": query,
                    "s": s,
                    "dc": s + results_per_page,
                    "v": "l",
                    "o": "json",
                    "api": "/d.js"
                }
                
                retries = 0
                while retries < CONFIG["max_retries"]:
                    try:
                        # Random delay to avoid detection
                        await asyncio.sleep(random.uniform(*CONFIG["request_delay"]))
                        async with session.get(
                            self.base_url,
                            params=params,
                            headers=headers,
                            proxy=proxy_config,
                            timeout=aiohttp.ClientTimeout(total=CONFIG["timeout"]),
                            ssl=False
                        ) as response:
                            if response.status != 200:
                                logger.warning(f"DuckDuckGo returned status {response.status}")
                                retries += 1
                                continue
                            
                            html = await response.text()
                            soup = BeautifulSoup(html, 'html.parser')
                            
                            # Parse search results
                            search_divs = soup.find_all('div', class_='result')
                            
                            for div in search_divs:
                                # Extract title and URL
                                title_elem = div.find('a', class_='result__a')
                                if not title_elem:
                                    continue
                                
                                title = title_elem.get_text()
                                
                                # Extract URL
                                url = title_elem['href']
                                
                                # Extract snippet
                                snippet_elem = div.find('a', class_='result__snippet')
                                snippet = snippet_elem.get_text() if snippet_elem else ""
                                
                                results.append(SearchResult(
                                    title=title,
                                    url=url,
                                    snippet=snippet,
                                    engine="DuckDuckGo"
                                ))
                                
                                if len(results) >= num_results:
                                    return results
                            
                            # If we got results, break the retry loop
                            break
                            
                    except Exception as e:
                        logger.error(f"Error searching DuckDuckGo: {e}")
                        retries += 1
                        await asyncio.sleep(2 ** retries)  # Exponential backoff
        
        return results

class DorkParserBot:
    """Main bot class for handling Telegram interactions"""
    
    def __init__(self):
        self.search_engines = {
            "google": GoogleSearchEngine(),
            "bing": BingSearchEngine(),
            "yahoo": YahooSearchEngine(),
            "yandex": YandexSearchEngine(),
            "duckduckgo": DuckDuckGoSearchEngine()
        }
        self.active_searches = {}  # Track active searches by user_id
        self.executor = ThreadPoolExecutor(max_workers=CONFIG["max_concurrent_searches"])
    
    async def start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle the /start command"""
        welcome_message = (
            "🔍 *Advanced Dork Parser Bot*\n\n"
            "I can help you search across multiple search engines using advanced dorks.\n\n"
            "Commands:\n"
            "/search - Search with a single dork\n"
            "/file - Upload a .txt file with multiple dorks\n"
            "/engines - List available search engines\n"
            "/proxy - Set proxy for searches\n"
            "/help - Get help\n\n"
            "Simply send me a dork or upload a .txt file with multiple dorks to get started!"
        )
        
        await update.message.reply_text(
            welcome_message,
            parse_mode=ParseMode.MARKDOWN
        )
    
    async def help_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle the /help command"""
        help_message = (
            "🔍 *Advanced Dork Parser Bot Help*\n\n"
            "*Basic Usage:*\n"
            "• Send a dork directly to the bot to search\n"
            "• Use /file to upload a .txt file with multiple dorks\n\n"
            "*Advanced Features:*\n"
            "• Use /proxy to set a proxy for all searches\n"
            "• Use /engines to select specific search engines\n"
            "• Results are combined and deduplicated\n\n"
            "*Dork Examples:*\n"
            "• `site:example.com`\n"
            "• `inurl:admin filetype:pdf`\n"
            "*Tips:*\n"
            "• Use quotes for exact phrases\n"
            "• Combine operators for better results\n"
            "• Upload multiple dorks in a .txt file for batch processing"
        )
        
        await update.message.reply_text(
            help_message,
            parse_mode=ParseMode.MARKDOWN
        )


        





    async def search_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle the /search command"""
        # Check if user provided a query after /search
        if context.args:
            query = " ".join(context.args)
            await self.process_search(update, context, [query])
        else:
            await update.message.reply_text(
                "Please provide a dork to search.\n\n"
                "Example: `/search site:example.com`\n"
                "Example: `/search inurl:admin filetype:pdf`",
                parse_mode=ParseMode.MARKDOWN
            )









    
    async def engines_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle the /engines command"""
        keyboard = []
        
        for engine_name in self.search_engines.keys():
            keyboard.append([InlineKeyboardButton(
                engine_name.capitalize(),
                callback_data=f"toggle_engine:{engine_name}"
            )])
        
        keyboard.append([InlineKeyboardButton("Search All", callback_data="toggle_engine:all")])
        keyboard.append([InlineKeyboardButton("Done", callback_data="engines_done")])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(
            "Select search engines to use:",
            reply_markup=reply_markup
        )
    
    async def proxy_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle the /proxy command"""
        await update.message.reply_text(
            "Please send your proxy in one of these formats:\n\n"
            "• HTTP: `http://user:pass@host:port`\n"
            "• SOCKS5: `socks5://user:pass@host:port`\n\n"
            "Or send `disable` to stop using a proxy."
        )
        
        # Store that we're waiting for a proxy
        context.user_data["waiting_for_proxy"] = True
    
    async def file_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle the /file command"""
        await update.message.reply_text(
            "Please upload a .txt file with one dork per line.\n\n"
            "The file should contain dorks like:\n"
            "site:example.com\n"
            "inurl:admin filetype:pdf\n"
            "intitle:\"index of\" \"parent directory\""
        )
        
        # Store that we're waiting for a file
        context.user_data["waiting_for_file"] = True
    
    async def handle_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle text messages"""
        text = update.message.text
        
        # Check if we're waiting for a proxy
        if context.user_data.get("waiting_for_proxy"):
            context.user_data["waiting_for_proxy"] = False
            
            if text.lower() == "disable":
                context.user_data["proxy"] = None
                await update.message.reply_text("Proxy disabled.")
            else:
                # Validate proxy format
                if text.startswith(("http://", "https://", "socks5://")):
                    context.user_data["proxy"] = text
                    await update.message.reply_text(f"Proxy set: {text}")
                else:
                    await update.message.reply_text("Invalid proxy format. Please try again.")
            return
        
        # Otherwise, treat as a search query
        await self.process_search(update, context, [text])
    
    async def handle_document(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle document uploads"""
        document = update.message.document
        
        # Check if we're waiting for a file
        if not context.user_data.get("waiting_for_file"):
            await update.message.reply_text(
                "Please use the /file command first before uploading a file."
            )
            return
        
        context.user_data["waiting_for_file"] = False
        
        # Check file type and size
        if not document.file_name.endswith('.txt'):
            await update.message.reply_text("Please upload a .txt file.")
            return
        
        if document.file_size > CONFIG["max_file_size"]:
            await update.message.reply_text(
                f"File too large. Maximum size is {CONFIG['max_file_size'] / (1024*1024):.1f}MB."
            )
            return
        
        # Download and process the file
        try:
            file = await context.bot.get_file(document.file_id)
            
            # Create a temporary file
            temp_file = f"temp_{document.file_name}"
            await file.download_to_drive(temp_file)
            
            # Read dorks from file
            async with aiofiles.open(temp_file, 'r') as f:
                content = await f.read()
                dorks = [line.strip() for line in content.split('\n') if line.strip()]
            
            # Clean up temp file
            await aiofiles.os.remove(temp_file)
            
            if not dorks:
                await update.message.reply_text("No dorks found in the file.")
                return
            
            await update.message.reply_text(
                f"Found {len(dorks)} dorks in the file. Starting search..."
            )
            
            # Process the search
            await self.process_search(update, context, dorks)
            
        except Exception as e:
            logger.error(f"Error processing file: {e}")
            await update.message.reply_text("Error processing file. Please try again.")
    
    async def process_search(self, update: Update, context: ContextTypes.DEFAULT_TYPE, dorks: List[str]) -> None:
        """Process search queries"""
        user_id = update.effective_user.id
        
        # Get selected engines or use all
        selected_engines = context.user_data.get("selected_engines", list(self.search_engines.keys()))
        proxy = context.user_data.get("proxy")
        
        # Create progress tracking
        progress = SearchProgress(
            total=len(dorks) * len(selected_engines),
            completed=0,
            current_engine="",
            message_id=0
        )
        
        # Send initial progress message
        progress_message = await update.message.reply_text(
            f"🔍 Starting search with {len(dorks)} dorks across {len(selected_engines)} engines...",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("Cancel", callback_data=f"cancel_search:{user_id}")]
            ])
        )
        progress.message_id = progress_message.message_id
        
        # Store progress for this user
        self.active_searches[user_id] = {
            "progress": progress,
            "results": [],
            "cancelled": False
        }
        
        # Start the search in the background
        asyncio.create_task(self.run_search(update, context, dorks, selected_engines, proxy, user_id))
    
    async def run_search(self, update: Update, context: ContextTypes.DEFAULT_TYPE, 
                        dorks: List[str], engines: List[str], proxy: Optional[str], user_id: int) -> None:
        """Run the actual search process"""
        user_search = self.active_searches.get(user_id)
        if not user_search:
            return
        
        progress = user_search["progress"]
        results = user_search["results"]
        
        try:
            # Process each dork
            for i, dork in enumerate(dorks):
                # Check if search was cancelled
                if user_search["cancelled"]:
                    await context.bot.edit_message_text(
                        chat_id=update.effective_chat.id,
                        message_id=progress.message_id,
                        text="❌ Search cancelled."
                    )
                    return
                
                # Update progress
                progress.current_engine = f"Processing dork {i+1}/{len(dorks)}"
                await self.update_progress(update, context, progress)
                
                # Search each engine
                for engine_name in engines:
                    # Check if search was cancelled
                    if user_search["cancelled"]:
                        await context.bot.edit_message_text(
                            chat_id=update.effective_chat.id,
                            message_id=progress.message_id,
                            text="❌ Search cancelled."
                        )
                        return
                    
                    # Update progress
                    progress.current_engine = f"Searching {engine_name.capitalize()} for dork {i+1}/{len(dorks)}"
                    await self.update_progress(update, context, progress)
                    
                    try:
                        # Get the search engine
                        engine = self.search_engines.get(engine_name)
                        if not engine:
                            continue
                        
                        # Perform search
                        engine_results = await engine.search(
                            dork, 
                            num_results=CONFIG["default_results_per_engine"],
                            proxy=proxy
                        )
                        
                        # Add results to our collection
                        results.extend(engine_results)
                        
                        # Update progress
                        progress.completed += 1
                        await self.update_progress(update, context, progress)
                        
                    except Exception as e:
                        logger.error(f"Error searching {engine_name}: {e}")
                        # Still update progress
                        progress.completed += 1
                        await self.update_progress(update, context, progress)
            
            # Process and deduplicate results
            unique_results = self.deduplicate_results(results)
            
            # Send final results
            await self.send_results(update, context, unique_results, dorks)
            
        except Exception as e:
            logger.error(f"Error in search process: {e}")
            await context.bot.edit_message_text(
                chat_id=update.effective_chat.id,
                message_id=progress.message_id,
                text=f"❌ Error during search: {str(e)}"
            )
        finally:
            # Clean up
            if user_id in self.active_searches:
                del self.active_searches[user_id]
    
    async def update_progress(self, update: Update, context: ContextTypes.DEFAULT_TYPE, 
                            progress: SearchProgress) -> None:
        """Update the progress message"""
        try:
            percentage = (progress.completed / progress.total) * 100 if progress.total > 0 else 0
            progress_bar = "█" * int(percentage / 5) + "░" * (20 - int(percentage / 5))
            
            await context.bot.edit_message_text(
                chat_id=update.effective_chat.id,
                message_id=progress.message_id,
                text=f"🔍 Searching...\n\n"
                     f"Progress: {progress_bar} {percentage:.1f}%\n"
                     f"Completed: {progress.completed}/{progress.total}\n"
                     f"Current: {progress.current_engine}",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("Cancel", callback_data=f"cancel_search:{update.effective_user.id}")]
                ])
            )
        except Exception as e:
            logger.error(f"Error updating progress: {e}")
    
    def deduplicate_results(self, results: List[SearchResult]) -> List[SearchResult]:
        """Deduplicate results by URL"""
        seen_urls = set()
        unique_results = []
        
        for result in results:
            # Normalize URL for comparison
            url = result.url.lower()
            if url not in seen_urls:
                seen_urls.add(url)
                unique_results.append(result)
        
        return unique_results
    
    async def send_results(self, update: Update, context: ContextTypes.DEFAULT_TYPE, 
                          results: List[SearchResult], dorks: List[str]) -> None:
        """Send the search results"""
        user_id = update.effective_user.id
        user_search = self.active_searches.get(user_id)
        
        if not user_search:
            return
        
        progress = user_search["progress"]
        
        # Update progress message to show completion
        await context.bot.edit_message_text(
            chat_id=update.effective_chat.id,
            message_id=progress.message_id,
            text=f"✅ Search completed! Found {len(results)} unique results."
        )
        
        if not results:
            await update.message.reply_text("No results found for the given dorks.")
            return
        
        # Group results by engine
        results_by_engine = {}
        for result in results:
            if result.engine not in results_by_engine:
                results_by_engine[result.engine] = []
            results_by_engine[result.engine].append(result)
        
        # Create a summary message
        summary = f"🔍 *Search Results*\n\n"
        summary += f"Dorks searched: {len(dorks)}\n"
        summary += f"Total unique results: {len(results)}\n\n"
        
        for engine, engine_results in results_by_engine.items():
            summary += f"{engine.capitalize()}: {len(engine_results)} results\n"
        
        summary += "\n*Top Results:*\n"
        
        # Add top 5 results
        for i, result in enumerate(results[:5]):
            summary += f"\n{i+1}. [{result.title}]({result.url})\n"
            summary += f"   {result.snippet[:100]}{'...' if len(result.snippet) > 100 else ''}\n"
            summary += f"   _Source: {result.engine}_\n"
        
        await update.message.reply_text(
            summary,
            parse_mode=ParseMode.MARKDOWN,
            disable_web_page_preview=True
        )
        
        # Create a file with all results
        await self.create_results_file(update, context, results, dorks)
    
    async def create_results_file(self, update: Update, context: ContextTypes.DEFAULT_TYPE, 
                                results: List[SearchResult], dorks: List[str]) -> None:
        """Create a file with all results"""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"dork_results_{timestamp}.txt"
        
        try:
            # Create the file content
            content = f"Advanced Dork Parser Results\n"
            content += f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
            content += f"Dorks searched: {len(dorks)}\n"
            content += f"Total results: {len(results)}\n\n"
            
            content += "Dorks:\n"
            for i, dork in enumerate(dorks, 1):
                content += f"{i}. {dork}\n"
            
            content += "\nResults:\n\n"
            
            # Group results by engine
            results_by_engine = {}
            for result in results:
                if result.engine not in results_by_engine:
                    results_by_engine[result.engine] = []
                results_by_engine[result.engine].append(result)
            
            for engine, engine_results in results_by_engine.items():
                content += f"=== {engine.upper()} RESULTS ===\n\n"
                
                for i, result in enumerate(engine_results, 1):
                    content += f"{i}. {result.title}\n"
                    content += f"   URL: {result.url}\n"
                    content += f"   Snippet: {result.snippet}\n\n"
            
            # Write to file
            async with aiofiles.open(filename, 'w') as f:
                await f.write(content)
            
            # Send the file
            await context.bot.send_document(
                chat_id=update.effective_chat.id,
                document=open(filename, 'rb'),
                caption=f"Complete results for {len(dorks)} dorks"
            )
            
            # Clean up
            await aiofiles.os.remove(filename)
            
        except Exception as e:
            logger.error(f"Error creating results file: {e}")
            await update.message.reply_text("Error creating results file.")
    
    async def button_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle button callbacks"""
        query = update.callback_query
        await query.answer()
        
        data = query.data
        
        if data.startswith("toggle_engine:"):
            engine_name = data.split(":", 1)[1]
            
            if engine_name == "all":
                # Toggle all engines
                if len(context.user_data.get("selected_engines", [])) == len(self.search_engines):
                    # If all are selected, deselect all
                    context.user_data["selected_engines"] = []
                else:
                    # Select all
                    context.user_data["selected_engines"] = list(self.search_engines.keys())
            else:
                # Toggle specific engine
                selected_engines = context.user_data.get("selected_engines", [])
                
                if engine_name in selected_engines:
                    selected_engines.remove(engine_name)
                else:
                    selected_engines.append(engine_name)
                
                context.user_data["selected_engines"] = selected_engines
            
            # Update the message
            await self.update_engines_message(query, context)
            
        elif data == "engines_done":
            await query.edit_message_text("Search engines selection saved.")
            
        elif data.startswith("cancel_search:"):
            user_id = int(data.split(":", 1)[1])
            
            if user_id in self.active_searches:
                self.active_searches[user_id]["cancelled"] = True
    
    async def update_engines_message(self, query, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Update the engines selection message"""
        selected_engines = context.user_data.get("selected_engines", [])
        
        keyboard = []
        
        for engine_name in self.search_engines.keys():
            is_selected = engine_name in selected_engines
            keyboard.append([InlineKeyboardButton(
                f"{'✅ ' if is_selected else ''}{engine_name.capitalize()}",
                callback_data=f"toggle_engine:{engine_name}"
            )])
        
        keyboard.append([InlineKeyboardButton("Search All", callback_data="toggle_engine:all")])
        keyboard.append([InlineKeyboardButton("Done", callback_data="engines_done")])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            "Select search engines to use:",
            reply_markup=reply_markup
        )
    
    async def create_results_file(self, update: Update, context: ContextTypes.DEFAULT_TYPE, 
                                results: List[SearchResult], dorks: List[str]) -> None:
        """Create a file with only URLs from all results"""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"dork_urls_{timestamp}.txt"
        
        try:
            # Create the file content with only URLs
            content = f"Advanced Dork Parser - URLs Only\n"
            content += f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
            content += f"Dorks searched: {len(dorks)}\n"
            content += f"Total URLs: {len(results)}\n\n"
            
            content += "Dorks used:\n"
            for i, dork in enumerate(dorks, 1):
                content += f"{i}. {dork}\n"
            
            content += "\n" + "="*50 + "\n\n"
            content += "URLs:\n\n"
            
            # Group URLs by engine
            urls_by_engine = {}
            for result in results:
                if result.engine not in urls_by_engine:
                    urls_by_engine[result.engine] = set()
                urls_by_engine[result.engine].add(result.url)
            
            for engine, urls in urls_by_engine.items():
                content += f"=== {engine.upper()} URLs ===\n"
                for url in sorted(urls):
                    content += f"{url}\n"
                content += "\n"
            
            # Also add all URLs without duplicates at the end
            content += "="*50 + "\n\n"
            content += "ALL UNIQUE URLS:\n\n"
            
            all_urls = set()
            for result in results:
                all_urls.add(result.url)
            
            for url in sorted(all_urls):
                content += f"{url}\n"
            
            # Write to file
            async with aiofiles.open(filename, 'w') as f:
                await f.write(content)
            
            # Send the file
            await context.bot.send_document(
                chat_id=update.effective_chat.id,
                document=open(filename, 'rb'),
                caption=f"URLs only - {len(all_urls)} unique URLs from {len(dorks)} dorks"
            )
            
            # Clean up
            await aiofiles.os.remove(filename)
            
        except Exception as e:
            logger.error(f"Error creating results file: {e}")
            await update.message.reply_text("Error creating results file.")
    
    def run(self) -> None:
        """Run the bot"""
        application = Application.builder().token(CONFIG["telegram_token"]).build()
        
        # Add handlers
        application.add_handler(CommandHandler("start", self.start_command))
        application.add_handler(CommandHandler("help", self.help_command))
        application.add_handler(CommandHandler("engines", self.engines_command))
        application.add_handler(CommandHandler("proxy", self.proxy_command))
        application.add_handler(CommandHandler("file", self.file_command))
        
        # ✅ YE LINE ADD KAREIN:
        application.add_handler(CommandHandler("search", self.search_command)) 
        
        application.add_handler(CallbackQueryHandler(self.button_callback))
        application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_message))
        application.add_handler(MessageHandler(filters.Document.ALL, self.handle_document))
        
        # Run the bot
        application.run_polling()

def main():
    """Main function to start the bot"""
    bot = DorkParserBot()
    bot.run()

if __name__ == "__main__":
    main()
                       
