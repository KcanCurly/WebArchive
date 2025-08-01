#!/usr/bin/env python3
"""
WebArchive Subdomain Extractor
Advanced Wayback Machine subdomain extraction tool

Usage:
    python web.archive.py <domain>

Copyright (C) 2025 Cuma KURT
Email: cumakurt [at] gmail [dot] com
LinkedIn: https://www.linkedin.com/in/cuma-kurt-34414917/

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with this program.  If not, see <https://www.gnu.org/licenses/>.
"""
import sys 
import os
import re
import json
import csv
import time
import logging
import argparse
import configparser
from urllib.parse import urlparse
from functools import wraps
from typing import List, Dict, Optional, Any
import requests
from prettytable import PrettyTable
from termcolor import colored
from tqdm import tqdm
import dns.resolver


# Global logger
logger = None

def setup_logging(level: int = logging.INFO, log_file: str = 'webarchive.log') -> logging.Logger:
    """Setup logging configuration."""
    global logger
    
    # Create logs directory if it doesn't exist
    try:
        os.makedirs('logs', exist_ok=True)
        log_path = os.path.join('logs', log_file)
        
        # Test if we can write to the logs directory
        test_file = os.path.join('logs', 'test.log')
        with open(test_file, 'w') as f:
            f.write('test')
        os.remove(test_file)
        
        handlers = [
            logging.FileHandler(log_path, encoding='utf-8'),
            logging.StreamHandler()
        ]
    except (PermissionError, OSError):
        # If we can't write to logs directory, only use console handler
        handlers = [logging.StreamHandler()]
    
    logging.basicConfig(
        level=level,
        format='%(asctime)s - %(levelname)s - %(message)s',
        handlers=handlers
    )
    
    logger = logging.getLogger(__name__)
    return logger

def load_config(config_file: str = 'config.ini') -> Dict[str, Any]:
    """Load configuration from file or use defaults."""
    config = {
        'api_url': 'https://web.archive.org/cdx/search/cdx',
        'output_format': 'txt',
        'collapse': 'urlkey',
        'max_results': 10000,
        'timeout': 30,
        'max_retries': 3,
        'retry_delay': 1,
        'user_agent': 'WebArchive-Subdomain-Extractor/1.0'
    }
    
    if os.path.exists(config_file):
        try:
            parser = configparser.ConfigParser()
            parser.read(config_file)
            
            if 'DEFAULT' in parser:
                for key in config.keys():
                    if key in parser['DEFAULT']:
                        value = parser['DEFAULT'][key]
                        # Convert numeric values to appropriate types
                        if key in ['timeout', 'max_retries', 'retry_delay', 'max_results']:
                            try:
                                config[key] = int(value)
                            except ValueError:
                                logger.warning(f"Invalid {key} value in config: {value}, using default")
                        else:
                            config[key] = value
                        
            logger.info(f"Configuration loaded from {config_file}")
        except Exception as e:
            logger.warning(f"Failed to load config file: {e}")
    
    return config

def validate_domain(domain: str) -> str:
    """Validate domain format."""
    domain_pattern = r'^[a-zA-Z0-9]([a-zA-Z0-9\-]{0,61}[a-zA-Z0-9])?(\.[a-zA-Z0-9]([a-zA-Z0-9\-]{0,61}[a-zA-Z0-9])?)*$'
    if not re.match(domain_pattern, domain):
        raise ValueError(f"Invalid domain format: {domain}")
    return domain.lower()

def sanitize_filename(filename: str) -> str:
    """Sanitize filename for safe file operations."""
    return re.sub(r'[<>:"/\\|?*]', '_', filename)

def retry_on_failure(max_retries: int = 3, delay: int = 1):
    """Decorator for retrying failed operations."""
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            for attempt in range(max_retries):
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    if attempt == max_retries - 1:
                        logger.error(f"Final attempt failed: {e}")
                        raise e
                    logger.warning(f"Attempt {attempt + 1} failed: {e}, retrying in {delay}s...")
                    time.sleep(delay)
            return None
        return wrapper
    return decorator

@retry_on_failure(max_retries=3, delay=2)
def fetch_data_with_progress(domain: str, config: Dict[str, Any]) -> List[str]:
    """Fetch data with progress bar and error handling."""
    params = {
        'url': f'*.{domain}/*',
        'output': 'txt',
        'fl': 'original',
        'collapse': config.get('collapse', 'urlkey'),
        'limit': config.get('max_results', 10000)
    }
    
    headers = {
        'User-Agent': config.get('user_agent', 'WebArchive-Subdomain-Extractor/1.0')
    }
    
    logger.info(f"Fetching data for domain: {domain}")
    print(colored(f"\nFetching data for domain: {domain}", "blue"))
    
    try:
        response = requests.get(
            config['api_url'], 
            params=params, 
            headers=headers,
            timeout=config.get('timeout', 30),
            stream=True
        )
        response.raise_for_status()
        
        # Process data with progress bar
        lines = []
        total_lines = 0
        
        # First estimate line count
        for line in response.iter_lines():
            if line:
                total_lines += 1
        
        # Fetch data again and process with progress bar
        response = requests.get(
            config['api_url'], 
            params=params, 
            headers=headers,
            timeout=config.get('timeout', 30)
        )
        response.raise_for_status()
        
        for line in tqdm(response.text.splitlines(), desc="Fetching URLs", unit="url"):
            if line.strip():
                lines.append(line.strip())
        
        logger.info(f"Successfully fetched {len(lines)} URLs")
        return lines
        
    except requests.exceptions.RequestException as e:
        logger.error(f"Failed to fetch data: {e}")
        print(colored(f"[ERROR] Failed to fetch data: {e}", "red"))
        raise

def extract_subdomains(urls: List[str]) -> List[str]:
    """Extract unique subdomains using proper URL parsing."""
    subdomains = set()
    
    logger.info(f"Extracting subdomains from {len(urls)} URLs")
    
    for url in urls:
        try:
            # Use urllib.parse for URL parsing
            parsed = urlparse(url)
            hostname = parsed.netloc.split(":")[0]  # Remove port number
            
            # Valid hostname check
            if hostname and '.' in hostname:
                subdomains.add(hostname)
                
        except Exception as e:
            logger.debug(f"Failed to parse URL {url}: {e}")
            continue
    
    result = sorted(subdomains)
    logger.info(f"Extracted {len(result)} unique subdomains")
    return result

def filter_subdomains(subdomains: List[str], filters: Optional[Dict[str, Any]] = None) -> List[str]:
    """Filter subdomains based on criteria."""
    if not filters:
        return subdomains
    
    logger.info("Applying filters to subdomains")
    filtered = []
    
    for subdomain in subdomains:
        # Regex filtering
        if filters.get('regex') and not re.search(filters['regex'], subdomain):
            continue
            
        # Length filtering
        if filters.get('min_length') and len(subdomain) < filters['min_length']:
            continue
            
        if filters.get('max_length') and len(subdomain) > filters['max_length']:
            continue
            
        # Word exclusion filtering
        if filters.get('exclude_words'):
            exclude_words = filters['exclude_words']
            if any(word in subdomain.lower() for word in exclude_words):
                continue
                
        filtered.append(subdomain)
    
    logger.info(f"Filtered subdomains: {len(filtered)} remaining")
    return filtered

def save_results(domain: str, subdomains: List[str], output_dir: str, 
                formats: List[str] = ['txt', 'json', 'csv']) -> Dict[str, str]:
    """Save results in multiple formats."""
    base_name = sanitize_filename(domain.replace('.', '_'))
    saved_files = {}
    
    # Create output directory
    os.makedirs(output_dir, exist_ok=True)
    
    logger.info(f"Saving results in formats: {formats}")
    
    for fmt in formats:
        try:
            if fmt == 'txt':
                file_path = os.path.join(output_dir, f"{base_name}_subdomains.txt")
                with open(file_path, "w", encoding='utf-8') as f:
                    f.write("\n".join(subdomains))
                saved_files['txt'] = file_path
                
            elif fmt == 'json':
                file_path = os.path.join(output_dir, f"{base_name}_subdomains.json")
                data = {
                    'domain': domain,
                    'subdomain_count': len(subdomains),
                    'extraction_date': time.strftime('%Y-%m-%d %H:%M:%S'),
                    'subdomains': subdomains
                }
                with open(file_path, "w", encoding='utf-8') as f:
                    json.dump(data, f, indent=2, ensure_ascii=False)
                saved_files['json'] = file_path
                
            elif fmt == 'csv':
                file_path = os.path.join(output_dir, f"{base_name}_subdomains.csv")
                with open(file_path, "w", newline='', encoding='utf-8') as f:
                    writer = csv.writer(f)
                    writer.writerow(['index', 'subdomain'])
                    for i, subdomain in enumerate(subdomains, 1):
                        writer.writerow([i, subdomain])
                saved_files['csv'] = file_path
                
        except Exception as e:
            logger.error(f"Failed to save {fmt} format: {e}")
    
    return saved_files

def save_raw_data(domain: str, urls: List[str], output_dir: str) -> str:
    """Save raw URLs to a file."""
    base_name = sanitize_filename(domain.replace('.', '_'))
    raw_file_path = os.path.join(output_dir, f"{base_name}_raw_urls.txt")
    
    try:
        with open(raw_file_path, "w", encoding='utf-8') as f:
            f.write("\n".join(urls))
        logger.info(f"Raw data saved to: {raw_file_path}")
        return raw_file_path
    except Exception as e:
        logger.error(f"Failed to save raw data: {e}")
        raise

def dns_check_domain(subdomains):
    valid_subdomains = []
    for domain in subdomains:
        answers = dns.resolver.resolve(domain, "A")
        if answers:
            valid_subdomains.append(domain)
    return valid_subdomains


def display_results(domain: str, subdomains: List[str], saved_files: Dict[str, str], 
                   raw_file: str, verbose: bool = False):
    """Display results with enhanced formatting."""
    subdomain_count = len(subdomains)
    
    print(colored("\n" + "="*60, "cyan"))
    print(colored("           RESULTS", "cyan"))
    print(colored("="*60, "cyan"))
    
    print(colored(f"\nDomain: {domain}", "blue"))
    print(colored(f"Total unique subdomains: {subdomain_count}", "green"))
    print(colored(f"Extraction date: {time.strftime('%Y-%m-%d %H:%M:%S')}", "blue"))
    
    # Show file paths
    print(colored("\nSaved files:", "yellow"))
    for fmt, file_path in saved_files.items():
        print(colored(f"       {fmt.upper()}: {file_path}", "yellow"))
    print(colored(f"       Raw data: {raw_file}", "yellow"))
    
    # Display subdomain list in table format
    if subdomains:
        print(colored("\n[RESULT] Subdomain List:", "cyan"))
        table = PrettyTable(["Index", "Subdomain"])
        table.align = "l"
        
        # Show all in verbose mode, otherwise first 20
        display_list = subdomains if verbose else subdomains[:20]
        
        for i, subdomain in enumerate(display_list, 1):
            table.add_row([i, subdomain])
        
        print(table)
        
        if not verbose and len(subdomains) > 20:
            print(colored(f"\n[NOTE] Only first 20 subdomains shown. "
                         f"Use --verbose to see all {len(subdomains)} subdomains.", "yellow"))
    
    # Statistics
    if verbose:
        print(colored("\n[STATS] Statistics:", "cyan"))
        avg_length = sum(len(s) for s in subdomains) / len(subdomains) if subdomains else 0
        print(colored(f"       Average length: {avg_length:.1f} characters", "blue"))
        print(colored(f"       Shortest: {min(subdomains, key=len) if subdomains else 'N/A'}", "blue"))
        print(colored(f"       Longest: {max(subdomains, key=len) if subdomains else 'N/A'}", "blue"))

def parse_arguments():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description='Advanced Wayback Machine subdomain extractor with filtering and multiple output formats',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
EXAMPLES:
  Basic usage:
    python web.archive.py example.com
  
  Multiple output formats:
    python web.archive.py example.com --output-dir results --format txt json csv
  
  Filtering subdomains:
    python web.archive.py example.com --filter "test|dev" --exclude-words admin,test
  
  Advanced filtering:
    python web.archive.py example.com --min-length 10 --max-length 30 --verbose
  
  Custom configuration:
    python web.archive.py example.com --config custom_config.ini --log-level DEBUG

FEATURES:
  • Extract subdomains from Wayback Machine archives
  • Multiple output formats (TXT, JSON, CSV)
  • Advanced filtering with regex patterns
  • Progress tracking with visual indicators
  • Comprehensive logging system
  • Retry mechanism for failed requests
  • Domain validation and sanitization
  • Detailed statistics and reporting
        """
    )
    
    parser.add_argument('domain', 
                       help='Target domain to analyze (e.g., example.com)')
    
    parser.add_argument('--output-dir', '-o', 
                       default='.', 
                       help='Output directory for results (default: current directory)')
    
    parser.add_argument('--format', '-f', 
                       choices=['txt', 'json', 'csv'], 
                       nargs='+', 
                       default=['txt'], 
                       help='Output formats (default: txt, can specify multiple)')
    
    parser.add_argument('--filter', 
                       help='Regex pattern to filter subdomains (e.g., "test|dev|staging")')
    
    parser.add_argument('--exclude-words', 
                       help='Comma-separated words to exclude from subdomains (e.g., admin,test,dev)')
    
    parser.add_argument('--min-length', 
                       type=int, 
                       help='Minimum subdomain length (e.g., 10)')
    
    parser.add_argument('--max-length', 
                       type=int, 
                       help='Maximum subdomain length (e.g., 50)')
    
    parser.add_argument('--max-results', 
                       type=int, 
                       default=10000, 
                       help='Maximum number of results to fetch (default: 10000)')
    
    parser.add_argument('--verbose', '-v', 
                       action='store_true', 
                       help='Enable verbose output with detailed statistics')
    
    parser.add_argument('--config', '-c', 
                       default='config.ini', 
                       help='Configuration file path (default: config.ini)')
    
    parser.add_argument('--log-level', 
                       choices=['DEBUG', 'INFO', 'WARNING', 'ERROR'], 
                       default='INFO', 
                       help='Logging level (default: INFO)')
    
    return parser.parse_args()

def main():
    """Main function."""
    args = parse_arguments()
    
    # Setup logging
    log_level = getattr(logging, args.log_level.upper())
    setup_logging(level=log_level)
    
    try:
        # Validate domain
        domain = validate_domain(args.domain)
        logger.info(f"Starting analysis for domain: {domain}")
        
        # Load configuration
        config = load_config(args.config)
        config['max_results'] = args.max_results
        
        # Prepare filters
        filters = {}
        if args.filter:
            filters['regex'] = args.filter
        if args.exclude_words:
            filters['exclude_words'] = [word.strip() for word in args.exclude_words.split(',')]
        if args.min_length:
            filters['min_length'] = args.min_length
        if args.max_length:
            filters['max_length'] = args.max_length
        
        print(colored(f"\nStarting subdomain extraction for: {domain}", "blue"))
        if filters:
            print(colored(f"Active filters: {filters}", "blue"))
        
        # Fetch data
        urls = fetch_data_with_progress(domain, config)
        if not urls:
            print(colored("[WARNING] No data found for the given domain.", "yellow"))
            sys.exit(0)
        
        # Save raw data
        raw_file = save_raw_data(domain, urls, args.output_dir)
        
        # Extract subdomains
        subdomains = extract_subdomains(urls)

        # Dns check subdomains
        subdomains = dns_check_domain(subdomains)
        
        if not subdomains:
            print(colored("[WARNING] No subdomains could be extracted.", "yellow"))
            sys.exit(0)
        
        # Apply filtering
        if filters:
            original_count = len(subdomains)
            subdomains = filter_subdomains(subdomains, filters)
            logger.info(f"Filtering reduced subdomains from {original_count} to {len(subdomains)}")

        
        
        # Save results
        saved_files = save_results(domain, subdomains, args.output_dir, args.format)
        
        # Display results
        display_results(domain, subdomains, saved_files, raw_file, args.verbose)
        
        print(colored("\nOperation completed successfully!", "green"))
        
    except KeyboardInterrupt:
        print(colored("\nOperation cancelled by user.", "yellow"))
        sys.exit(1)
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
        print(colored(f"\nUnexpected error: {e}", "red"))
        sys.exit(1)

if __name__ == "__main__":
    main()
