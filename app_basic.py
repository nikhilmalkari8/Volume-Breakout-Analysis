from flask import Flask, render_template, request, send_file, url_for
import yfinance as yf
import pandas as pd
import numpy as np
from io import BytesIO
import plotly.graph_objects as go
from pandas.tseries.offsets import BDay

app = Flask(__name__)

output_csv = None

@app.route('/', methods=['GET'])
def home():
    return render_template('index.html')

@app.route('/generate-report', methods=['POST'])
def generate_report():
    global output_csv

    try:
        # Get form inputs with validation
        ticker = request.form['ticker']
        start_date = request.form['start_date']
        end_date = request.form['end_date']
        volume_threshold = float(request.form['volume_threshold'])
        price_change = float(request.form['price_change'])
        holding_period = int(request.form['holding_period'])
    except ValueError:
        return "<h2>Error: Invalid input. Please ensure thresholds are numeric.</h2>"

    # Fetch historical data using yfinance
    stock = yf.Ticker(ticker)
    try:
        data = stock.history(start=start_date, end=end_date)
        if data.empty:
            return "<h2>Error: No data found for the given ticker and date range.</h2>"
    except Exception as e:
        return f"<h2>Error fetching data: {str(e)}</h2>"

    # Check if data is sufficient for 20-day average calculation
    if len(data) < 20:
        return "<h2>Error: Date range too short for 20-day average volume calculation.</h2>"

    # Check for missing data
    if data.isnull().any().any():
        return "<h2>Warning: Missing data detected. Please verify data completeness.</h2>"

    # Calculate 20-day average volume excluding the current day
    data['20DayAvgVolume'] = data['Volume'].rolling(window=20).mean().shift(1)

    # Identify breakout days
    data['VolumeBreakout'] = data['Volume'] > (1 + volume_threshold / 100) * data['20DayAvgVolume']
    data['PriceChange'] = data['Close'].pct_change() * 100
    data['PriceBreakout'] = data['PriceChange'] > price_change

    # Filter breakout days
    breakout_days = data[(data['VolumeBreakout']) & (data['PriceBreakout'])]

    # Detailed logging for verification
    for index, row in breakout_days.iterrows():
        print(f"Date: {index}")
        print(f"Volume: {row['Volume']}")
        print(f"20-Day Avg Volume: {row['20DayAvgVolume']}")
        print(f"Volume Threshold: {(1 + volume_threshold / 100) * row['20DayAvgVolume']}")
        print(f"Price Change: {row['PriceChange']:.2f}%")
        print("-" * 50)

    # Calculate returns for breakout strategy
    results_breakout = pd.DataFrame()
    if not breakout_days.empty:
        results_breakout = calculate_returns(data, breakout_days, holding_period, "Breakout Strategy")

    # Save results to CSV
    output_csv = BytesIO()
    results_breakout.to_csv(output_csv, index=False, float_format="%.2f")
    output_csv.seek(0)

    print("CSV generated successfully")

    # Generate plot
    plot_path = create_plotly_plot(data, breakout_days, ticker, "Breakout Strategy", results_breakout)

    return render_template('report2.html',
                           ticker=ticker,
                           metrics=calculate_metrics(results_breakout),
                           breakout_plot=plot_path,
                           download_link=url_for('download_csv'))

def calculate_returns(data, trade_days, holding_period, strategy_name):
    results = []
    for trade_date in trade_days.index:
        buy_price = data.at[trade_date, 'Close']
        
        # Calculate the sell date as 10 discrete trading days later
        sell_date = trade_date + BDay(holding_period)

        # Check if sell date exists in the data
        if sell_date in data.index:
            sell_price = data.at[sell_date, 'Close']
            return_percent = ((sell_price - buy_price) / buy_price) * 100
            sell_date_display = sell_date.date()
        else:
            sell_price = None
            return_percent = None
            sell_date_display = "N/A"

        results.append({
            'Strategy': strategy_name,
            'Breakout Date': trade_date.date(),
            'Buy Price': buy_price,
            'Sell Date': sell_date_display,
            'Sell Price': sell_price,
            'Return (%)': return_percent
        })
    return pd.DataFrame(results)

def calculate_metrics(results):
    metrics = ""
    returns = results['Return (%)'].dropna()

    win_rate = (returns > 0).mean() * 100 if not returns.empty else 0
    avg_return = returns.mean() if not returns.empty else 0
    max_drawdown = (returns.cumsum().cummax() - returns.cumsum()).max() if not returns.empty else 0

    metrics += f"Breakout Strategy\n"
    metrics += f"Win Rate: {win_rate:.2f}%\n"
    metrics += f"Average Return: {avg_return:.2f}%\n"
    metrics += f"Maximum Drawdown: {max_drawdown:.2f}%\n\n"
    return metrics

def create_plotly_plot(data, trade_days, ticker, title, results):
    fig = go.Figure()

    # Plot stock price
    fig.add_trace(go.Scatter(x=data.index, y=data['Close'], mode='lines', name='Stock Price'))

    # Plot buy points
    fig.add_trace(go.Scatter(
        x=trade_days.index,
        y=trade_days['Close'],
        mode='markers',
        name='Buy Point',
        marker=dict(color='green', symbol='triangle-up', size=10)
    ))

    # Plot sell points
    sell_dates = pd.to_datetime(results['Sell Date'].dropna())
    sell_prices = results['Sell Price'].dropna()

    fig.add_trace(go.Scatter(
        x=sell_dates,
        y=sell_prices,
        mode='markers',
        name='Sell Point',
        marker=dict(color='red', symbol='triangle-down', size=10)
    ))

    # Add titles and labels
    fig.update_layout(
        title=f"{ticker} - {title}",
        xaxis_title="Date",
        yaxis_title="Price",
        template="plotly_dark",
        showlegend=True
    )

    # Save plot as HTML
    plot_path = f'static/{ticker}_{title.replace(" ", "_").lower()}.html'
    fig.write_html(plot_path)
    return plot_path

@app.route('/download-csv')
def download_csv():
    global output_csv
    if output_csv:
        output_csv.seek(0)
        return send_file(output_csv, download_name="breakout_strategy_report.csv", as_attachment=True)
    else:
        return "Error: Report not found. Please generate the report first."

if __name__ == '__main__':
    app.run(debug=True)
