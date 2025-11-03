# app.py - COMPLETE FIXED VERSION with Windows Unicode Fix

from flask import Flask, render_template, Response, jsonify, request
from flask_cors import CORS
import json
import time
import queue
import logging
import sys
import io
from threading import Thread, Lock
from dotenv import load_dotenv
import os

# WINDOWS FIX: Force UTF-8 encoding to handle emojis
if sys.platform == 'win32':
    if sys.stdout.encoding != 'utf-8':
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    if sys.stderr.encoding != 'utf-8':
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

from trading_engine import TradingEngine
from trading_engine_options import NiftyOptionsTradingEngine
from upstox_ws_client import UpstoxWebSocketClient
from database import Database

# Configure logging with UTF-8 encoding
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('trading.log', encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

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
engine_lock = Lock()  # Thread safety

ws_client = None
message_queue = queue.Queue(maxsize=1000)

# Track current trade ID for exits
current_trade_id = None


@app.route('/')
def index():
    return render_template('index.html')


@app.route('/stream')
def stream():
    """Server-Sent Events stream"""
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
            logger.info("SSE client disconnected")
    
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
        instruments = data.get('instruments', ['NSE_FO|47664','NSE_FO|47667'])
        
        with engine_lock:
            active_engine = futures_engine
            engine_type = 'futures'
        
        access_token = os.getenv('UPSTOX_ACCESS_TOKEN')
        if not access_token:
            return jsonify({
                'status': 'error',
                'message': 'UPSTOX_ACCESS_TOKEN not found in environment'
            }), 400
        
        ws_client = UpstoxWebSocketClient(
            access_token=access_token,
            instruments=instruments,
            mode='full_d30',
            on_message_callback=handle_market_data
        )
        
        ws_thread = Thread(target=ws_client.connect, daemon=True)
        ws_thread.start()
        
        logger.info("Futures trading started")
        return jsonify({
            'status': 'success',
            'message': 'Futures trading started',
            'engine': 'futures'
        })
    
    except Exception as e:
        logger.error(f"Error starting futures trading: {e}", exc_info=True)
        return jsonify({'status': 'error', 'message': str(e)}), 500


@app.route('/api/start-options-trading', methods=['POST'])
def start_options_trading():
    """Start OPTIONS trading"""
    global ws_client, active_engine, engine_type
    
    try:
        data = request.get_json()
        instruments = data.get('instruments', ['NSE_FO|47664','NSE_FO|47667'])
        
        with engine_lock:
            active_engine = options_engine
            engine_type = 'options'
        
        access_token = os.getenv('UPSTOX_ACCESS_TOKEN')
        if not access_token:
            return jsonify({
                'status': 'error',
                'message': 'UPSTOX_ACCESS_TOKEN not found in environment'
            }), 400
        
        ws_client = UpstoxWebSocketClient(
            access_token=access_token,
            instruments=instruments,
            mode='full_d30',
            on_message_callback=handle_market_data
        )
        
        ws_thread = Thread(target=ws_client.connect, daemon=True)
        ws_thread.start()
        
        logger.info("Options trading started")
        return jsonify({
            'status': 'success',
            'message': 'Options trading started',
            'engine': 'options'
        })
    
    except Exception as e:
        logger.error(f"Error starting options trading: {e}", exc_info=True)
        return jsonify({'status': 'error', 'message': str(e)}), 500


@app.route('/api/stop-trading', methods=['POST'])
def stop_trading():
    """Stop trading"""
    global ws_client, active_engine, engine_type, current_trade_id
    
    try:
        if ws_client:
            ws_client.disconnect()
            ws_client = None
        
        with engine_lock:
            active_engine = None
            engine_type = None
            current_trade_id = None
        
        logger.info("Trading stopped")
        return jsonify({'status': 'success'})
    
    except Exception as e:
        logger.error(f"Error stopping trading: {e}", exc_info=True)
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
                'action': decision.get('action', 'WAIT'),
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
                
                # Greeks (if available)
                'greeks': {},
                'engine_type': engine_type
            }
            
            # Add Greeks if options
            if hasattr(active_engine, 'get_current_greeks'):
                details['greeks'] = active_engine.get_current_greeks()
            
            return jsonify(details)
        
        return jsonify({
            'action': decision.get('action', 'WAIT'),
            'score': decision.get('score', 0),
            'message': decision.get('message', '')
        })
    
    except Exception as e:
        logger.error(f"Error getting signal details: {e}", exc_info=True)
        return jsonify({'status': 'error', 'message': str(e)}), 500


@app.route('/api/positions')
def get_positions():
    """Get active positions"""
    try:
        return jsonify(db.get_active_positions())
    except Exception as e:
        logger.error(f"Error fetching positions: {e}", exc_info=True)
        return jsonify([])


@app.route('/api/trades')
def get_trades():
    """Get trade history"""
    try:
        limit = request.args.get('limit', 50, type=int)
        return jsonify(db.get_trades(limit=limit))
    except Exception as e:
        logger.error(f"Error fetching trades: {e}", exc_info=True)
        return jsonify([])


@app.route('/api/stats')
def get_stats():
    """Get trading statistics"""
    try:
        return jsonify(db.get_trading_stats())
    except Exception as e:
        logger.error(f"Error fetching stats: {e}", exc_info=True)
        return jsonify({
            'total_trades': 0,
            'win_rate': 0,
            'total_pnl': 0
        })


@app.route('/api/health')
def health_check():
    """Health check endpoint"""
    return jsonify({
        'status': 'healthy',
        'active_engine': engine_type,
        'has_active_position': active_engine.active_position is not None if active_engine else False,
        'versions': {
            'flask': '3.1.2',
            'websockets': '15.0.1',
            'upstox_sdk': '2.18.0',
            'tailwind': '4.1.0'
        }
    })


def handle_market_data(feed_data):
    """Process market data with active engine - FIXED VERSION"""
    global active_engine, current_trade_id
    
    if not active_engine:
        return
    
    try:
        # Process tick data
        active_engine.process_tick(feed_data)
        decision = active_engine.get_trading_decision()
        
        # ENTRY LOGIC
        if decision['action'] in ['BUY', 'SELL']:
            logger.info(f"Entry signal: {decision['action']} at {decision['entry']}")
            
            # Place order
            order_result = ws_client.place_order(
                symbol=decision['symbol'],
                transaction_type=decision['action'],
                quantity=decision['quantity'],
                price=decision['entry'],
                trigger_price=decision.get('stop_loss')
            )
            
            # NEW: Check order result before proceeding
            if order_result['status'] == 'success':
                logger.info(f"Order placed successfully: {order_result['order_id']}")
                
                # Save to database
                trade_id = db.save_trade(decision, order_result, engine_type)
                
                if trade_id:
                    # NEW: Update active position in engine
                    with engine_lock:
                        active_engine.active_position = {
                            **decision,
                            'order_id': order_result['order_id'],
                            'trade_id': trade_id,
                            'entry_time': time.time()
                        }
                        current_trade_id = trade_id
                    
                    logger.info(f"Position tracked: Trade ID {trade_id}")
                    
                    # Send trade notification
                    try:
                        message_queue.put({
                            'type': 'trade',
                            'data': {
                                **decision,
                                'engine_type': engine_type,
                                'trade_id': trade_id
                            }
                        }, timeout=0.5)
                    except queue.Full:
                        logger.warning("Message queue full, trade notification dropped")
                else:
                    logger.error("Failed to save trade to database")
            else:
                logger.error(f"Order placement failed: {order_result.get('message')}")
        
        # EXIT LOGIC
        elif decision['action'] == 'EXIT':
            logger.info(f"Exit signal: {decision['reason']}")
            
            if active_engine.active_position and current_trade_id:
                # Place exit order
                exit_type = 'SELL' if active_engine.active_position['type'] == 'LONG' else 'BUY'
                
                exit_order = ws_client.place_order(
                    symbol=active_engine.active_position['symbol'],
                    transaction_type=exit_type,
                    quantity=active_engine.active_position['quantity'],
                    price=decision['exit_price']
                )
                
                if exit_order['status'] == 'success':
                    logger.info(f"Exit order placed: {exit_order['order_id']}")
                    
                    # Update database
                    db.update_trade_exit(
                        trade_id=current_trade_id,
                        exit_price=decision['exit_price'],
                        pnl=decision['pnl'],
                        pnl_percent=decision['pnl_percent'],
                        exit_reason=decision['reason']
                    )
                    
                    # Update engine daily P&L
                    active_engine.update_daily_pnl(decision['pnl'])
                    
                    # Reset position
                    with engine_lock:
                        active_engine.reset_position()
                        current_trade_id = None
                    
                    logger.info(f"Position closed: P&L={decision['pnl']:.2f}")
                    
                    # Send exit notification
                    try:
                        message_queue.put({
                            'type': 'exit',
                            'data': {
                                'reason': decision['reason'],
                                'pnl': decision['pnl'],
                                'pnl_percent': decision['pnl_percent']
                            }
                        }, timeout=0.5)
                    except queue.Full:
                        logger.warning("Message queue full, exit notification dropped")
                else:
                    logger.error(f"Exit order failed: {exit_order.get('message')}")
        
        # Send live market data
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
                pass  # Skip this update
        
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
        logger.error(f"Error handling market data: {e}", exc_info=True)


if __name__ == '__main__':
    logger.info("=" * 70)
    logger.info("🚀 Upstox Enhanced Trading System - FIXED VERSION")
    logger.info("=" * 70)
    logger.info("📦 Flask 3.1.2 | Tailwind 4.1 | WebSockets 15.0.1")
    logger.info("🎯 Engines: Futures + Options")
    logger.info("✅ Features: Exit Logic, Risk Management, Proper Logging")
    logger.info("🌐 http://localhost:5000")
    logger.info("=" * 70)
    
    app.run(debug=True, threaded=True, host='0.0.0.0', port=5000)