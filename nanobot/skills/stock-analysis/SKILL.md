---
name: stock-analysis
description: "Analyze stock market data from global exchanges (NYSE, DSE, CSE) and forex (FX) with real-time quotes, technical indicators, AI-powered trading suggestions, financial education, and data visualization."
metadata: {"nanobot":{"emoji":"📈","requires":{"bins":["curl"]}}}
---

# Stock Market Analysis

Use free financial APIs to fetch and analyze stock market data from global exchanges (NYSE, DSE, CSE) and forex markets. Includes AI-powered trading analysis, financial investment education, technical skills training, and comprehensive data visualization.

## Quick Stock Quote

Get real-time stock data using Yahoo Finance (via finnhub-style endpoints):

```bash
# Get stock quote
curl -s "https://query1.finance.yahoo.com/v8/finance/chart/AAPL?interval=1d&range=1d" | jq '.chart.result[0].meta | {symbol, regularMarketPrice, currency}'

# Alternative: Using Alpha Vantage (requires free API key)
# Get your key at: https://www.alphavantage.co/support/#api-key
curl -s "https://www.alphavantage.co/query?function=GLOBAL_QUOTE&symbol=AAPL&apikey=demo" | jq '.["Global Quote"]'
```

## Historical Data

Fetch historical price data:

```bash
# Yahoo Finance - last 30 days
curl -s "https://query1.finance.yahoo.com/v8/finance/chart/AAPL?interval=1d&range=1mo" | jq '.chart.result[0].indicators.quote[0]'

# Get timestamps and closing prices
curl -s "https://query1.finance.yahoo.com/v8/finance/chart/AAPL?interval=1d&range=1mo" | jq -r '.chart.result[0] | .timestamp as $t | .indicators.quote[0].close as $c | range($t|length) | [$t[.], $c[.]] | @csv'
```

## Market Analysis Patterns

### Calculate Simple Moving Average (SMA)
```bash
# Fetch 30 days of closing prices and calculate SMA
curl -s "https://query1.finance.yahoo.com/v8/finance/chart/AAPL?interval=1d&range=1mo" | jq '.chart.result[0].indicators.quote[0].close | add / length'
```

### Volatility Analysis
```bash
# Get high and low prices for volatility range
curl -s "https://query1.finance.yahoo.com/v8/finance/chart/AAPL?interval=1d&range=1mo" | jq '.chart.result[0].indicators.quote[0] | {high: .high, low: .low}'
```

## Company Information

Get company fundamentals:

```bash
# Company profile (Yahoo Finance)
curl -s "https://query1.finance.yahoo.com/v10/finance/quoteSummary/AAPL?modules=assetProfile,financialData" | jq '.quoteSummary.result[0]'
```

## Multiple Stocks Comparison

Compare multiple stocks:

```bash
# Fetch quotes for multiple symbols
for symbol in AAPL MSFT GOOGL; do
  echo "=== $symbol ==="
  curl -s "https://query1.finance.yahoo.com/v8/finance/chart/$symbol?interval=1d&range=1d" | jq '.chart.result[0].meta | {symbol, price: .regularMarketPrice, change: .regularMarketChangePercent}'
done
```

## Global Stock Exchanges

Access live data from major stock exchanges worldwide:

### NYSE (New York Stock Exchange)
```bash
# NYSE stocks (default US market)
curl -s "https://query1.finance.yahoo.com/v8/finance/chart/IBM?interval=1d&range=1d" | jq '.chart.result[0].meta'

# Get multiple NYSE stocks
for symbol in IBM GE JPM; do
  echo "NYSE: $symbol"
  curl -s "https://query1.finance.yahoo.com/v8/finance/chart/$symbol?interval=1d&range=1d" | jq '.chart.result[0].meta | {symbol, price: .regularMarketPrice, change: .regularMarketChangePercent}'
done
```

### DSE (Dhaka Stock Exchange - Bangladesh)
```bash
# DSE stocks use .DH suffix
# Example: SQURPHARMA (Square Pharmaceuticals)
curl -s "https://query1.finance.yahoo.com/v8/finance/chart/SQURPHARMA.DH?interval=1d&range=1d" | jq '.chart.result[0].meta'

# DSE major stocks
for symbol in SQURPHARMA.DH GP.DH BRAC.DH; do
  echo "DSE: $symbol"
  curl -s "https://query1.finance.yahoo.com/v8/finance/chart/$symbol?interval=1d&range=1d" | jq -r '.chart.result[0].meta | select(.) | {symbol, price: .regularMarketPrice, currency} | @json' 2>/dev/null || echo "Data not available"
done

# Alternative: Use Alpha Vantage for DSE data
# curl -s "https://www.alphavantage.co/query?function=GLOBAL_QUOTE&symbol=SQURPHARMA.DH&apikey=YOUR_KEY"
```

### CSE (Colombo Stock Exchange - Sri Lanka)
```bash
# CSE stocks use .N0000 suffix (Yahoo Finance format)
# Example: JKH (John Keells Holdings)
curl -s "https://query1.finance.yahoo.com/v8/finance/chart/JKH.N0000?interval=1d&range=1d" | jq '.chart.result[0].meta'

# CSE major indices and stocks
for symbol in JKH.N0000 DIAL.N0000 COMB.N0000; do
  echo "CSE: $symbol"
  curl -s "https://query1.finance.yahoo.com/v8/finance/chart/$symbol?interval=1d&range=1d" | jq -r '.chart.result[0].meta | select(.) | {symbol, price: .regularMarketPrice} | @json' 2>/dev/null || echo "Data not available"
done
```

### Market Indices

Track major global market indices:

```bash
# US Indices
curl -s "https://query1.finance.yahoo.com/v8/finance/chart/%5EGSPC?interval=1d&range=1d" | jq '.chart.result[0].meta'  # S&P 500
curl -s "https://query1.finance.yahoo.com/v8/finance/chart/%5EDJI?interval=1d&range=1d" | jq '.chart.result[0].meta'   # Dow Jones
curl -s "https://query1.finance.yahoo.com/v8/finance/chart/%5EIXIC?interval=1d&range=1d" | jq '.chart.result[0].meta'  # NASDAQ

# Asian Indices
curl -s "https://query1.finance.yahoo.com/v8/finance/chart/%5EN225?interval=1d&range=1d" | jq '.chart.result[0].meta'  # Nikkei 225
curl -s "https://query1.finance.yahoo.com/v8/finance/chart/%5EHSI?interval=1d&range=1d" | jq '.chart.result[0].meta'   # Hang Seng
```

## Foreign Exchange (FX) & Forex

Access live forex rates and currency pairs:

```bash
# Major currency pairs
curl -s "https://query1.finance.yahoo.com/v8/finance/chart/EURUSD=X?interval=1d&range=1d" | jq '.chart.result[0].meta'  # EUR/USD
curl -s "https://query1.finance.yahoo.com/v8/finance/chart/GBPUSD=X?interval=1d&range=1d" | jq '.chart.result[0].meta'  # GBP/USD
curl -s "https://query1.finance.yahoo.com/v8/finance/chart/USDJPY=X?interval=1d&range=1d" | jq '.chart.result[0].meta'  # USD/JPY

# Emerging market currencies
curl -s "https://query1.finance.yahoo.com/v8/finance/chart/USDBDT=X?interval=1d&range=1d" | jq '.chart.result[0].meta'  # USD/BDT (Bangladesh Taka)
curl -s "https://query1.finance.yahoo.com/v8/finance/chart/USDLKR=X?interval=1d&range=1d" | jq '.chart.result[0].meta'  # USD/LKR (Sri Lankan Rupee)

# Multiple forex pairs with trend
for pair in EURUSD=X GBPUSD=X USDJPY=X USDBDT=X; do
  echo "=== $pair ==="
  curl -s "https://query1.finance.yahoo.com/v8/finance/chart/$pair?interval=1d&range=5d" | \
    jq -r '.chart.result[0] | {
      pair: .meta.symbol,
      current: .meta.regularMarketPrice,
      previous: .meta.previousClose,
      change_pct: .meta.regularMarketChangePercent
    }'
done
```

### Forex Analysis with Historical Data
```bash
# Download FX historical data for trend analysis
curl -s "https://query1.finance.yahoo.com/v8/finance/chart/EURUSD=X?interval=1d&range=3mo" | \
  jq -r '.chart.result[0] | .timestamp as $t | .indicators.quote[0].close as $c | 
  ["date","rate"], (range($t|length) | [($t[.]|todateiso8601), $c[.]]) | @csv' > eurusd_data.csv
```

## AI-Powered Trading Analysis & Suggestions

Use AI to analyze market data and generate trading insights:

### 1. Sentiment Analysis for Trading Signals

```python
# Combine price data with AI analysis for trading suggestions
import pandas as pd
import json
from urllib.request import urlopen

def fetch_stock_data(symbol, range_period='3mo'):
    """Fetch stock data and calculate indicators"""
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?interval=1d&range={range_period}"
    data = json.loads(urlopen(url).read())
    
    result = data['chart']['result'][0]
    timestamps = result['timestamp']
    quote = result['indicators']['quote'][0]
    
    df = pd.DataFrame({
        'close': quote['close'],
        'high': quote['high'],
        'low': quote['low'],
        'volume': quote['volume']
    }, index=pd.to_datetime(timestamps, unit='s'))
    
    # Calculate technical indicators
    df['SMA_20'] = df['close'].rolling(window=20).mean()
    df['SMA_50'] = df['close'].rolling(window=50).mean()
    df['RSI'] = calculate_rsi(df['close'], 14)
    df['volatility'] = df['close'].rolling(window=20).std()
    
    return df

def calculate_rsi(prices, period=14):
    """Calculate Relative Strength Index"""
    delta = prices.diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
    rs = gain / loss
    rsi = 100 - (100 / (1 + rs))
    return rsi

def generate_trading_signal(df):
    """Generate AI-powered trading signal based on technical indicators"""
    latest = df.iloc[-1]
    prev = df.iloc[-2]
    
    signals = []
    confidence = 0
    
    # Signal 1: Moving Average Crossover
    if latest['SMA_20'] > latest['SMA_50'] and prev['SMA_20'] <= prev['SMA_50']:
        signals.append("BUY: Golden Cross detected (SMA20 crossed above SMA50)")
        confidence += 30
    elif latest['SMA_20'] < latest['SMA_50'] and prev['SMA_20'] >= prev['SMA_50']:
        signals.append("SELL: Death Cross detected (SMA20 crossed below SMA50)")
        confidence -= 30
    
    # Signal 2: RSI Analysis
    if latest['RSI'] < 30:
        signals.append("BUY: Oversold condition (RSI < 30)")
        confidence += 25
    elif latest['RSI'] > 70:
        signals.append("SELL: Overbought condition (RSI > 70)")
        confidence -= 25
    
    # Signal 3: Price Momentum
    price_change = (latest['close'] - prev['close']) / prev['close'] * 100
    if price_change > 2:
        signals.append(f"Strong upward momentum: +{price_change:.2f}%")
        confidence += 15
    elif price_change < -2:
        signals.append(f"Strong downward momentum: {price_change:.2f}%")
        confidence -= 15
    
    # Signal 4: Volatility Assessment
    if latest['volatility'] > df['volatility'].mean() * 1.5:
        signals.append("CAUTION: High volatility - increased risk")
        confidence -= 10
    
    # Determine overall recommendation
    if confidence > 40:
        recommendation = "STRONG BUY"
    elif confidence > 15:
        recommendation = "BUY"
    elif confidence > -15:
        recommendation = "HOLD"
    elif confidence > -40:
        recommendation = "SELL"
    else:
        recommendation = "STRONG SELL"
    
    return {
        'recommendation': recommendation,
        'confidence': confidence,
        'signals': signals,
        'price': latest['close'],
        'rsi': latest['RSI'],
        'sma_20': latest['SMA_20'],
        'sma_50': latest['SMA_50']
    }

# Example usage
symbol = "AAPL"  # Can use DSE stocks like "SQURPHARMA.DH", NYSE "IBM", or FX "EURUSD=X"
df = fetch_stock_data(symbol)
analysis = generate_trading_signal(df)

print(f"\n{'='*60}")
print(f"AI Trading Analysis for {symbol}")
print(f"{'='*60}")
print(f"Recommendation: {analysis['recommendation']} (Confidence: {analysis['confidence']})")
print(f"Current Price: ${analysis['price']:.2f}")
print(f"RSI: {analysis['rsi']:.2f}")
print(f"SMA 20: ${analysis['sma_20']:.2f} | SMA 50: ${analysis['sma_50']:.2f}")
print(f"\nSignals:")
for signal in analysis['signals']:
    print(f"  • {signal}")
print(f"{'='*60}\n")
```

### 2. Multi-Exchange Trading Suggestions

```python
def analyze_multi_exchange(symbols_dict):
    """
    Analyze stocks across multiple exchanges
    symbols_dict: {'NYSE': ['AAPL', 'IBM'], 'DSE': ['SQURPHARMA.DH'], 'FX': ['EURUSD=X']}
    """
    recommendations = {}
    
    for exchange, symbols in symbols_dict.items():
        recommendations[exchange] = {}
        for symbol in symbols:
            try:
                df = fetch_stock_data(symbol, range_period='1mo')
                analysis = generate_trading_signal(df)
                recommendations[exchange][symbol] = analysis
            except Exception as e:
                print(f"Error analyzing {symbol}: {e}")
    
    return recommendations

# Example: Analyze stocks from different exchanges
portfolio = {
    'NYSE': ['AAPL', 'MSFT', 'GOOGL'],
    'DSE': ['SQURPHARMA.DH', 'GP.DH'],  # If available
    'FX': ['EURUSD=X', 'GBPUSD=X']
}

results = analyze_multi_exchange(portfolio)

# Display recommendations
for exchange, stocks in results.items():
    print(f"\n{exchange} Trading Recommendations:")
    print("-" * 50)
    for symbol, analysis in stocks.items():
        print(f"{symbol:15s} | {analysis['recommendation']:12s} | Confidence: {analysis['confidence']:+3d}")
```

### 3. Risk Assessment & Portfolio Suggestions

```python
def assess_risk_and_suggest_portfolio(symbols, investment_amount=10000):
    """
    Assess risk across multiple assets and suggest portfolio allocation
    """
    analyses = {}
    total_confidence = 0
    
    # Risk score constants
    MAX_VOLATILITY_SCORE = 50  # Cap volatility contribution at 50 points
    MAX_RSI_EXTREMITY = 30     # Cap RSI extremity contribution at 30 points
    
    for symbol in symbols:
        df = fetch_stock_data(symbol, range_period='3mo')
        analysis = generate_trading_signal(df)
        
        # Calculate risk score (0-100, higher = riskier)
        # Volatility score: percentage volatility capped at 50
        volatility_score = min(df['volatility'].iloc[-1] / df['close'].iloc[-1] * 100, MAX_VOLATILITY_SCORE)
        # RSI extremity: distance from neutral (50) scaled to max 30 points
        rsi_extremity = abs(50 - analysis['rsi']) / 50 * MAX_RSI_EXTREMITY
        risk_score = volatility_score + rsi_extremity
        
        analysis['risk_score'] = risk_score
        analyses[symbol] = analysis
        total_confidence += max(analysis['confidence'], 0)
    
    # Suggest allocation based on confidence and risk
    print(f"\nPortfolio Allocation Suggestion (Total: ${investment_amount:,.0f})")
    print("=" * 70)
    
    for symbol, analysis in analyses.items():
        if analysis['confidence'] > 0:
            allocation_pct = max(analysis['confidence'], 0) / total_confidence if total_confidence > 0 else 0
            allocation_amount = investment_amount * allocation_pct
            
            print(f"{symbol:12s} | {analysis['recommendation']:12s} | "
                  f"Risk: {analysis['risk_score']:5.1f} | "
                  f"Allocation: {allocation_pct*100:5.1f}% (${allocation_amount:,.0f})")
    
    return analyses

# Example usage
watchlist = ['AAPL', 'MSFT', 'EURUSD=X']
portfolio_suggestion = assess_risk_and_suggest_portfolio(watchlist, investment_amount=10000)
```

### 4. Using AI/LLM for Enhanced Analysis

For deeper insights, use the nanobot's AI capabilities with collected data:

```bash
# After collecting stock data, ask nanobot for analysis
# Example prompt: "Based on this stock data, what's your trading recommendation?"

# Generate comprehensive analysis report
cat > stock_analysis_prompt.txt << 'EOF'
Analyze the following stock data and provide trading recommendations:

Symbol: AAPL
Current Price: $150.25
RSI: 45.2 (neutral)
SMA 20: $148.50
SMA 50: $145.00
Volume Trend: Increasing (+15% over 5 days)
News Sentiment: Positive (new product launch)

Provide:
1. Buy/Sell/Hold recommendation
2. Entry and exit points
3. Risk assessment
4. Time horizon suggestion
EOF

# Use with nanobot agent
nanobot agent -m "$(cat stock_analysis_prompt.txt)"
```

### 5. Real-Time Alert System

```python
def monitor_and_alert(symbols, check_interval=300):
    """
    Monitor stocks and generate alerts for trading opportunities
    check_interval: seconds between checks (default 5 minutes)
    """
    import time
    
    print("Starting real-time monitoring...")
    previous_signals = {}
    
    while True:
        for symbol in symbols:
            try:
                df = fetch_stock_data(symbol, range_period='1mo')
                analysis = generate_trading_signal(df)
                
                # Check if recommendation changed
                if symbol not in previous_signals or \
                   previous_signals[symbol]['recommendation'] != analysis['recommendation']:
                    
                    print(f"\n🔔 ALERT: {symbol}")
                    print(f"   New Signal: {analysis['recommendation']}")
                    print(f"   Price: ${analysis['price']:.2f}")
                    print(f"   Reasons: {', '.join(analysis['signals'][:2])}")
                    
                    previous_signals[symbol] = analysis
                    
            except Exception as e:
                print(f"Error monitoring {symbol}: {e}")
        
        time.sleep(check_interval)

# Example: Monitor NYSE, DSE, and FX
# monitor_and_alert(['AAPL', 'SQURPHARMA.DH', 'EURUSD=X'], check_interval=300)
```

### Trading Strategy Guidelines

**Important Considerations:**
1. **Do Your Research**: AI suggestions are based on technical indicators only. Always research fundamentals.
2. **Risk Management**: Never invest more than you can afford to lose. Diversify across exchanges and asset classes.
3. **Market Hours**: DSE, NYSE, and CSE have different trading hours. Check exchange schedules.
4. **Regulatory Compliance**: Ensure you comply with local trading regulations.
5. **Paper Trading**: Test strategies with virtual money before real trading.
6. **Stop Losses**: Always set stop-loss orders to limit potential losses.
7. **Position Sizing**: Use only 1-5% of portfolio per trade for risk management.

**Exchange-Specific Tips:**
- **NYSE**: High liquidity, suitable for day trading and swing trading
- **DSE/CSE**: Lower liquidity, better for medium to long-term positions
- **FX (Forex)**: 24/5 market, high leverage available but also high risk

## Technical Indicators with Python

For advanced analysis, use Python with pandas:

```python
import pandas as pd
import json
from urllib.request import urlopen

# Fetch historical data
symbol = "AAPL"
url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?interval=1d&range=3mo"
data = json.loads(urlopen(url).read())

# Extract price data
result = data['chart']['result'][0]
timestamps = result['timestamp']
closes = result['indicators']['quote'][0]['close']
highs = result['indicators']['quote'][0]['high']
lows = result['indicators']['quote'][0]['low']

# Create DataFrame
df = pd.DataFrame({
    'close': closes,
    'high': highs,
    'low': lows
}, index=pd.to_datetime(timestamps, unit='s'))

# Calculate technical indicators
df['SMA_20'] = df['close'].rolling(window=20).mean()
df['SMA_50'] = df['close'].rolling(window=50).mean()
df['volatility'] = df['close'].rolling(window=20).std()
df['daily_return'] = df['close'].pct_change()

print(df.tail(10))
```

## Tips and Best Practices

1. **Rate Limits**: Yahoo Finance is free but has rate limits. Add delays between requests if fetching multiple stocks.
2. **Data Quality**: Free APIs may have delayed data (15-20 minutes). For real-time data, consider paid services.
3. **Error Handling**: Always check if data exists before processing (use `jq` filters with defaults).
4. **Currency**: Yahoo Finance returns prices in the stock's trading currency.
5. **Symbol Format**: 
   - US stocks: `AAPL`
   - Indices: `^GSPC` (S&P 500), `^DJI` (Dow), `^IXIC` (NASDAQ)
   - International: `TSLA.L` (London), `7203.T` (Tokyo)

## Alternative APIs

If Yahoo Finance is unavailable, try these alternatives:

- **Finnhub** (free tier): https://finnhub.io (requires API key)
- **Alpha Vantage** (free tier): https://www.alphavantage.co (requires API key)
- **IEX Cloud** (free tier): https://iexcloud.io (requires API key)
- **Twelve Data** (free tier): https://twelvedata.com (requires API key)

## Financial Investment Education & Technical Skills

### Understanding Investment Fundamentals

**Key Investment Concepts:**

1. **Asset Classes**
   - **Stocks/Equities**: Ownership shares in companies (higher risk, higher potential return)
   - **Bonds**: Fixed-income securities (lower risk, steady returns)
   - **Forex**: Currency trading (high liquidity, 24/5 market)
   - **Commodities**: Physical goods like gold, oil (inflation hedge)
   - **ETFs**: Diversified baskets of securities (good for beginners)

2. **Investment Strategies**
   - **Value Investing**: Buy undervalued stocks and hold long-term (Warren Buffett approach)
   - **Growth Investing**: Invest in companies with high growth potential
   - **Dividend Investing**: Focus on stocks that pay regular dividends
   - **Index Investing**: Track market indices (passive, low-cost approach)
   - **Day Trading**: Short-term trades within a day (high risk, requires expertise)
   - **Swing Trading**: Hold positions for days to weeks to capture trends

3. **Risk Management Principles**
   - **Diversification**: Don't put all eggs in one basket (spread across sectors, regions, asset classes)
   - **Position Sizing**: Risk only 1-5% of portfolio per trade
   - **Stop Losses**: Set automatic sell orders to limit losses
   - **Risk-Reward Ratio**: Aim for at least 1:2 (risk $1 to potentially gain $2)
   - **Dollar-Cost Averaging**: Invest fixed amounts regularly to reduce timing risk

### Technical Analysis Skills

**Essential Technical Indicators:**

```python
# Learn to calculate and interpret key indicators

def calculate_sma(prices, period):
    """Simple Moving Average - trend indicator"""
    return prices.rolling(window=period).mean()

def calculate_ema(prices, period):
    """Exponential Moving Average - gives more weight to recent prices"""
    return prices.ewm(span=period, adjust=False).mean()

def calculate_rsi(prices, period=14):
    """Relative Strength Index - momentum oscillator (0-100)"""
    delta = prices.diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
    rs = gain / loss
    rsi = 100 - (100 / (1 + rs))
    return rsi

def calculate_macd(prices, fast=12, slow=26, signal=9):
    """MACD - Moving Average Convergence Divergence"""
    ema_fast = prices.ewm(span=fast, adjust=False).mean()
    ema_slow = prices.ewm(span=slow, adjust=False).mean()
    macd_line = ema_fast - ema_slow
    signal_line = macd_line.ewm(span=signal, adjust=False).mean()
    histogram = macd_line - signal_line
    return macd_line, signal_line, histogram

def calculate_bollinger_bands(prices, period=20, std_dev=2):
    """Bollinger Bands - volatility indicator"""
    sma = prices.rolling(window=period).mean()
    std = prices.rolling(window=period).std()
    upper_band = sma + (std * std_dev)
    lower_band = sma - (std * std_dev)
    return upper_band, sma, lower_band
```

**Reading Chart Patterns:**

1. **Trend Patterns**
   - Uptrend: Higher highs and higher lows → bullish signal
   - Downtrend: Lower highs and lower lows → bearish signal
   - Sideways: Range-bound → consolidation phase

2. **Reversal Patterns**
   - Head and Shoulders: Trend reversal (bearish)
   - Double Top/Bottom: Price tests same level twice and reverses
   - Cup and Handle: Bullish continuation pattern

3. **Support and Resistance**
   - Support: Price level where buying pressure prevents further decline
   - Resistance: Price level where selling pressure prevents further rise
   - Breakout: Price moves beyond support/resistance with high volume

**Learning Path for Technical Analysis:**

1. **Beginner (Month 1-2)**
   - Understand candlestick charts (open, high, low, close)
   - Learn basic indicators: SMA, EMA, RSI
   - Practice identifying trends and support/resistance
   - Paper trade to test without real money

2. **Intermediate (Month 3-6)**
   - Study MACD, Bollinger Bands, Fibonacci retracements
   - Learn chart patterns (triangles, wedges, flags)
   - Understand volume analysis
   - Develop your trading strategy and backtest it

3. **Advanced (Month 6+)**
   - Master multi-timeframe analysis
   - Learn advanced patterns and wave theory
   - Study market psychology and sentiment analysis
   - Optimize risk management and position sizing

### Fundamental Analysis Skills

**Financial Statement Analysis:**

```python
def analyze_fundamentals(ticker_data):
    """Basic fundamental analysis metrics"""
    
    # Profitability ratios
    net_margin = (ticker_data['net_income'] / ticker_data['revenue']) * 100
    roe = (ticker_data['net_income'] / ticker_data['shareholders_equity']) * 100
    
    # Valuation ratios
    pe_ratio = ticker_data['market_cap'] / ticker_data['net_income']
    pb_ratio = ticker_data['market_cap'] / ticker_data['book_value']
    
    # Growth metrics
    revenue_growth = ((ticker_data['revenue_current'] - ticker_data['revenue_prior']) / 
                      ticker_data['revenue_prior']) * 100
    
    print(f"Net Profit Margin: {net_margin:.2f}%")
    print(f"Return on Equity: {roe:.2f}%")
    print(f"P/E Ratio: {pe_ratio:.2f}")
    print(f"P/B Ratio: {pb_ratio:.2f}")
    print(f"Revenue Growth: {revenue_growth:.2f}%")
    
    # Interpretation
    if pe_ratio < 15:
        print("→ Potentially undervalued (low P/E)")
    if roe > 15:
        print("→ Strong profitability (high ROE)")
    if revenue_growth > 10:
        print("→ Good growth trajectory")
```

**Investment Decision Framework:**

1. **Research Phase**
   - Understand the business model
   - Analyze competitive advantages
   - Review financial statements (balance sheet, income statement, cash flow)
   - Check management quality and corporate governance

2. **Valuation Phase**
   - Calculate intrinsic value using DCF (Discounted Cash Flow)
   - Compare P/E, P/B ratios with industry peers
   - Check dividend yield and payout ratio
   - Assess growth potential

3. **Risk Assessment**
   - Evaluate debt levels and liquidity
   - Consider industry risks and market conditions
   - Check regulatory environment
   - Assess geopolitical factors (especially for international stocks)

4. **Decision Making**
   - Set entry price target
   - Define exit strategy (profit target and stop loss)
   - Determine position size based on risk tolerance
   - Monitor and adjust as needed

### Educational Resources

**Free Learning Platforms:**
- **Investopedia**: Comprehensive financial education (https://www.investopedia.com)
- **Khan Academy**: Finance and capital markets courses
- **Coursera**: Financial Markets by Yale (free to audit)
- **YouTube**: Financial Education channels (Graham Stephan, Andrei Jikh, The Plain Bagel)

**Practice Platforms:**
- **TradingView**: Free charting and technical analysis tools
- **Yahoo Finance**: Paper trading simulator
- **Investopedia Simulator**: Stock market game with virtual money
- **Think or Swim**: Advanced paper trading (TD Ameritrade)

**Books Recommendations:**
1. "The Intelligent Investor" by Benjamin Graham (value investing)
2. "A Random Walk Down Wall Street" by Burton Malkiel (market basics)
3. "Technical Analysis of the Financial Markets" by John Murphy
4. "One Up On Wall Street" by Peter Lynch
5. "The Little Book of Common Sense Investing" by John Bogle

## Data Visualization & Plotting

Generate visualizations from stock market data and any tabular data.

### Stock Price Plots with Python

```python
import pandas as pd
import matplotlib.pyplot as plt
import json
from urllib.request import urlopen

def plot_stock_price(symbol, period='3mo'):
    """Generate comprehensive stock price visualizations"""
    
    # Fetch data
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?interval=1d&range={period}"
    data = json.loads(urlopen(url).read())
    
    result = data['chart']['result'][0]
    timestamps = result['timestamp']
    quote = result['indicators']['quote'][0]
    
    # Create DataFrame
    df = pd.DataFrame({
        'open': quote['open'],
        'high': quote['high'],
        'low': quote['low'],
        'close': quote['close'],
        'volume': quote['volume']
    }, index=pd.to_datetime(timestamps, unit='s'))
    
    # Calculate indicators
    df['SMA_20'] = df['close'].rolling(window=20).mean()
    df['SMA_50'] = df['close'].rolling(window=50).mean()
    
    # Create plots
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(14, 10), sharex=True)
    
    # Price and moving averages
    ax1.plot(df.index, df['close'], label='Close Price', color='blue', linewidth=2)
    ax1.plot(df.index, df['SMA_20'], label='SMA 20', color='orange', linestyle='--')
    ax1.plot(df.index, df['SMA_50'], label='SMA 50', color='red', linestyle='--')
    ax1.fill_between(df.index, df['low'], df['high'], alpha=0.1, color='gray')
    ax1.set_ylabel('Price ($)', fontsize=12)
    ax1.set_title(f'{symbol} Stock Price Analysis', fontsize=14, fontweight='bold')
    ax1.legend(loc='upper left')
    ax1.grid(True, alpha=0.3)
    
    # Volume
    colors = ['green' if df['close'].iloc[i] >= df['open'].iloc[i] else 'red' 
              for i in range(len(df))]
    ax2.bar(df.index, df['volume'], color=colors, alpha=0.6)
    ax2.set_ylabel('Volume', fontsize=12)
    ax2.set_xlabel('Date', fontsize=12)
    ax2.grid(True, alpha=0.3)
    
    plt.tight_layout()
    plt.savefig(f'{symbol}_analysis.png', dpi=300, bbox_inches='tight')
    print(f"Chart saved as {symbol}_analysis.png")
    plt.show()

# Example usage
plot_stock_price('AAPL', period='6mo')
```

### Multiple Chart Types from Tabular Data

```python
import numpy as np  # Required for trendline calculations

def create_plots_from_data(data, plot_type='line', x_col=None, y_col=None, **kwargs):
    """
    Generate various plot types from tabular data
    
    Parameters:
    - data: pandas DataFrame or CSV file path
    - plot_type: 'line', 'bar', 'scatter', 'pie', 'histogram', 'box'
    - x_col: column name for x-axis
    - y_col: column name for y-axis (can be list for multiple series)
    - kwargs: additional plotting parameters
    """
    
    # Load data if CSV path provided
    if isinstance(data, str):
        df = pd.read_csv(data)
    else:
        df = data
    
    plt.figure(figsize=(12, 6))
    
    if plot_type == 'line':
        # Line chart - great for time series
        if isinstance(y_col, list):
            for col in y_col:
                plt.plot(df[x_col] if x_col else df.index, df[col], label=col, marker='o')
        else:
            plt.plot(df[x_col] if x_col else df.index, df[y_col], marker='o', linewidth=2)
        plt.xlabel(x_col or 'Index')
        plt.ylabel(y_col if isinstance(y_col, str) else 'Value')
        plt.title('Line Chart')
        plt.legend()
        plt.grid(True, alpha=0.3)
        
    elif plot_type == 'bar':
        # Bar chart - compare categories
        if isinstance(y_col, list):
            df.plot(x=x_col, y=y_col, kind='bar', ax=plt.gca())
        else:
            plt.bar(df[x_col] if x_col else df.index, df[y_col], color='steelblue')
        plt.xlabel(x_col or 'Category')
        plt.ylabel(y_col if isinstance(y_col, str) else 'Value')
        plt.title('Bar Chart')
        plt.xticks(rotation=45, ha='right')
        
    elif plot_type == 'scatter':
        # Scatter plot - show relationships
        plt.scatter(df[x_col], df[y_col], alpha=0.6, s=50, color='coral')
        plt.xlabel(x_col)
        plt.ylabel(y_col)
        plt.title('Scatter Plot')
        plt.grid(True, alpha=0.3)
        
        # Add trend line if requested
        if kwargs.get('trendline', False):
            z = np.polyfit(df[x_col].dropna(), df[y_col].dropna(), 1)
            p = np.poly1d(z)
            plt.plot(df[x_col], p(df[x_col]), "r--", alpha=0.8, label='Trend')
            plt.legend()
    
    elif plot_type == 'pie':
        # Pie chart - show proportions
        plt.pie(df[y_col], labels=df[x_col], autopct='%1.1f%%', startangle=90)
        plt.title('Pie Chart')
        plt.axis('equal')
        
    elif plot_type == 'histogram':
        # Histogram - show distribution
        plt.hist(df[y_col], bins=kwargs.get('bins', 30), color='skyblue', edgecolor='black', alpha=0.7)
        plt.xlabel(y_col)
        plt.ylabel('Frequency')
        plt.title('Histogram')
        plt.grid(True, alpha=0.3)
        
    elif plot_type == 'box':
        # Box plot - show statistical distribution
        if isinstance(y_col, list):
            df[y_col].boxplot()
        else:
            df.boxplot(column=y_col, by=x_col if x_col else None)
        plt.title('Box Plot')
        plt.suptitle('')  # Remove default title
    
    plt.tight_layout()
    plt.savefig(f'{plot_type}_chart.png', dpi=300, bbox_inches='tight')
    print(f"Chart saved as {plot_type}_chart.png")
    plt.show()

# Example usage with stock data
# Line chart
create_plots_from_data('stock_data.csv', plot_type='line', x_col='date', y_col='close')

# Multiple lines
create_plots_from_data('stock_data.csv', plot_type='line', x_col='date', 
                       y_col=['open', 'close', 'high', 'low'])

# Bar chart comparing volumes
create_plots_from_data('stock_data.csv', plot_type='bar', x_col='date', y_col='volume')

# Scatter plot: price vs volume
create_plots_from_data('stock_data.csv', plot_type='scatter', 
                       x_col='volume', y_col='close', trendline=True)

# Histogram of daily returns
create_plots_from_data('stock_data.csv', plot_type='histogram', y_col='daily_return', bins=50)
```

### Advanced Visualization: Candlestick Charts

```python
import plotly.graph_objects as go

def plot_candlestick(symbol, period='1mo'):
    """Create interactive candlestick chart with plotly"""
    
    # Fetch data
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?interval=1d&range={period}"
    data = json.loads(urlopen(url).read())
    
    result = data['chart']['result'][0]
    timestamps = result['timestamp']
    quote = result['indicators']['quote'][0]
    
    df = pd.DataFrame({
        'date': pd.to_datetime(timestamps, unit='s'),
        'open': quote['open'],
        'high': quote['high'],
        'low': quote['low'],
        'close': quote['close'],
        'volume': quote['volume']
    })
    
    # Create candlestick chart
    fig = go.Figure(data=[go.Candlestick(
        x=df['date'],
        open=df['open'],
        high=df['high'],
        low=df['low'],
        close=df['close'],
        name='Price'
    )])
    
    # Add volume bars
    fig.add_trace(go.Bar(
        x=df['date'],
        y=df['volume'],
        name='Volume',
        yaxis='y2',
        marker_color='rgba(100, 150, 200, 0.3)'
    ))
    
    # Update layout
    fig.update_layout(
        title=f'{symbol} Candlestick Chart',
        yaxis_title='Price ($)',
        yaxis2=dict(title='Volume', overlaying='y', side='right'),
        xaxis_rangeslider_visible=False,
        height=600
    )
    
    fig.write_html(f'{symbol}_candlestick.html')
    print(f"Interactive chart saved as {symbol}_candlestick.html")
    fig.show()

# Example usage
plot_candlestick('AAPL', period='3mo')
```

### Quick Plot Generation from Any CSV

```bash
# Using matplotlib directly from command line (requires Python)
python << EOF
import pandas as pd
import matplotlib.pyplot as plt

# Read any CSV file
df = pd.read_csv('data.csv')

# Auto-detect columns and create appropriate plots
for col in df.select_dtypes(include=['float64', 'int64']).columns:
    plt.figure(figsize=(10, 6))
    df[col].plot(kind='line', title=f'{col} Over Time')
    plt.savefig(f'{col}_plot.png')
    print(f"Created {col}_plot.png")
    plt.close()
EOF

# One-liner to create a quick line plot
python -c "import pandas as pd; import matplotlib.pyplot as plt; df = pd.read_csv('data.csv'); df.plot(); plt.savefig('quick_plot.png'); print('Plot saved')"
```

### Visualization Best Practices

1. **Choose the Right Chart Type**
   - Line: Time series, trends
   - Bar: Comparisons between categories
   - Scatter: Relationships between variables
   - Pie: Proportions (use sparingly)
   - Histogram: Distribution of values
   - Box: Statistical summaries

2. **Design Principles**
   - Clear titles and labels
   - Readable font sizes (12-14pt for labels)
   - Appropriate color schemes (consider colorblind-friendly palettes)
   - Grid lines for easier reading
   - Legend when multiple series
   - High resolution for sharing (300 dpi)

3. **Data Preparation**
   - Clean missing values
   - Handle outliers appropriately
   - Aggregate data if too dense
   - Sort data logically

## Data Engineering for Stock Analysis

Process and analyze large datasets:

```bash
# Download historical data and save to CSV
curl -s "https://query1.finance.yahoo.com/v8/finance/chart/AAPL?interval=1d&range=1y" | \
  jq -r '.chart.result[0] | .timestamp as $t | .indicators.quote[0] | .open as $o | .high as $h | .low as $l | .close as $c | .volume as $v | ["date","open","high","low","close","volume"], (range($t|length) | [($t[.]|todateiso8601), $o[.], $h[.], $l[.], $c[.], $v[.]]) | @csv' > stock_data.csv

# Analyze with awk for quick stats
awk -F, 'NR>1 {sum+=$5; count++} END {print "Average Close:", sum/count}' stock_data.csv
```
