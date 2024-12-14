from flask import Flask, render_template, request, send_file, url_for
import yfinance as yf
import pandas as pd
import numpy as np
from io import BytesIO
import plotly.graph_objects as go
from sklearn.ensemble import RandomForestClassifier
from sklearn.model_selection import train_test_split

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

    # Fetch historical data
    stock = yf.Ticker(ticker)
    data = stock.history(start=start_date, end=end_date)
    if data.empty:
        return "<h2>No data found for the given ticker and date range.</h2>"

    # Calculate technical indicators
    data['20DayAvgVolume'] = data['Volume'].rolling(window=20).mean()
    data['10DaySMA'] = data['Close'].rolling(window=10).mean()
    data['50DaySMA'] = data['Close'].rolling(window=50).mean()

    # Identify breakout points
    data['VolumeBreakout'] = data['Volume'] > (volume_threshold / 100) * data['20DayAvgVolume']
    data['PriceChange'] = data['Close'].pct_change() * 100
    data['PriceBreakout'] = data['PriceChange'] > price_change

    # Breakout Strategy
    breakout_days = data[(data['VolumeBreakout']) & (data['PriceBreakout'])]
    results_breakout = calculate_returns(data, breakout_days, holding_period, "Breakout Strategy")

    # SMA Crossover Strategy
    data['SMA_Crossover_Buy'] = (data['10DaySMA'] > data['50DaySMA']) & (data['10DaySMA'].shift(1) <= data['50DaySMA'].shift(1))
    crossover_days = data[data['SMA_Crossover_Buy']]
    results_crossover = calculate_returns(data, crossover_days, holding_period, "SMA Crossover Strategy")

    # Breakout Strategy with Risk Management
    results_breakout_risk = calculate_returns(data, breakout_days, holding_period, "Breakout Strategy with Risk Management", stop_loss=1.5, take_profit=3.0)

    # ML Predicted Breakouts
    ml_results = predict_breakouts_with_ml(data)
    results_ml = calculate_returns(data, ml_results, holding_period, "ML Predicted Breakouts")

    # Combine results
    combined_results = pd.concat([results_breakout, results_crossover, results_breakout_risk, results_ml], ignore_index=True)

    # Save to CSV
    output_csv = BytesIO()
    combined_results.to_csv(output_csv, index=False)
    output_csv.seek(0)

    # Generate Plotly Plots
    breakout_plot = create_plotly_plot(data, breakout_days, "Breakout Strategy")
    crossover_plot = create_plotly_plot(data, crossover_days, "SMA Crossover Strategy")
    breakout_risk_plot = create_plotly_plot(data, breakout_days, "Breakout Strategy with Risk Management")
    ml_plot = create_plotly_plot(data, ml_results, "ML Predicted Breakouts")

    return render_template('report.html',
                           ticker=ticker,
                           breakout_plot=breakout_plot,
                           crossover_plot=crossover_plot,
                           breakout_risk_plot=breakout_risk_plot,
                           ml_plot=ml_plot,
                           download_link=url_for('download_csv'))

def calculate_returns(data, trade_days, holding_period, strategy_name, stop_loss=None, take_profit=None):
    results = []
    for trade_date in trade_days.index:
        buy_price = data.at[trade_date, 'Close']
        sell_date = trade_date + pd.Timedelta(days=holding_period)
        sell_price = data.at[sell_date, 'Close'] if sell_date in data.index else None

        if stop_loss and take_profit:
            for i in range(holding_period):
                current_date = trade_date + pd.Timedelta(days=i)
                if current_date in data.index:
                    current_price = data.at[current_date, 'Close']
                    change = ((current_price - buy_price) / buy_price) * 100
                    if change <= -stop_loss or change >= take_profit:
                        sell_date = current_date
                        sell_price = current_price
                        break

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

def predict_breakouts_with_ml(data):
    data = data.dropna()
    X = data[['Close', 'Volume', '20DayAvgVolume', '10DaySMA', '50DaySMA']]
    y = ((data['VolumeBreakout']) & (data['PriceBreakout'])).astype(int)
    model = RandomForestClassifier(n_estimators=200, max_depth=10, random_state=42)
    model.fit(X, y)
    data['ML_Predicted_Breakout'] = model.predict(X)
    return data[data['ML_Predicted_Breakout'] == 1]

def create_plotly_plot(data, trade_days, strategy_name):
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=data.index, y=data['Close'], mode='lines', name='Stock Price'))
    fig.add_trace(go.Scatter(x=trade_days.index, y=trade_days['Close'], mode='markers', name='Buy Point', marker=dict(color='green', symbol='triangle-up')))
    plot_path = f'static/{strategy_name.replace(" ", "_").lower()}.html'
    fig.write_html(plot_path)
    return plot_path

@app.route('/download-csv')
def download_csv():
    return send_file(output_csv, download_name="strategy_report.csv", as_attachment=True)

if __name__ == '__main__':
    app.run(debug=True)
