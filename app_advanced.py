from flask import Flask, render_template, request, send_file, url_for
import yfinance as yf
import pandas as pd
import numpy as np
from io import BytesIO
import plotly.graph_objects as go
import os
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

    combined_results = pd.concat([
        pd.DataFrame([{"Strategy": "--- Breakout Strategy ---"}]), results_breakout,
        pd.DataFrame([{"Strategy": "--- SMA Crossover Strategy ---"}]), results_crossover,
        pd.DataFrame([{"Strategy": "--- Breakout Strategy with Risk Management ---"}]), results_breakout_risk,
        pd.DataFrame([{"Strategy": "--- ML Predicted Breakouts ---"}]), results_ml
    ], ignore_index=True)

    output_csv = BytesIO()
    combined_results.to_csv(output_csv, index=False)
    output_csv.seek(0)

    plot_path_breakout = create_plotly_plot(data, breakout_days, "Breakout Strategy", results_breakout)
    plot_path_risk = create_plotly_plot(data, breakout_days, "Breakout Strategy with Risk Management", results_breakout_risk)
    plot_path_crossover = create_plotly_plot(data, crossover_days, "SMA Crossover Strategy", results_crossover)
    plot_path_ml = create_plotly_plot(data, ml_results, "ML Predicted Breakouts", results_ml)

    metrics = calculate_metrics(combined_results)

    return render_template('report.html',
                           ticker=ticker,
                           metrics=metrics,
                           breakout_plot=plot_path_breakout,
                           crossover_plot=plot_path_crossover,
                           breakout_risk_plot=plot_path_risk,
                           ml_plot=plot_path_ml,
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

def predict_breakouts_with_ml(data):
    data = data.dropna()
    X = data[['Close', 'Volume', '20DayAvgVolume', '10DaySMA', '50DaySMA']]
    y = ((data['VolumeBreakout']) & (data['PriceBreakout'])).astype(int)
    model = RandomForestClassifier(n_estimators=200, max_depth=10, random_state=42)
    model.fit(X, y)
    data['ML_Predicted_Breakout'] = model.predict(X)
    return data[data['ML_Predicted_Breakout'] == 1]

def create_plotly_plot(data, trade_days, strategy_name, results):
    fig = go.Figure()

    fig.add_trace(go.Scatter(
        x=data.index, 
        y=data['Close'], 
        mode='lines', 
        name='Stock Price', 
        line=dict(color='blue')
    ))

    fig.add_trace(go.Scatter(
        x=trade_days.index, 
        y=trade_days['Close'], 
        mode='markers', 
        name='Buy Point', 
        marker=dict(color='green', symbol='triangle-up', size=10)
    ))

    sell_dates = pd.to_datetime(results['Sell Date'].dropna())
    sell_prices = results['Sell Price'].dropna()
    fig.add_trace(go.Scatter(
        x=sell_dates, 
        y=sell_prices, 
        mode='markers', 
        name='Sell Point', 
        marker=dict(color='red', symbol='triangle-down', size=10)
    ))

    fig.update_layout(
        title=f"{strategy_name} - Buy and Sell Points",
        xaxis_title="Date",
        yaxis_title="Price",
        template="plotly_dark",
        showlegend=True
    )

    plot_path = f'static/{strategy_name.replace(" ", "_").lower()}.html'
    fig.write_html(plot_path)

    return plot_path

@app.route('/download-csv')
def download_csv():
    return send_file(output_csv, download_name="combined_strategy_report.csv", as_attachment=True)

if __name__ == '__main__':
    app.run(debug=True)
