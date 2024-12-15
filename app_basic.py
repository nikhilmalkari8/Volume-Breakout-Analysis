from flask import Flask, render_template, request, send_file, url_for
import yfinance as yf
import pandas as pd
from io import BytesIO
import plotly.graph_objects as go
from pandas.tseries.offsets import CustomBusinessDay
from pandas.tseries.holiday import USFederalHolidayCalendar
import traceback

app = Flask(__name__)

# Define a custom business day with US federal holidays
us_bd = CustomBusinessDay(calendar=USFederalHolidayCalendar())

def fetch_data(ticker: str, start_date: str, end_date: str) -> pd.DataFrame:
    """Fetch historical stock data using yfinance."""
    try:
        stock = yf.Ticker(ticker)
        data = stock.history(start=start_date, end=end_date)
        print(f"Fetched data for {ticker} from {start_date} to {end_date}")
        print(data.head())
        return data
    except Exception as e:
        print(f"Error fetching data: {e}")
        return pd.DataFrame()

def identify_breakouts(data: pd.DataFrame, volume_threshold: float, price_change: float) -> pd.DataFrame:
    """Identify breakout days based on volume and price change thresholds."""
    try:
        data['20DayAvgVolume'] = data['Volume'].rolling(window=20).mean().shift(1)
        data['VolumeBreakout'] = data['Volume'] > (1 + volume_threshold / 100) * data['20DayAvgVolume']
        data['PriceChange'] = data['Close'].pct_change() * 100
        data['PriceBreakout'] = data['PriceChange'] > price_change
        breakout_days = data[(data['VolumeBreakout']) & (data['PriceBreakout'])]
        print(f"Identified {len(breakout_days)} breakout days")
        return breakout_days
    except Exception as e:
        print(f"Error identifying breakouts: {e}")
        return pd.DataFrame()

def calculate_returns(data: pd.DataFrame, breakout_days: pd.DataFrame, holding_period: int, waiting_period: int, strategy_name: str) -> pd.DataFrame:
    """Calculate returns for each breakout based on the holding period and waiting period."""
    results = []

    for breakout_date in breakout_days.index:
        # Calculate the Buy Date: Breakout Date + Waiting Period
        buy_date = breakout_date + waiting_period * us_bd

        # Ensure the Buy Date is within the data range
        if buy_date not in data.index or buy_date >= data.index[-1]:
            continue

        buy_price = data.at[buy_date, 'Close']

        # Calculate the initial Sell Date: Buy Date + Holding Period (40 trading days)
        sell_date = buy_date + holding_period * us_bd

        # If Sell Date is not in the data, find the next valid trading day
        while sell_date not in data.index and sell_date <= data.index[-1]:
            sell_date += us_bd

        # Ensure the final Sell Date is within the data range
        if sell_date not in data.index:
            print(f"No valid Sell Date found for breakout on {breakout_date}")
            continue

        sell_price = data.at[sell_date, 'Close']
        return_percent = ((sell_price - buy_price) / buy_price) * 100

        results.append({
            'Strategy': strategy_name,
            'Breakout Date': breakout_date.date(),
            'Buy Date': buy_date.date(),
            'Buy Price': buy_price,
            'Sell Date': sell_date.date(),
            'Sell Price': sell_price,
            'Return (%)': return_percent
        })

    return pd.DataFrame(results)

def create_plot(data: pd.DataFrame, results: pd.DataFrame, ticker: str, title: str) -> str:
    """Create a Plotly plot showing buy and sell points on the stock price chart."""
    fig = go.Figure()

    # Plot stock price
    fig.add_trace(go.Scatter(x=data.index, y=data['Close'], mode='lines', name='Stock Price'))

    # Plot buy points
    buy_dates = pd.to_datetime(results['Buy Date'].dropna(), errors='coerce')
    buy_prices = results['Buy Price'].dropna()
    fig.add_trace(go.Scatter(x=buy_dates, y=buy_prices, mode='markers', name='Buy Point',
                             marker=dict(color='green', symbol='triangle-up', size=10)))

    # Plot sell points for valid trades
    valid_sell_trades = results[results['Sell Date'] != 'N/A']
    sell_dates = pd.to_datetime(valid_sell_trades['Sell Date'], errors='coerce')
    sell_prices = valid_sell_trades['Sell Price'].dropna()
    fig.add_trace(go.Scatter(x=sell_dates, y=sell_prices, mode='markers', name='Sell Point',
                             marker=dict(color='red', symbol='triangle-down', size=10)))

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

def calculate_performance_metrics(results: pd.DataFrame) -> dict:
    """Calculate and return performance metrics for the strategy."""
    # Filter valid trades with non-null returns
    valid_results = results.dropna(subset=['Return (%)'])
    
    total_trades = len(valid_results)
    winning_trades = len(valid_results[valid_results['Return (%)'] > 0])
    losing_trades = len(valid_results[valid_results['Return (%)'] < 0])
    average_return = valid_results['Return (%)'].mean()
    max_return = valid_results['Return (%)'].max()
    min_return = valid_results['Return (%)'].min()
    
    metrics = {
        "Total Trades": total_trades,
        "Winning Trades": winning_trades,
        "Losing Trades": losing_trades,
        "Average Return (%)": average_return,
        "Maximum Return (%)": max_return,
        "Minimum Return (%)": min_return
    }
    
    # Print metrics to the console
    print("\nPerformance Metrics:")
    for key, value in metrics.items():
        print(f"{key}: {value:.2f}")
    
    return metrics

@app.route('/', methods=['GET'])
def home():
    return render_template('index.html')

@app.route('/generate-report', methods=['POST'])
def generate_report():
    global output_csv

    try:
        # Get form inputs
        ticker = request.form['ticker']
        start_date = request.form['start_date']
        end_date = request.form['end_date']
        volume_threshold = float(request.form['volume_threshold'])
        price_change = float(request.form['price_change'])
        holding_period = int(request.form['holding_period'])
        waiting_period = int(request.form['waiting_period'])

        # Fetch data
        data = fetch_data(ticker, start_date, end_date)
        if data.empty:
            return "<h2>Error: No data found for the given ticker and date range.</h2>"

        # Identify breakout days
        breakout_days = identify_breakouts(data, volume_threshold, price_change)
        if breakout_days.empty:
            return "<h2>No breakouts identified with the given parameters. Please adjust the thresholds.</h2>"

        # Calculate returns
        results_breakout = calculate_returns(data, breakout_days, holding_period, waiting_period, "Breakout Strategy")
        if results_breakout.empty:
            return "<h2>No valid trades found with the given holding and waiting period. Please adjust the periods.</h2>"

        # Calculate and print performance metrics
        metrics = calculate_performance_metrics(results_breakout)

        # Save results to CSV
        output_csv = BytesIO()
        results_breakout.to_csv(output_csv, index=False, float_format="%.2f")
        output_csv.seek(0)

        # Create plot
        plot_path = create_plot(data, results_breakout, ticker, "Breakout Strategy")

        return render_template('report2.html',
                               ticker=ticker,
                               download_link=url_for('download_csv'),
                               breakout_plot=plot_path,
                               metrics=metrics)

    except Exception as e:
        error_message = f"<h2>Internal Server Error: {str(e)}</h2><pre>{traceback.format_exc()}</pre>"
        return error_message

@app.route('/download-csv')
def download_csv():
    global output_csv
    try:
        if output_csv:
            output_csv.seek(0)
            return send_file(output_csv, download_name="breakout_strategy_report.csv", as_attachment=True)
        else:
            return "<h2>Error: No CSV file found. Please generate the report first.</h2>"
    except Exception as e:
        return f"<h2>Error during download: {str(e)}</h2>"

if __name__ == '__main__':
    app.run(debug=True)
