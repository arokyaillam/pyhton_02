from flask import Flask, render_template, Response, jsonify, request
from flask_cors import CORS
import json
import time
import queue
from threading import Thread
from dotenv import load_dotenv
import os

from trading_engine import TradingEngine
from upstox_client import UpstoxWebSocketClient
from database import Database

load_dotenv()

app = Flask(__name__)
app.config['SECRET_KEY'] = os.getenv('FLASK_SECRET_KEY', 'dev-secret-key')

CORS(app, resources={
    r"/api/*": {"origins": "*"},
    r"/stream": {"origins": "*"}
})

db = Database(os.getenv('DATABASE_PATH', 'trading.db'))
trading_engine = TradingEngine(db)
ws_client = None
message_queue = queue.Queue(maxsize=1000)


@app.route('/')
def index():
    return render_template('index.html')


@app.route('/stream')
def stream():
    def event_stream():
        try:
            while True:
                try:
                    message = message_queue.get(timeout=1)
                    yield f"data: {json.dumps(message)}\n\n"
                except queue.Empty:
                    yield f"data: {json.dumps({'type': 'heartbeat'})}\n\n"
                time.sleep(0.1)
        except GeneratorExit:
            pass
    
    return Response(
        event_stream(),
        mimetype='text/event-stream',
        headers={
            'Cache-Control': 'no-cache',
            'X-Accel-Buffering': 'no',
            'Connection': 'keep-alive'
        }
    )


@app.route('/api/start-trading', methods=['POST'])
def start_trading():
    global ws_client
    
    try:
        data = request.get_json()
        instruments = data.get('instruments', ['NSE_FO|61755'])
        
        ws_client = UpstoxWebSocketClient(
            access_token=os.getenv('UPSTOX_ACCESS_TOKEN'),
            instruments=instruments,
            mode='full_d30',
            on_message_callback=handle_market_data
        )
        
        ws_thread = Thread(target=ws_client.connect, daemon=True)
        ws_thread.start()
        
        return jsonify({
            'status': 'success',
            'message': 'Trading started'
        })
    
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500


@app.route('/api/stop-trading', methods=['POST'])
def stop_trading():
    global ws_client
    
    try:
        if ws_client:
            ws_client.disconnect()
            ws_client = None
        
        return jsonify({'status': 'success'})
    
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500


@app.route('/api/positions')
def get_positions():
    return jsonify(db.get_active_positions())


@app.route('/api/trades')
def get_trades():
    limit = request.args.get('limit', 50, type=int)
    return jsonify(db.get_trades(limit=limit))


@app.route('/api/stats')
def get_stats():
    return jsonify(db.get_trading_stats())


@app.route('/api/health')
def health_check():
    return jsonify({
        'status': 'healthy',
        'versions': {
            'flask': '3.1.2',
            'websockets': '15.0.1',
            'upstox_sdk': '2.18.0',
            'tailwind': '4.1.0'
        }
    })


def handle_market_data(feed_data):
    try:
        trading_engine.process_tick(feed_data)
        decision = trading_engine.get_trading_decision()
        
        if decision['action'] in ['BUY', 'SELL']:
            order_result = ws_client.place_order(
                symbol=decision['symbol'],
                transaction_type=decision['action'],
                quantity=decision['quantity'],
                price=decision['entry'],
                trigger_price=decision['stop_loss']
            )
            
            if order_result['status'] == 'success':
                db.save_trade(decision, order_result)
                
                try:
                    message_queue.put({'type': 'trade', 'data': decision}, timeout=0.5)
                except queue.Full:
                    pass
        
        try:
            message_queue.put({
                'type': 'market_data',
                'data': {
                    'ltp': trading_engine.tick_data[-1]['ltp'] if trading_engine.tick_data else 0,
                    'vwap': trading_engine.get_vwap(),
                    'pressure': trading_engine.get_order_book_pressure(),
                    'gamma': trading_engine.tick_data[-1]['gamma'] if trading_engine.tick_data else 0
                }
            }, timeout=0.5)
        except queue.Full:
            pass
        
        if trading_engine.active_position:
            try:
                message_queue.put({
                    'type': 'position_update',
                    'data': trading_engine.active_position
                }, timeout=0.5)
            except queue.Full:
                pass
    
    except Exception as e:
        print(f"Error: {e}")


if __name__ == '__main__':
    print("🚀 Upstox Trading System")
    print("📦 Flask 3.1.2 | Tailwind 4.1 | WebSockets 15.0.1")
    print("🌐 http://localhost:5000")
    
    app.run(debug=True, threaded=True, host='0.0.0.0', port=5000)
