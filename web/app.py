#!/usr/bin/env python3

import os
import sys
import json
import subprocess
from pathlib import Path
from datetime import datetime, date
from typing import Dict, List, Any, Optional
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

import subprocess
import json
import csv
import os

from flask import Flask, render_template, jsonify, request, send_from_directory
from flask_cors import CORS

# Add src to path for imports
PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from equity_sorter.config import load_settings
from equity_sorter.io_utils import read_json, read_jsonl, read_csv

app = Flask(__name__, static_folder='static', template_folder='templates')
CORS(app)

settings = load_settings()

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/status')
def get_status():
    """Get system status and configuration."""
    return jsonify({
        'project_root': str(settings.project_root),
        'data_dir': str(settings.data_dir),
        'output_dir': str(settings.output_dir),
        'eodhd_configured': bool(settings.eodhd_api_key),
        'sec_user_agent': settings.sec_user_agent,
        'free_us_sample_tickers': settings.free_us_sample_tickers
    })

@app.route('/api/pipelines')
def get_pipelines():
    """Get available pipeline configurations."""
    return jsonify([
        {
            'id': 'free_us_demo',
            'name': 'Free US Demo',
            'description': 'Free data sources (SEC, Nasdaq, Stooq)',
            'requires_api_key': False,
            'estimated_time': '2-5 minutes'
        },
        {
            'id': 'eodhd_us_sample',
            'name': 'EODHD US Sample',
            'description': 'EODHD API data for US equities',
            'requires_api_key': True,
            'estimated_time': '5-10 minutes'
        },
        {
            'id': 'public_us_phase0',
            'name': 'Public US Phase 0',
            'description': 'SEC public data with local prices',
            'requires_api_key': False,
            'estimated_time': '3-8 minutes'
        }
    ])

@app.route('/api/analysis-configs')
def get_analysis_configs():
    """Get available analysis configurations."""
    try:
        from config import get_default_configs, get_stock_universe_info
        configs = get_default_configs()
        universe_info = get_stock_universe_info()
        
        # Convert configs to JSON-serializable format
        serializable_configs = {}
        for name, config in configs.items():
            serializable_configs[name] = {
                'max_stocks': config.max_stocks,
                'min_market_cap_millions': config.min_market_cap_millions,
                'exclude_financials': config.exclude_financials,
                'exclude_utilities': config.exclude_utilities,
                'countries': config.countries,
                'quality_weight': config.quality_weight,
                'value_weight': config.value_weight,
                'growth_weight': config.growth_weight,
                'safety_weight': config.safety_weight,
                'momentum_weight': config.momentum_weight,
                'quality_metrics': config.quality_metrics,
                'value_metrics': config.value_metrics,
                'growth_metrics': config.growth_metrics,
                'safety_metrics': config.safety_metrics,
                'momentum_metrics': config.momentum_metrics,
            }
        
        return jsonify({
            'configs': serializable_configs,
            'universes': universe_info
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/bulk-download', methods=['POST'])
def bulk_download():
    """Download bulk data for maximum local coverage."""
    data = request.json
    exchange = data.get('exchange', 'US')
    max_companies = data.get('max_companies', None)
    
    try:
        # Import and run bulk download
        sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
        from download_bulk_eodhd_data import download_bulk_data
        
        result = download_bulk_data(settings, exchange, max_companies)
        return jsonify({
            'success': True,
            'result': result
        })
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/comprehensive-download', methods=['POST'])
def comprehensive_download():
    """Download comprehensive data with maximum extraction from EODHD."""
    data = request.json
    exchange = data.get('exchange', 'US')
    max_companies = data.get('max_companies', None)
    
    try:
        # Import and run comprehensive download
        sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
        from download_comprehensive_eodhd_data import download_comprehensive_data
        
        result = download_comprehensive_data(settings, exchange, max_companies)
        return jsonify({
            'success': True,
            'result': result
        })
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/data-coverage-analysis')
def data_coverage_analysis():
    """Analyze what data we can gather vs the comprehensive requirements."""
    try:
        coverage = {
            "available_from_eodhd": {
                "basic_company_info": [
                    "Company name", "Ticker", "Exchange", "Country", "Currency", 
                    "Sector", "Industry", "Company description", "Market cap", "Enterprise value"
                ],
                "financial_statements": [
                    "Revenue", "Gross profit", "Operating income", "EBIT", "EBITDA", 
                    "Net income", "EPS", "Operating cash flow", "Capex", "Free cash flow",
                    "Cash", "Debt", "Equity", "Assets", "Liabilities", "Working capital"
                ],
                "market_data": [
                    "Historical prices", "Dividends", "Stock splits", "Volume", 
                    "52-week high/low", "Volatility", "Beta", "Momentum indicators"
                ],
                "valuation_metrics": [
                    "P/E", "P/S", "P/B", "EV/EBITDA", "EV/FCF", "Yield metrics",
                    "Historical valuation percentiles"
                ],
                "news_and_sentiment": [
                    "Latest news headlines", "Full news articles", "Historical news",
                    "News sentiment scores", "Social media sentiment", "Word frequency analysis",
                    "News volume trends", "Sentiment trends over time"
                ]
            },
            "missing_from_current_sources": {
                "business_model_analysis": [
                    "Business model summary", "Main products/services", "Revenue streams",
                    "Operating segments", "Geographic revenue split", "Customer types",
                    "End markets", "Main competitors", "Competitive advantages"
                ],
                "moat_analysis": [
                    "Brand moat indicators", "Scale advantages", "Network effects",
                    "Switching costs", "Cost advantages", "Distribution advantages",
                    "Regulatory advantages", "Patent/IP advantages", "Data/ecosystem advantages"
                ],
                "customer_metrics": [
                    "Recurring revenue indicators", "Subscription revenue", "Contract length",
                    "Customer retention", "Churn disclosures", "Net revenue retention",
                    "Customer concentration", "Customer acquisition costs"
                ],
                "risk_analysis": [
                    "Supplier concentration", "Government customer exposure", "Commodity exposure",
                    "FX exposure", "Interest rate exposure", "Regulatory exposure",
                    "Litigation exposure", "Environmental liability", "Cybersecurity risks"
                ],
                "management_governance": [
                    "Management team analysis", "Insider ownership/trading", "Capital allocation quality",
                    "Accounting quality metrics", "Board composition", "Executive compensation"
                ],
                "advanced_metrics": [
                    "SaaS metrics (LTV/CAC, churn)", "Industry-specific metrics", "Peer comparisons",
                    "Quality scores", "Moat scores", "Risk scores", "Management scores"
                ]
            },
            "data_augmentation_opportunities": {
                "sec_edgar_filings": "Business descriptions, risk factors, management discussion",
                "eodhd_news_sentiment": "Management tone, controversies, competitive positioning, news sentiment analysis",
                "industry_databases": "Peer comparisons, market share, competitive landscape",
                "alternative_data": "Supply chain data, web traffic, app downloads, hiring data",
                "manual_research": "Management calls, investor presentations, industry reports"
            },
            "recommended_strategy": {
                "phase_1": "Download maximum EODHD data (prices, fundamentals, corporate actions)",
                "phase_2": "Add EODHD news and sentiment data for qualitative insights",
                "phase_3": "Augment with SEC Edgar data (business descriptions, risk factors)",
                "phase_4": "Add industry classification and peer group analysis",
                "phase_5": "Implement calculated metrics (margins, ratios, growth rates)",
                "phase_6": "Add scoring systems for quality, value, growth, safety, momentum"
            },
            "current_capabilities": {
                "total_metrics_available": "~180 financial, market, and sentiment metrics",
                "historical_depth": "5-10 years of historical data + news sentiment",
                "coverage": "57,000+ US securities (EODHD)",
                "update_frequency": "Daily for prices/news, quarterly for fundamentals",
                "confidence_level": "High for quantitative data, Medium for sentiment data"
            }
        }
        
        return jsonify(coverage)
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/news-download', methods=['POST'])
def news_download():
    """Download news and sentiment data for companies."""
    data = request.json
    symbols = data.get('symbols', [])
    max_symbols = data.get('max_symbols', 100)
    days_back = data.get('days_back', 30)
    market_news = data.get('market_news', False)
    
    try:
        # Import and run news download
        sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
        from download_eodhd_news_data import download_bulk_news_data, download_market_news_data
        
        results = {}
        
        # Download market news if requested
        if market_news:
            market_news_data = download_market_news_data(settings, days_back)
            results['market_news'] = len(market_news_data) if market_news_data else 0
        
        # Get symbols to process
        if not symbols:
            # Load symbols from existing data
            from equity_sorter.io_utils import read_jsonl
            listings_dir = settings.data_dir / "silver" / "listings" / "exchange=US"
            if listings_dir.exists():
                for date_dir in listings_dir.iterdir():
                    if date_dir.is_dir():
                        listings_file = date_dir / "rows.jsonl"
                        if listings_file.exists():
                            listings = read_jsonl(listings_file)
                            symbols = [listing.get('ticker') for listing in listings[:max_symbols] if listing.get('ticker')]
                            break
        
        if symbols:
            news_result = download_bulk_news_data(settings, 'US', symbols, days_back)
            results['company_news'] = news_result
        
        return jsonify({
            'success': True,
            'results': results
        })
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/companies')
def get_companies():
    """Get list of companies with basic data."""
    try:
        # Load from normalized silver data
        listings_dir = settings.data_dir / "silver" / "listings"
        companies = []
        
        if listings_dir.exists():
            for exchange_dir in listings_dir.iterdir():
                if exchange_dir.is_dir() and exchange_dir.name.startswith("exchange="):
                    exchange = exchange_dir.name.split("=")[1]
                    for date_dir in exchange_dir.iterdir():
                        if date_dir.is_dir() and date_dir.name.startswith("date="):
                            listings_file = date_dir / "rows.jsonl"
                            if listings_file.exists():
                                from equity_sorter.io_utils import read_jsonl
                                listings = read_jsonl(listings_file)
                                for listing in listings[:1000]:  # Limit for performance
                                    companies.append({
                                        'ticker': listing.get('ticker'),
                                        'company_name': listing.get('company_name', listing.get('ticker')),
                                        'exchange': exchange,
                                        'country': listing.get('country'),
                                        'currency': listing.get('currency'),
                                        'security_id': listing.get('security_id')
                                    })
        
        return jsonify({
            'companies': companies,
            'total_count': len(companies)
        })
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/company/<security_id>')
def get_company_details(security_id):
    """Get detailed information for a specific company."""
    try:
        # Load comprehensive company data
        company_data = {}
        
        # Load from bronze data
        bronze_dir = settings.data_dir / "bronze" / f"provider={settings.provider_name}" / "dataset=company_data"
        
        # Find company data across exchanges
        for exchange_dir in bronze_dir.iterdir():
            if exchange_dir.is_dir() and exchange_dir.name.startswith("exchange="):
                for symbol_dir in exchange_dir.iterdir():
                    if symbol_dir.is_dir() and symbol_dir.name.startswith("symbol="):
                        for date_dir in symbol_dir.iterdir():
                            if date_dir.is_dir():
                                # Check if this matches our security_id
                                prices_file = date_dir / "prices.json"
                                if prices_file.exists():
                                    from equity_sorter.io_utils import read_json
                                    prices_data = read_json(prices_file)
                                    if prices_data and prices_data.get('payload'):
                                        # Try to match by symbol or other identifier
                                        symbol = symbol_dir.name.split("=")[1]
                                        if symbol == security_id or security_id in symbol:
                                            company_data = {
                                                'symbol': symbol,
                                                'exchange': exchange_dir.name.split("=")[1],
                                                'prices': prices_data['payload'],
                                                'fundamentals': {},
                                                'splits': [],
                                                'dividends': []
                                            }
                                            
                                            # Load fundamentals
                                            fundamentals_file = date_dir / "fundamentals.json"
                                            if fundamentals_file.exists():
                                                fundamentals_data = read_json(fundamentals_file)
                                                company_data['fundamentals'] = fundamentals_data.get('payload', {})
                                            
                                            # Load splits
                                            splits_file = date_dir / "splits.json"
                                            if splits_file.exists():
                                                splits_data = read_json(splits_file)
                                                company_data['splits'] = splits_data.get('payload', [])
                                            
                                            # Load dividends
                                            dividends_file = date_dir / "dividends.json"
                                            if dividends_file.exists():
                                                dividends_data = read_json(dividends_file)
                                                company_data['dividends'] = dividends_data.get('payload', [])
                                            
                                            break
                                if company_data:
                                    break
                            if company_data:
                                break
                        if company_data:
                            break
        
        if not company_data:
            return jsonify({'error': 'Company not found'}), 404
        
        return jsonify(company_data)
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/run-pipeline', methods=['POST'])
def run_pipeline():
    """Execute a pipeline with configuration."""
    data = request.json
    pipeline_id = data.get('pipeline_id')
    as_of_date = data.get('as_of_date', date.today().isoformat())
    max_count = data.get('max_count', 100)
    config_name = data.get('config_name', 'balanced')
    custom_config = data.get('custom_config', {})
    
    if not pipeline_id:
        return jsonify({'error': 'Pipeline ID required'}), 400
    
    try:
        # Load configuration
        try:
            from config import get_default_configs
            configs = get_default_configs()
            analysis_config = configs.get(config_name, configs['balanced'])
            
            # Override with custom config if provided
            if custom_config:
                for key, value in custom_config.items():
                    if hasattr(analysis_config, key):
                        setattr(analysis_config, key, value)
        except Exception as e:
            return jsonify({'error': f'Failed to load configuration: {e}'}), 500
        
        # Use configured max count
        actual_max_count = analysis_config.max_stocks if max_count == 100 else max_count
        
        # Map pipeline IDs to scripts with configuration
        pipeline_scripts = {
            'free_us_demo': [
                ('load_free_us_demo_fixture.py', []),
                ('run_garp_ranking.py', ['--as-of-date', as_of_date, '--exchange', 'US', '--snapshot-name', f'free_us_demo_{config_name}'])
            ],
            'eodhd_us_sample': [
                ('ingest_eodhd_sample.py', ['--exchange', 'US', '--country', 'USA', '--max-count', str(actual_max_count)]),
                ('build_sample_snapshot.py', ['--as-of-date', as_of_date, '--exchange', 'US', '--snapshot-name', f'eodhd_us_{config_name}']),
                ('run_garp_ranking.py', ['--as-of-date', as_of_date, '--exchange', 'US', '--snapshot-name', f'eodhd_us_{config_name}'])
            ],
            'public_us_phase0': [
                ('download_public_us_sample.py', ['--bronze-date', date.today().isoformat(), '--tickers', 'AAPL,MSFT,KO']),
                ('build_public_us_sample.py', ['--bronze-date', date.today().isoformat()]),
                ('run_garp_ranking.py', ['--as-of-date', as_of_date, '--exchange', 'US', '--snapshot-name', f'public_us_{config_name}'])
            ]
        }
        
        if pipeline_id not in pipeline_scripts:
            return jsonify({'error': f'Unknown pipeline: {pipeline_id}'}), 400
        
        # Execute pipeline scripts
        results = []
        scripts_dir = PROJECT_ROOT / "scripts"
        
        for script_name, args in pipeline_scripts[pipeline_id]:
            script_path = scripts_dir / script_name
            cmd = [sys.executable, str(script_path)] + args
            
            try:
                result = subprocess.run(
                    cmd,
                    cwd=str(PROJECT_ROOT),
                    capture_output=True,
                    text=True,
                    timeout=600  # 10 minute timeout per script
                )
                
                results.append({
                    'script': script_name,
                    'success': result.returncode == 0,
                    'stdout': result.stdout,
                    'stderr': result.stderr
                })
                
                if result.returncode != 0:
                    return jsonify({
                        'error': f'Script {script_name} failed',
                        'results': results
                    }), 500
                    
            except subprocess.TimeoutExpired:
                return jsonify({
                    'error': f'Script {script_name} timed out',
                    'results': results
                }), 500
        
        return jsonify({
            'success': True,
            'pipeline_id': pipeline_id,
            'as_of_date': as_of_date,
            'results': results
        })
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/results')
def get_results():
    """Get available ranking results."""
    output_dir = settings.output_dir
    results = []
    
    if output_dir.exists():
        for snapshot_dir in output_dir.iterdir():
            if snapshot_dir.is_dir() and snapshot_dir.name != 'quality':
                for date_dir in snapshot_dir.iterdir():
                    if date_dir.is_dir():
                        csv_file = date_dir / 'rankings.csv'
                        if csv_file.exists():
                            results.append({
                                'snapshot_name': snapshot_dir.name,
                                'date': date_dir.name,
                                'path': str(csv_file),
                                'size': csv_file.stat().st_size,
                                'modified': datetime.fromtimestamp(csv_file.stat().st_mtime).isoformat()
                            })
    
    # Sort by modified date, newest first
    results.sort(key=lambda x: x['modified'], reverse=True)
    return jsonify(results)

@app.route('/api/ranking/<snapshot_name>/<date>')
def get_ranking(snapshot_name: str, date: str):
    """Get ranking data for a specific snapshot and date."""
    try:
        csv_path = settings.output_dir / snapshot_name / date / 'rankings.csv'
        if not csv_path.exists():
            return jsonify({'error': 'Ranking file not found'}), 404
        
        # Read CSV and convert to JSON
        data = read_csv(csv_path)
        return jsonify({
            'snapshot_name': snapshot_name,
            'date': date,
            'data': data,
            'total_count': len(data) if data else 0
        })
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/quality-reports')
def get_quality_reports():
    """Get available quality reports."""
    quality_dir = settings.output_dir / 'quality'
    reports = []
    
    if quality_dir.exists():
        for exchange_dir in quality_dir.iterdir():
            if exchange_dir.is_dir():
                for date_dir in exchange_dir.iterdir():
                    if date_dir.is_dir():
                        events_file = date_dir / 'events.jsonl'
                        if events_file.exists():
                            reports.append({
                                'exchange': exchange_dir.name,
                                'date': date_dir.name,
                                'path': str(events_file),
                                'size': events_file.stat().st_size
                            })
    
    return jsonify(reports)

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
