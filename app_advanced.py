from flask import Flask, render_template, request, send_file, url_for
import yfinance as yf
import pandas as pd
import matplotlib
matplotlib.use('Agg')  # Use Agg backend to avoid GUI errors
import matplotlib.pyplot as plt
from io import BytesIO
import os
import numpy as np
from sklearn.ensemble import RandomForestClassifier
from sklearn.model_selection import train_test_split
from sklearn.metrics import accuracy_score, classification_report

app = Flask(__name__)

output_csv = None

@app.route('/', methods=['GET'])
def home():
    return render_template('index.html')

@app.route('/generate-report', methods=['POST'])
def generate_report():
    global output_csv
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
    data['10DaySMA'] = data['Close'].rolling(window=10).mean()
    data['50DaySMA'] = data['Close'].rolling(window=50).mean()

    # Identify breakout days
    data['VolumeBreakout'] = data['Volume'] > (volume_threshold / 100) * data['20DayAvgVolume']
    data['PriceChange'] = data['Close'].pct_change() * 100
    data['PriceBreakout'] = data['PriceChange'] > price_change

    # Simple Moving Average Crossover Strategy
    data['SMA_Crossover_Buy'] = (data['10DaySMA'] > data['50DaySMA']) & (data['10DaySMA'].shift(1) <= data['50DaySMA'].shift(1))

    # Calculate returns for breakout strategy
    breakout_days = data[(data['VolumeBreakout']) & (data['PriceBreakout'])]
    results_breakout = calculate_returns(data, breakout_days, holding_period, "Breakout Strategy")

    # Calculate returns for SMA Crossover strategy
    crossover_days = data[data['SMA_Crossover_Buy']]
    results_crossover = calculate_returns(data, crossover_days, holding_period, "SMA Crossover Strategy")

    # Apply risk management to breakout strategy
    results_breakout_risk = calculate_returns(data, breakout_days, holding_period, "Breakout Strategy with Risk Management", stop_loss=2, take_profit=5)

    # Machine Learning Model for Breakout Prediction
    ml_results = predict_breakouts_with_ml(data)
    results_ml = calculate_returns(data, ml_results, holding_period, "ML Predicted Breakouts")

    # Add section headings and combine all results
    combined_results = pd.concat([
        pd.DataFrame([{"Strategy": "--- Breakout Strategy ---"}]), results_breakout,
        pd.DataFrame([{"Strategy": "--- SMA Crossover Strategy ---"}]), results_crossover,
        pd.DataFrame([{"Strategy": "--- Breakout Strategy with Risk Management ---"}]), results_breakout_risk,
        pd.DataFrame([{"Strategy": "--- ML Predicted Breakouts ---"}]), results_ml
    ], ignore_index=True)

    # Round prices to two decimal places
    combined_results['Buy Price'] = combined_results['Buy Price'].round(2)
    combined_results['Sell Price'] = combined_results['Sell Price'].round(2)

    # Calculate metrics
    metrics = calculate_metrics(combined_results)

    # Save the combined results to a CSV
    output_csv = BytesIO()
    combined_results.to_csv(output_csv, index=False)
    output_csv.seek(0)

    # Generate and save plots
    plot_path_breakout = save_plot(data, breakout_days, ticker, "Breakout Strategy")
    plot_path_crossover = save_plot(data, crossover_days, ticker, "SMA Crossover Strategy")
    plot_path_risk = save_plot(data, breakout_days, ticker, "Breakout Strategy with Risk Management")
    plot_path_ml = save_plot(data, ml_results, ticker, "ML Predicted Breakouts")

    # HTML Response with Links to Visualizations and CSV Download
    return f'''
        <h2>Strategy Comparison for {ticker}</h2>
        <a href="{url_for('download_csv')}">Download Combined Report</a><br><br>
        <h3>Breakout Strategy</h3>
        <a href="/{plot_path_breakout}">View Breakout Strategy Plot</a><br><br>
        <h3>SMA Crossover Strategy</h3>
        <a href="/{plot_path_crossover}">View SMA Crossover Plot</a><br><br>
        <h3>Breakout Strategy with Risk Management</h3>
        <a href="/{plot_path_risk}">View Risk Management Plot</a><br><br>
        <h3>Machine Learning Predicted Breakouts</h3>
        <a href="/{plot_path_ml}">View ML Predictions Plot</a><br><br>
        <h3>Performance Metrics</h3>
        <pre>{metrics}</pre>
    '''

def calculate_returns(data, trade_days, holding_period, strategy_name, stop_loss=None, take_profit=None):
    results = []
    for trade_date in trade_days.index:
        buy_price = data.at[trade_date, 'Close']
        sell_date = trade_date + pd.Timedelta(days=holding_period)
        sell_price = data.at[sell_date, 'Close'] if sell_date in data.index else None
        return_percent = ((sell_price - buy_price) / buy_price) * 100 if sell_price else None
        results.append({
            'Strategy': strategy_name,
            'Breakout Date': trade_date.date(),
            'Buy Price': buy_price,
            'Sell Date': sell_date.date() if sell_price else None,
            'Sell Price': sell_price,
            'Return (%)': return_percent
        })
    return pd.DataFrame(results)

def calculate_metrics(results):
    metrics = ""
    strategies = results['Strategy'].unique()
    for strategy in strategies:
        if strategy.startswith("---"):
            continue
        strategy_results = results[results['Strategy'] == strategy]
        returns = strategy_results['Return (%)'].dropna()
        
        win_rate = (returns > 0).mean() * 100 if not returns.empty else 0
        avg_return = returns.mean() if not returns.empty else 0
        max_drawdown = (returns.cumsum().cummax() - returns.cumsum()).max() if not returns.empty else 0

        metrics += f"{strategy}\n"
        metrics += f"Win Rate: {win_rate:.2f}%\n"
        metrics += f"Average Return: {avg_return:.2f}%\n"
        metrics += f"Maximum Drawdown: {max_drawdown:.2f}%\n\n"
    return metrics

def save_plot(data, trade_days, ticker, title):
    plt.figure(figsize=(12, 8))
    plt.plot(data.index, data['Close'], label='Stock Price', color='blue')
    plt.scatter(trade_days.index, trade_days['Close'], color='green', label='Trade Point', marker='^')
    plt.title(f'{ticker} - {title}')
    plt.legend()
    plt.grid(True)
    plot_path = f'static/{ticker}_{title.replace(" ", "_").lower()}.png'
    plt.savefig(plot_path)
    plt.close()
    return plot_path

def predict_breakouts_with_ml(data):
    data = data.dropna()
    X = data[['Close', 'Volume', '20DayAvgVolume', '10DaySMA', '50DaySMA']]
    y = ((data['VolumeBreakout']) & (data['PriceBreakout'])).astype(int)
    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42)
    model = RandomForestClassifier(n_estimators=100, random_state=42)
    model.fit(X_train, y_train)
    data['ML_Predicted_Breakout'] = model.predict(X)
    return data[data['ML_Predicted_Breakout'] == 1]
    
@app.route('/download-csv')
def download_csv():
    return send_file(output_csv, download_name="combined_strategy_report.csv", as_attachment=True)

if __name__ == '__main__':
    app.run(debug=True)
