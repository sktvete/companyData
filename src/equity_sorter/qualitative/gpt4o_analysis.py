#!/usr/bin/env python3

"""
GPT-4o Qualitative Analysis Integration
Phase 2: Business model, competitive advantage, and management analysis using OpenAI GPT-4o.
"""

from __future__ import annotations
import os
import json
from typing import Dict, List, Any, Optional
from datetime import datetime
import openai
from openai import OpenAI

class GPT4oQualitativeAnalyzer:
    """GPT-4o powered qualitative analysis for equity research."""
    
    def __init__(self, api_key: Optional[str] = None):
        """Initialize GPT-4o analyzer."""
        self.api_key = api_key or os.getenv("OPENAI_API_KEY")
        if not self.api_key:
            raise ValueError("OpenAI API key required for GPT-4o analysis")
        
        self.client = OpenAI(api_key=self.api_key)
        self.model = "gpt-4o"
    
    def analyze_business_model(self, company_data: Dict[str, Any]) -> Dict[str, Any]:
        """Analyze business model using GPT-4o."""
        
        symbol = company_data.get("symbol", "Unknown")
        company_info = company_data.get("company_info", {})
        financial_metrics = company_data.get("financial_metrics", {})
        
        prompt = f"""
        As an expert equity analyst, analyze the business model of {symbol} ({company_info.get('name', symbol)}).
        
        Company Information:
        - Sector: {company_info.get('sector', 'Unknown')}
        - Industry: {company_info.get('industry', 'Unknown')}
        - Description: {company_info.get('description', 'Not available')}
        
        Financial Highlights:
        - Revenue: ${financial_metrics.get('revenue', 0)/1e9:.1f}B
        - Gross Margin: {financial_metrics.get('gross_margin', 0)*100:.1f}%
        - Operating Margin: {financial_metrics.get('operating_margin', 0)*100:.1f}%
        - ROE: {financial_metrics.get('roe', 0)*100:.1f}%
        - Revenue Growth: {financial_metrics.get('revenue_growth_1y', 0)*100:.1f}%
        
        Provide a comprehensive business model analysis including:
        1. Business model summary (2-3 sentences)
        2. Main products/services
        3. Primary revenue streams
        4. Key operating segments
        5. Geographic revenue concentration
        6. Customer types and end markets
        7. Main competitive advantages
        8. Business model risks
        
        Format as JSON with these exact keys:
        {{
            "business_model_summary": "...",
            "main_products": ["...", "..."],
            "main_services": ["...", "..."],
            "revenue_streams": ["...", "..."],
            "operating_segments": ["...", "..."],
            "geographic_focus": "...",
            "customer_types": ["...", "..."],
            "end_markets": ["...", "..."],
            "competitive_advantages": ["...", "..."],
            "business_model_risks": ["...", "..."],
            "business_model_strength": "STRONG/MODERATE/WEAK",
            "revenue_model": "SUBSCRIPTION/TRANSACTIONAL/HYBRID/OTHER"
        }}
        """
        
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": "You are an expert equity analyst specializing in business model analysis. Provide concise, data-driven insights."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.3,
                max_tokens=1000
            )
            
            result = response.choices[0].message.content.strip()
            
            # Try to parse as JSON
            try:
                return json.loads(result)
            except json.JSONDecodeError:
                # Fallback: extract key information manually
                return {
                    "business_model_summary": result[:200] + "..." if len(result) > 200 else result,
                    "analysis_raw": result,
                    "parsing_error": True
                }
                
        except Exception as e:
            return {
                "error": f"GPT-4o analysis failed: {str(e)}",
                "business_model_summary": "Analysis unavailable due to API error"
            }
    
    def analyze_competitive_advantages(self, company_data: Dict[str, Any]) -> Dict[str, Any]:
        """Analyze competitive advantages and moat using GPT-4o."""
        
        symbol = company_data.get("symbol", "Unknown")
        company_info = company_data.get("company_info", {})
        financial_metrics = company_data.get("financial_metrics", {})
        
        prompt = f"""
        As an expert equity analyst, analyze the competitive advantages and economic moat of {symbol}.
        
        Company: {symbol} ({company_info.get('name', symbol)})
        Sector: {company_info.get('sector', 'Unknown')}
        Industry: {company_info.get('industry', 'Unknown')}
        
        Financial Metrics:
        - ROE: {financial_metrics.get('roe', 0)*100:.1f}%
        - ROIC: {financial_metrics.get('roic', 0)*100:.1f}%
        - Gross Margin: {financial_metrics.get('gross_margin', 0)*100:.1f}%
        - Net Margin: {financial_metrics.get('net_margin', 0)*100:.1f}%
        - Revenue Growth: {financial_metrics.get('revenue_growth_1y', 0)*100:.1f}%
        - Debt/Equity: {financial_metrics.get('debt_to_equity', 0):.2f}
        
        Analyze the company's competitive advantages and identify:
        1. Brand moat indicators
        2. Scale advantage indicators  
        3. Network effect indicators
        4. Switching cost indicators
        5. Cost advantage indicators
        6. Distribution advantage indicators
        7. Regulatory/license advantages
        8. Patent/IP advantages
        9. Data/ecosystem advantages
        10. Overall moat strength
        
        Rate each advantage on a scale of 0-5 (0=none, 5=very strong) and provide reasoning.
        
        Format as JSON:
        {{
            "brand_moat_score": 0,
            "brand_moat_indicators": ["...", "..."],
            "scale_advantage_score": 0,
            "scale_advantage_indicators": ["...", "..."],
            "network_effect_score": 0,
            "network_effect_indicators": ["...", "..."],
            "switching_cost_score": 0,
            "switching_cost_indicators": ["...", "..."],
            "cost_advantage_score": 0,
            "cost_advantage_indicators": ["...", "..."],
            "distribution_advantage_score": 0,
            "distribution_advantage_indicators": ["...", "..."],
            "regulatory_advantage_score": 0,
            "regulatory_advantage_indicators": ["...", "..."],
            "patent_ip_score": 0,
            "patent_ip_indicators": ["...", "..."],
            "data_ecosystem_score": 0,
            "data_ecosystem_indicators": ["...", "..."],
            "overall_moat_strength": "NONE/WEAK/MODERATE/STRONG/WIDE",
            "moat_durability": "LOW/MEDIUM/HIGH",
            "primary_moat_type": "BRAND/SCALE/NETWORK/SWITCHING_COST/COST/DISTRIBUTION/REGULATORY/PATENT"
        }}
        """
        
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": "You are an expert equity analyst specializing in competitive advantage analysis. Be objective and evidence-based."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.2,
                max_tokens=1200
            )
            
            result = response.choices[0].message.content.strip()
            
            try:
                return json.loads(result)
            except json.JSONDecodeError:
                return {
                    "analysis_raw": result,
                    "parsing_error": True,
                    "overall_moat_strength": "UNKNOWN"
                }
                
        except Exception as e:
            return {
                "error": f"GPT-4o moat analysis failed: {str(e)}",
                "overall_moat_strength": "UNKNOWN"
            }
    
    def analyze_management_quality(self, company_data: Dict[str, Any]) -> Dict[str, Any]:
        """Analyze management quality and capital allocation using GPT-4o."""
        
        symbol = company_data.get("symbol", "Unknown")
        company_info = company_data.get("company_info", {})
        financial_metrics = company_data.get("financial_metrics", {})
        
        prompt = f"""
        As an expert equity analyst, assess the management quality of {symbol} based on financial patterns.
        
        Company: {symbol} ({company_info.get('name', symbol)})
        
        Financial Quality Indicators:
        - ROE: {financial_metrics.get('roe', 0)*100:.1f}%
        - ROIC: {financial_metrics.get('roic', 0)*100:.1f}%
        - FCF Conversion: {financial_metrics.get('fcf_conversion', 0)*100:.1f}%
        - Debt/Equity: {financial_metrics.get('debt_to_equity', 0):.2f}
        - Interest Coverage: {financial_metrics.get('interest_coverage', 0):.1f}x
        - Piotroski Score: {financial_metrics.get('piotroski_score', 0)}/9
        - Altman Z-Score: {financial_metrics.get('altman_z_score', 0):.2f}
        - Red Flags: {financial_metrics.get('red_flag_count', 0)}
        
        Assess management quality based on:
        1. Capital allocation efficiency
        2. Financial discipline
        3. Shareholder friendliness
        4. Operational excellence
        5. Risk management
        6. Growth quality
        
        Format as JSON:
        {{
            "capital_allocation_score": 0,
            "capital_allocation_quality": "POOR/FAIR/GOOD/EXCELLENT",
            "financial_discipline_score": 0,
            "financial_discipline_indicators": ["...", "..."],
            "shareholder_friendliness_score": 0,
            "shareholder_policies": ["...", "..."],
            "operational_excellence_score": 0,
            "operational_indicators": ["...", "..."],
            "risk_management_score": 0,
            "risk_management_indicators": ["...", "..."],
            "growth_quality_score": 0,
            "growth_quality_indicators": ["...", "..."],
            "overall_management_quality": "POOR/FAIR/GOOD/EXCELLENT",
            "management_strengths": ["...", "..."],
            "management_concerns": ["...", "..."],
            "capital_allocation_track_record": "POOR/FAIR/GOOD/EXCELLENT"
        }}
        """
        
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": "You are an expert equity analyst specializing in management assessment. Be objective and evidence-based."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.2,
                max_tokens=1000
            )
            
            result = response.choices[0].message.content.strip()
            
            try:
                return json.loads(result)
            except json.JSONDecodeError:
                return {
                    "analysis_raw": result,
                    "parsing_error": True,
                    "overall_management_quality": "UNKNOWN"
                }
                
        except Exception as e:
            return {
                "error": f"GPT-4o management analysis failed: {str(e)}",
                "overall_management_quality": "UNKNOWN"
            }
    
    def generate_investment_thesis(self, company_data: Dict[str, Any], qualitative_analysis: Dict[str, Any]) -> Dict[str, Any]:
        """Generate comprehensive investment thesis using GPT-4o."""
        
        symbol = company_data.get("symbol", "Unknown")
        company_info = company_data.get("company_info", {})
        financial_metrics = company_data.get("financial_metrics", {})
        investment_scores = company_data.get("investment_scores", {})
        
        prompt = f"""
        As a senior equity analyst, generate a comprehensive investment thesis for {symbol}.
        
        Company: {symbol} ({company_info.get('name', symbol)})
        Sector: {company_info.get('sector', 'Unknown')}
        
        Quantitative Analysis:
        - Overall Score: {investment_scores.get('overall_score', 0)}/20 ({investment_scores.get('investment_category', 'UNKNOWN')})
        - Value Score: {investment_scores.get('value_score', 0)}/5
        - Quality Score: {investment_scores.get('quality_score', 0)}/5
        - Growth Score: {investment_scores.get('growth_score', 0)}/5
        - Safety Score: {investment_scores.get('safety_score', 0)}/5
        - P/E Ratio: {financial_metrics.get('pe_ratio', 0):.1f}
        - ROE: {financial_metrics.get('roe', 0)*100:.1f}%
        - Revenue Growth: {financial_metrics.get('revenue_growth_1y', 0)*100:.1f}%
        
        Qualitative Analysis:
        - Business Model Strength: {qualitative_analysis.get('business_model', {}).get('business_model_strength', 'UNKNOWN')}
        - Moat Strength: {qualitative_analysis.get('competitive_advantages', {}).get('overall_moat_strength', 'UNKNOWN')}
        - Management Quality: {qualitative_analysis.get('management_quality', {}).get('overall_management_quality', 'UNKNOWN')}
        
        Generate a comprehensive investment thesis including:
        1. Investment thesis summary (3-4 sentences)
        2. Bull case (3 key points)
        3. Bear case (3 key points)
        4. Key catalysts
        5. Primary risks
        6. Investment time horizon
        7. Price targets (base, upside, downside scenarios)
        8. Investment recommendation (BUY/HOLD/SELL)
        
        Format as JSON:
        {{
            "investment_thesis": "...",
            "bull_case": ["...", "...", "..."],
            "bear_case": ["...", "...", "..."],
            "key_catalysts": ["...", "...", "..."],
            "primary_risks": ["...", "...", "..."],
            "investment_time_horizon": "SHORT/MEDIUM/LONG",
            "price_target_base": 0.0,
            "price_target_upside": 0.0,
            "price_target_downside": 0.0,
            "upside_potential_pct": 0.0,
            "downside_risk_pct": 0.0,
            "investment_recommendation": "BUY/HOLD/SELL",
            "conviction_level": "LOW/MEDIUM/HIGH",
            "thesis_strength": "WEAK/MODERATE/STRONG"
        }}
        """
        
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": "You are a senior equity analyst. Provide balanced, well-reasoned investment theses with clear risk/reward analysis."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.3,
                max_tokens=1200
            )
            
            result = response.choices[0].message.content.strip()
            
            try:
                return json.loads(result)
            except json.JSONDecodeError:
                return {
                    "thesis_raw": result,
                    "parsing_error": True,
                    "investment_recommendation": "UNKNOWN"
                }
                
        except Exception as e:
            return {
                "error": f"GPT-4o thesis generation failed: {str(e)}",
                "investment_recommendation": "UNKNOWN"
            }
    
    def comprehensive_analysis(self, company_data: Dict[str, Any]) -> Dict[str, Any]:
        """Perform complete qualitative analysis using GPT-4o."""
        
        symbol = company_data.get("symbol", "Unknown")
        
        print(f"🤖 Starting GPT-4o qualitative analysis for {symbol}...")
        
        analysis = {
            "symbol": symbol,
            "analysis_timestamp": datetime.now().isoformat(),
            "gpt4o_analysis": {}
        }
        
        # Step 1: Business Model Analysis
        print(f"  📊 Analyzing business model...")
        business_model = self.analyze_business_model(company_data)
        analysis["gpt4o_analysis"]["business_model"] = business_model
        
        # Step 2: Competitive Advantages
        print(f"  🏰 Analyzing competitive advantages...")
        competitive_advantages = self.analyze_competitive_advantages(company_data)
        analysis["gpt4o_analysis"]["competitive_advantages"] = competitive_advantages
        
        # Step 3: Management Quality
        print(f"  👥 Analyzing management quality...")
        management_quality = self.analyze_management_quality(company_data)
        analysis["gpt4o_analysis"]["management_quality"] = management_quality
        
        # Step 4: Investment Thesis
        print(f"  📋 Generating investment thesis...")
        investment_thesis = self.generate_investment_thesis(company_data, analysis["gpt4o_analysis"])
        analysis["gpt4o_analysis"]["investment_thesis"] = investment_thesis
        
        # Calculate qualitative scores
        analysis["qualitative_scores"] = self._calculate_qualitative_scores(analysis["gpt4o_analysis"])
        
        print(f"  ✅ GPT-4o analysis complete for {symbol}")
        
        return analysis
    
    def _calculate_qualitative_scores(self, gpt4o_analysis: Dict[str, Any]) -> Dict[str, Any]:
        """Calculate qualitative scores from GPT-4o analysis."""
        
        scores = {
            "business_model_score": 0,
            "moat_score": 0,
            "management_score": 0,
            "thesis_strength_score": 0,
            "overall_qualitative_score": 0
        }
        
        # Business model score
        business_model = gpt4o_analysis.get("business_model", {})
        if business_model.get("business_model_strength") == "STRONG":
            scores["business_model_score"] = 5
        elif business_model.get("business_model_strength") == "MODERATE":
            scores["business_model_score"] = 3
        elif business_model.get("business_model_strength") == "WEAK":
            scores["business_model_score"] = 1
        
        # Moat score
        moat = gpt4o_analysis.get("competitive_advantages", {})
        moat_strength = moat.get("overall_moat_strength", "NONE")
        moat_scores = {"NONE": 0, "WEAK": 1, "MODERATE": 3, "STRONG": 4, "WIDE": 5}
        scores["moat_score"] = moat_scores.get(moat_strength, 0)
        
        # Management score
        management = gpt4o_analysis.get("management_quality", {})
        mgmt_quality = management.get("overall_management_quality", "POOR")
        mgmt_scores = {"POOR": 1, "FAIR": 2, "GOOD": 4, "EXCELLENT": 5}
        scores["management_score"] = mgmt_scores.get(mgmt_quality, 0)
        
        # Thesis strength score
        thesis = gpt4o_analysis.get("investment_thesis", {})
        thesis_strength = thesis.get("thesis_strength", "WEAK")
        thesis_scores = {"WEAK": 1, "MODERATE": 3, "STRONG": 5}
        scores["thesis_strength_score"] = thesis_scores.get(thesis_strength, 0)
        
        # Overall qualitative score
        scores["overall_qualitative_score"] = (
            scores["business_model_score"] + 
            scores["moat_score"] + 
            scores["management_score"] + 
            scores["thesis_strength_score"]
        ) / 4
        
        return scores

def test_gpt4o_analyzer():
    """Test the GPT-4o analyzer with sample data."""
    
    try:
        analyzer = GPT4oQualitativeAnalyzer()
        
        # Sample company data
        sample_company = {
            "symbol": "AAPL",
            "company_info": {
                "name": "Apple Inc.",
                "sector": "Technology",
                "industry": "Consumer Electronics",
                "description": "Apple Inc. designs, manufactures, and markets smartphones, personal computers, tablets, wearables, and accessories worldwide."
            },
            "financial_metrics": {
                "revenue": 383285000000,
                "gross_margin": 0.452,
                "operating_margin": 0.301,
                "roe": 0.369,
                "roic": 0.226,
                "revenue_growth_1y": 0.028,
                "debt_to_equity": 1.73,
                "fcf_conversion": 0.89,
                "piotroski_score": 7,
                "altman_z_score": 6.8,
                "red_flag_count": 0
            },
            "investment_scores": {
                "overall_score": 16,
                "investment_category": "EXCELLENT",
                "value_score": 3,
                "quality_score": 4,
                "growth_score": 3,
                "safety_score": 6
            }
        }
        
        # Run analysis
        result = analyzer.comprehensive_analysis(sample_company)
        
        print("🎉 GPT-4o Analysis Test Successful!")
        print(f"Symbol: {result['symbol']}")
        print(f"Business Model Score: {result['qualitative_scores']['business_model_score']}/5")
        print(f"Moat Score: {result['qualitative_scores']['moat_score']}/5")
        print(f"Management Score: {result['qualitative_scores']['management_score']}/5")
        print(f"Overall Qualitative Score: {result['qualitative_scores']['overall_qualitative_score']:.1f}/5")
        
        return result
        
    except Exception as e:
        print(f"❌ GPT-4o test failed: {e}")
        return None

if __name__ == "__main__":
    test_gpt4o_analyzer()
