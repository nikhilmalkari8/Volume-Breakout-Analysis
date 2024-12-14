from flask import Flask, render_template, request, send_file, redirect, url_for
import yfinance as yf
import pandas as pd
import matplotlib
matplotlib.use('Agg')  # Use Agg backend to avoid GUI errors
import matplotlib.pyplot as plt
from io import BytesIO
import os
import numpy as np

app = Flask(__name__)

@app.route('/', methods=['GET'])
def home():
    return render_template('index.html')

@app.route('/generate-report', methods=['POST'])
def generate_report():
    # Get form inputs
    ticker = request.form['ticker']
    start_date = request.form['start_date']
    end_date = request.form['end_date']
    volume_threshold = float(request.form['volume_threshold'])
    price_change = float(request.form['price_change'])
    holding_period = int(request.form['holding_period'])

    # Fetch historical data using yfinance
    stock = yf.Ticker(ticker)
    data = stock.history(start=start_date, end=end_date)

    # Error handling for no data
    if data.empty:
        return "<h2>No data found for the given ticker and date range.</h2>"

    # Calculate 20-day average volume
    data['20DayAvgVolume'] = data['Volume'].rolling(window=20).mean()

    # Identify breakout days
    data['VolumeBreakout'] = data['Volume'] > (volume_threshold / 100) * data['20DayAvgVolume']
    data['PriceChange'] = data['Close'].pct_change() * 100
    data['PriceBreakout'] = data['PriceChange'] > price_change

    # Calculate percentage increase in volume and price on breakout days
    data['VolumeIncrease (%)'] = (data['Volume'] / data['20DayAvgVolume']) * 100
    data['PriceIncrease (%)'] = data['PriceChange']

    # Filter breakout days
    breakout_days = data[(data['VolumeBreakout']) & (data['PriceBreakout'])]

    # Calculate returns for each breakout day
    results = []
    for breakout_date in breakout_days.index:
        buy_price = data.at[breakout_date, 'Close']
        sell_date = breakout_date + pd.Timedelta(days=holding_period)
        if sell_date in data.index:
            sell_price = data.at[sell_date, 'Close']
            return_percent = ((sell_price - buy_price) / buy_price) * 100
            results.append({
                'Breakout Date': breakout_date.date(),
                'Buy Price': round(buy_price, 2),
                'Sell Date': sell_date.date(),
                'Sell Price': round(sell_price, 2),
                'Return (%)': round(return_percent, 2),
                'Volume Increase (%)': round(data.at[breakout_date, 'VolumeIncrease (%)'], 2),
                'Price Increase (%)': round(data.at[breakout_date, 'PriceIncrease (%)'], 2)
            })

    # Error handling for no breakout days
    if not results:
        return "<h2>No breakout days found with the given criteria.</h2>"

    # Create DataFrame for results
    results_df = pd.DataFrame(results)

    # Calculate cumulative returns and win rate
    results_df['Cumulative Return (%)'] = results_df['Return (%)'].cumsum()
    win_rate = (results_df['Return (%)'] > 0).mean() * 100

    # Calculate additional metrics
    returns = results_df['Return (%)']
    sharpe_ratio = returns.mean() / returns.std() if returns.std() != 0 else 0
    max_drawdown = (results_df['Cumulative Return (%)'].cummax() - results_df['Cumulative Return (%)']).max()
    volatility = returns.std()

    # Visualization
    plt.figure(figsize=(12, 8))
    plt.plot(data.index, data['Close'], label='Stock Price', color='blue')
    plt.scatter(breakout_days.index, breakout_days['Close'], color='green', label='Breakout Day', marker='^')
    for i, row in results_df.iterrows():
        sell_date = pd.to_datetime(row['Sell Date'])
        plt.scatter(sell_date, row['Sell Price'], color='red', label='Sell Point' if i == 0 else "")
    plt.xlabel('Date')
    plt.ylabel('Price')
    plt.title(f'{ticker} Price with Breakout Points')
    plt.legend()
    plt.grid(True)

    # Create a folder to store images
    if not os.path.exists("static"):
        os.makedirs("static")
    plot_path = f"static/{ticker}_breakout_plot.png"
    plt.savefig(plot_path)
    plt.close()  # Close the plot to free memory

    # Save results to CSV in a global variable
    global output
    output = BytesIO()
    results_df.to_csv(output, index=False)
    output.seek(0)

    # HTML Response with CSV Download and Plot
    return f'''
        <h2>Breakout Analysis for {ticker}</h2>
        <p>Win Rate: {win_rate:.2f}%</p>
        <p>Sharpe Ratio: {sharpe_ratio:.2f}</p>
        <p>Max Drawdown: {max_drawdown:.2f}%</p>
        <p>Volatility: {volatility:.2f}%</p>
        <a href="/download-report">Download Report</a><br><br>
        <a href="/view-visualizations?ticker={ticker}"><button>View Visualizations</button></a><br><br>
        <img src="/{plot_path}" alt="Breakout Plot" style="width:80%;">
    '''

@app.route('/download-report')
def download_report():
    return send_file(output, download_name="breakout_report.csv", as_attachment=True)

@app.route('/view-visualizations', methods=['GET'])
def view_visualizations():
    ticker = request.args.get('ticker')
    plot_path = f"static/{ticker}_breakout_plot.png"
    return f'<h2>Visualizations for {ticker}</h2><img src="/{plot_path}" alt="Breakout Plot" style="width:80%;">'

if __name__ == '__main__':
    app.run(debug=True)
