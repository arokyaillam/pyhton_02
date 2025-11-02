# app.py - Enhanced with Options Route

from flask import Flask, render_template, Response, jsonify, request
from flask_cors import CORS
import json
import time
import queue
from threading import Thread
from dotenv import load_dotenv
import os

from trading_engine import TradingEngine
from trading_engine_options import NiftyOptionsTradingEngine
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

# Two separate engines
futures_engine = TradingEngine(db)
options_engine = NiftyOptionsTradingEngine(db)

# Track which engine is active
active_engine = None
engine_type = None  # 'futures' or 'options'

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
    """Start FUTURES trading"""
    global ws_client, active_engine, engine_type
    
    try:
        data = request.get_json()
        instruments = data.get('instruments', ['NSE_FO|61755'])
        
        active_engine = futures_engine
        engine_type = 'futures'
        
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
            'message': 'Futures trading started',
            'engine': 'futures'
        })
    
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500


@app.route('/api/start-options-trading', methods=['POST'])
def start_options_trading():
    """Start OPTIONS trading"""
    global ws_client, active_engine, engine_type
    
    try:
        data = request.get_json()
        # Options instruments: CE/PE strikes
        instruments = data.get('instruments', ['NSE_FO|NIFTY2550619900CE'])
        
        active_engine = options_engine
        engine_type = 'options'
        
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
            'message': 'Options trading started',
            'engine': 'options'
        })
    
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500


@app.route('/api/stop-trading', methods=['POST'])
def stop_trading():
    global ws_client, active_engine, engine_type
    
    try:
        if ws_client:
            ws_client.disconnect()
            ws_client = None
        
        active_engine = None
        engine_type = None
        
        return jsonify({'status': 'success'})
    
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500


@app.route('/api/signal-details')
def get_signal_details():
    """Get detailed signal breakdown"""
    if not active_engine:
        return jsonify({'status': 'no_engine'})
    
    try:
        decision = active_engine.get_trading_decision()
        
        # Get additional market data
        if active_engine.tick_data:
            current_tick = active_engine.tick_data[-1]
            order_book = current_tick['order_book']
            
            details = {
                'action': decision.get('action'),
                'score': decision.get('score', 0),
                'confidence': decision.get('confidence', 0),
                'reasons': decision.get('reasons', []),
                'signal_details': decision.get('signal_details', {}),
                
                # Order Book Details
                'order_book': {
                    'pressure_score': order_book['pressure_score'],
                    'top5_imb': order_book.get('top5_imb', 0),
                    'mid10_imb': order_book.get('mid10_imb', 0),
                    'deep15_imb': order_book.get('deep15_imb', 0),
                    'spread_percent': order_book['spread_percent']
                },
                
                # Greeks (if options)
                'greeks': active_engine.get_current_greeks() if hasattr(active_engine, 'get_current_greeks') else {},
                
                'engine_type': engine_type
            }
            
            return jsonify(details)
        
        return jsonify({
            'action': decision.get('action'),
            'score': decision.get('score', 0),
            'message': decision.get('message', '')
        })
    
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
        'active_engine': engine_type,
        'versions': {
            'flask': '3.1.2',
            'websockets': '15.0.1',
            'upstox_sdk': '2.18.0',
            'tailwind': '4.1.0'
        }
    })


def handle_market_data(feed_data):
    """Process market data with active engine"""
    global active_engine
    
    if not active_engine:
        return
    
    try:
        active_engine.process_tick(feed_data)
        decision = active_engine.get_trading_decision()
        
        # Execute trade
        if decision['action'] in ['BUY', 'SELL']:
            order_result = ws_client.place_order(
                symbol=decision['symbol'],
                transaction_type=decision['action'],
                quantity=decision['quantity'],
                price=decision['entry'],
                trigger_price=decision.get('stop_loss')
            )
            
            if order_result['status'] == 'success':
                db.save_trade(decision, order_result)
                
                try:
                    message_queue.put({
                        'type': 'trade',
                        'data': {
                            **decision,
                            'engine_type': engine_type
                        }
                    }, timeout=0.5)
                except queue.Full:
                    pass
        
        # Send live data
        if active_engine.tick_data:
            try:
                current_tick = active_engine.tick_data[-1]
                
                market_data = {
                    'ltp': current_tick['ltp'],
                    'pressure': active_engine.get_order_book_pressure(),
                    'gamma': current_tick.get('gamma', 0),
                    'delta': current_tick.get('delta', 0),
                    'iv': current_tick.get('iv', 0),
                    'engine_type': engine_type
                }
                
                # Add VWAP for futures
                if engine_type == 'futures' and hasattr(active_engine, 'get_vwap'):
                    market_data['vwap'] = active_engine.get_vwap()
                
                message_queue.put({
                    'type': 'market_data',
                    'data': market_data
                }, timeout=0.5)
            except queue.Full:
                pass
        
        # Position update
        if active_engine.active_position:
            try:
                message_queue.put({
                    'type': 'position_update',
                    'data': active_engine.active_position
                }, timeout=0.5)
            except queue.Full:
                pass
    
    except Exception as e:
        print(f"Error: {e}")


if __name__ == '__main__':
    print("🚀 Upstox Enhanced Trading System")
    print("📦 Flask 3.1.2 | Tailwind 4.1 | WebSockets 15.0.1")
    print("🎯 Engines: Futures + Options")
    print("🌐 http://localhost:5000")
    
    app.run(debug=True, threaded=True, host='0.0.0.0', port=5000)