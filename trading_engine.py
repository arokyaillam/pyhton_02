import logging
from datetime import datetime, time as dt_time

logger = logging.getLogger(__name__)


class TradingEngine:
    """Enhanced Futures Trading Engine with Exit Logic and Risk Management"""
    
    def __init__(self, database):
        self.db = database
        self.tick_data = []
        self.one_minute_bars = []
        self.active_position = None
        self.max_ticks = 10000
        self.max_bars = 500
        
        # Risk Management Parameters
        self.max_daily_loss = -5000  # Max daily loss in rupees
        self.max_positions = 1  # Only 1 position at a time
        self.daily_pnl = 0
        self.daily_trades = 0
        self.max_daily_trades = 10
        
        # Position sizing
        self.risk_per_trade = 1000  # Risk per trade in rupees
        self.default_quantity = 75
        
        logger.info("Futures Trading Engine initialized with risk management")
    
    def extract_order_book(self, bid_ask_quote):
        """Extract 30-level order book with validation"""
        if not bid_ask_quote or len(bid_ask_quote) == 0:
            return {
                'pressure_score': 0,
                'total_bid_qty': 0,
                'total_ask_qty': 0,
                'best_bid': 0,
                'best_ask': 0,
                'spread_percent': 0,
                'top5_imb': 0,
                'mid10_imb': 0,
                'deep15_imb': 0
            }
        
        total_bid = total_ask = 0
        top5_bid = top5_ask = 0
        mid10_bid = mid10_ask = 0
        deep15_bid = deep15_ask = 0
        
        for idx, level in enumerate(bid_ask_quote[:30]):
            bid_q = int(level.get('bidQ', 0))
            ask_q = int(level.get('askQ', 0))
            
            total_bid += bid_q
            total_ask += ask_q
            
            if idx < 5:
                top5_bid += bid_q
                top5_ask += ask_q
            elif idx < 15:
                mid10_bid += bid_q
                mid10_ask += ask_q
            else:
                deep15_bid += bid_q
                deep15_ask += ask_q
        
        def calc_imb(bid, ask):
            total = bid + ask
            return (bid - ask) / total if total > 0 else 0
        
        top5_imb = calc_imb(top5_bid, top5_ask)
        mid10_imb = calc_imb(mid10_bid, mid10_ask)
        deep15_imb = calc_imb(deep15_bid, deep15_ask)
        
        # Retail (30%), Algo (30%), Institutions (40%)
        pressure_score = (top5_imb * 30) + (mid10_imb * 30) + (deep15_imb * 40)
        
        best_bid = float(bid_ask_quote[0].get('bidP', 0))
        best_ask = float(bid_ask_quote[0].get('askP', 0))
        mid_price = (best_bid + best_ask) / 2
        spread_percent = ((best_ask - best_bid) / mid_price * 100) if mid_price > 0 else 0
        
        return {
            'pressure_score': pressure_score,
            'total_bid_qty': total_bid,
            'total_ask_qty': total_ask,
            'best_bid': best_bid,
            'best_ask': best_ask,
            'spread_percent': spread_percent,
            'top5_imb': top5_imb,
            'mid10_imb': mid10_imb,
            'deep15_imb': deep15_imb
        }
    
    def is_data_stale(self, tick_timestamp, max_age_seconds=5):
        """Check if tick data is stale"""
        current_time = datetime.now().timestamp() * 1000  # Convert to milliseconds
        age_seconds = (current_time - tick_timestamp) / 1000
        return age_seconds > max_age_seconds
    
    def is_market_hours(self):
        """Check if within market hours"""
        now = datetime.now().time()
        return dt_time(9, 15) <= now <= dt_time(15, 30)
    
    def process_tick(self, feed_data):
        """Process tick with validation"""
        try:
            feeds = feed_data.get('feeds', {})
            
            for instrument_key, feed in feeds.items():
                full_feed = feed.get('fullFeed', {}).get('marketFF', {})
                
                if not full_feed:
                    logger.warning(f"Empty feed for {instrument_key}")
                    continue
                
                ltpc = full_feed.get('ltpc', {})
                market_level = full_feed.get('marketLevel', {})
                greeks = full_feed.get('optionGreeks', {})
                
                timestamp = int(ltpc.get('ltt', 0))
                
                # Check data staleness
                if self.is_data_stale(timestamp):
                    logger.warning(f"Stale data detected: {timestamp}")
                    continue
                
                tick = {
                    'timestamp': timestamp,
                    'ltp': float(ltpc.get('ltp', 0)),
                    'ltq': int(ltpc.get('ltq', 0)),
                    'order_book': self.extract_order_book(market_level.get('bidAskQuote', [])),
                    'gamma': float(greeks.get('gamma', 0)),
                    'delta': float(greeks.get('delta', 0)),
                    'oi': int(full_feed.get('oi', 0)),
                    'iv': float(full_feed.get('iv', 0)),
                    'instrument_key': instrument_key
                }
                
                # Validate tick data
                if tick['ltp'] <= 0:
                    logger.warning(f"Invalid LTP: {tick['ltp']}")
                    continue
                
                self.tick_data.append(tick)
                
                if len(self.tick_data) > self.max_ticks:
                    self.tick_data.pop(0)
                
                self.create_one_minute_bar()
        
        except Exception as e:
            logger.error(f"Error processing tick: {e}", exc_info=True)
    
    def create_one_minute_bar(self):
        """Create 1-minute OHLC bars"""
        if len(self.tick_data) < 2:
            return
        
        current_tick = self.tick_data[-1]
        current_minute = current_tick['timestamp'] // 60000
        
        if not self.one_minute_bars or self.one_minute_bars[-1]['timestamp'] // 60000 != current_minute:
            minute_ticks = [t for t in self.tick_data if t['timestamp'] // 60000 == current_minute]
            
            if minute_ticks:
                bar = {
                    'timestamp': current_minute * 60000,
                    'open': minute_ticks[0]['ltp'],
                    'high': max(t['ltp'] for t in minute_ticks),
                    'low': min(t['ltp'] for t in minute_ticks),
                    'close': minute_ticks[-1]['ltp'],
                    'volume': sum(t['ltq'] for t in minute_ticks),
                    'vwap': self.calculate_vwap(minute_ticks),
                    'avg_pressure': sum(t['order_book']['pressure_score'] for t in minute_ticks) / len(minute_ticks),
                    'avg_gamma': sum(t['gamma'] for t in minute_ticks) / len(minute_ticks)
                }
                
                self.one_minute_bars.append(bar)
                
                if len(self.one_minute_bars) > self.max_bars:
                    self.one_minute_bars.pop(0)
    
    def calculate_vwap(self, ticks):
        """Calculate VWAP with zero division protection"""
        total_value = sum(t['ltp'] * t['ltq'] for t in ticks)
        total_volume = sum(t['ltq'] for t in ticks)
        return total_value / total_volume if total_volume > 0 else (ticks[0]['ltp'] if ticks else 0)
    
    def calculate_session_vwap(self, bars):
        """Calculate session VWAP"""
        if not bars:
            return 0
        total_value = sum(b['vwap'] * b['volume'] for b in bars)
        total_volume = sum(b['volume'] for b in bars)
        return total_value / total_volume if total_volume > 0 else bars[0]['close']
    
    def calculate_atr(self, bars, period=14):
        """Calculate Average True Range"""
        if len(bars) < period + 1:
            return 1
        
        recent_bars = bars[-(period + 1):]
        tr_values = []
        
        for i in range(1, len(recent_bars)):
            hl = recent_bars[i]['high'] - recent_bars[i]['low']
            hc = abs(recent_bars[i]['high'] - recent_bars[i - 1]['close'])
            lc = abs(recent_bars[i]['low'] - recent_bars[i - 1]['close'])
            tr_values.append(max(hl, hc, lc))
        
        return sum(tr_values) / len(tr_values) if tr_values else 1
    
    def check_risk_limits(self):
        """Check if risk limits are breached"""
        if self.daily_pnl <= self.max_daily_loss:
            logger.critical(f"Daily loss limit breached: {self.daily_pnl}")
            return False
        
        if self.daily_trades >= self.max_daily_trades:
            logger.warning(f"Daily trade limit reached: {self.daily_trades}")
            return False
        
        if self.active_position:
            logger.info("Position already active, cannot enter new trade")
            return False
        
        return True
    
    def check_exit_conditions(self):
        """NEW: Check if position should be exited"""
        if not self.active_position or len(self.tick_data) == 0:
            return {'action': 'HOLD'}
        
        current_tick = self.tick_data[-1]
        current_price = current_tick['ltp']
        entry_price = self.active_position['entry']
        position_type = self.active_position['type']
        
        # Calculate P&L
        if position_type == 'LONG':
            pnl = (current_price - entry_price) * self.active_position['quantity']
            pnl_percent = ((current_price - entry_price) / entry_price) * 100
        else:  # SHORT
            pnl = (entry_price - current_price) * self.active_position['quantity']
            pnl_percent = ((entry_price - current_price) / entry_price) * 100
        
        # Stop Loss Hit
        if position_type == 'LONG':
            if current_price <= self.active_position['stop_loss']:
                logger.info(f"Stop Loss Hit: {current_price} <= {self.active_position['stop_loss']}")
                return {
                    'action': 'EXIT',
                    'reason': 'STOP_LOSS_HIT',
                    'exit_price': current_price,
                    'pnl': pnl,
                    'pnl_percent': pnl_percent
                }
        else:  # SHORT
            if current_price >= self.active_position['stop_loss']:
                logger.info(f"Stop Loss Hit: {current_price} >= {self.active_position['stop_loss']}")
                return {
                    'action': 'EXIT',
                    'reason': 'STOP_LOSS_HIT',
                    'exit_price': current_price,
                    'pnl': pnl,
                    'pnl_percent': pnl_percent
                }
        
        # Target Hit
        if position_type == 'LONG':
            if current_price >= self.active_position['target']:
                logger.info(f"Target Hit: {current_price} >= {self.active_position['target']}")
                return {
                    'action': 'EXIT',
                    'reason': 'TARGET_ACHIEVED',
                    'exit_price': current_price,
                    'pnl': pnl,
                    'pnl_percent': pnl_percent
                }
        else:  # SHORT
            if current_price <= self.active_position['target']:
                logger.info(f"Target Hit: {current_price} <= {self.active_position['target']}")
                return {
                    'action': 'EXIT',
                    'reason': 'TARGET_ACHIEVED',
                    'exit_price': current_price,
                    'pnl': pnl,
                    'pnl_percent': pnl_percent
                }
        
        # Order Book Reversal
        pressure = current_tick['order_book']['pressure_score']
        if position_type == 'LONG' and pressure < -50:
            logger.info(f"Order book reversal for LONG: pressure={pressure}")
            return {
                'action': 'EXIT',
                'reason': 'ORDER_BOOK_REVERSAL',
                'exit_price': current_price,
                'pnl': pnl,
                'pnl_percent': pnl_percent
            }
        elif position_type == 'SHORT' and pressure > 50:
            logger.info(f"Order book reversal for SHORT: pressure={pressure}")
            return {
                'action': 'EXIT',
                'reason': 'ORDER_BOOK_REVERSAL',
                'exit_price': current_price,
                'pnl': pnl,
                'pnl_percent': pnl_percent
            }
        
        # End of Day Square-off
        if datetime.now().time() >= dt_time(15, 15):
            logger.info("End of day square-off triggered")
            return {
                'action': 'EXIT',
                'reason': 'END_OF_DAY_SQUAREOFF',
                'exit_price': current_price,
                'pnl': pnl,
                'pnl_percent': pnl_percent
            }
        
        # Trailing Stop (Move SL to breakeven after 1% profit)
        if pnl_percent > 1.0:
            if position_type == 'LONG':
                new_sl = max(self.active_position['stop_loss'], entry_price)
                if new_sl > self.active_position['stop_loss']:
                    self.active_position['stop_loss'] = new_sl
                    logger.info(f"Trailing stop updated to breakeven: {new_sl}")
            else:  # SHORT
                new_sl = min(self.active_position['stop_loss'], entry_price)
                if new_sl < self.active_position['stop_loss']:
                    self.active_position['stop_loss'] = new_sl
                    logger.info(f"Trailing stop updated to breakeven: {new_sl}")
        
        return {
            'action': 'HOLD',
            'current_price': current_price,
            'pnl': pnl,
            'pnl_percent': pnl_percent
        }
    
    def get_trading_decision(self):
        """Main trading decision with risk checks"""
        
        # NEW: Check exit conditions first if position is active
        if self.active_position:
            return self.check_exit_conditions()
        
        # Check data availability
        if len(self.one_minute_bars) < 50:
            return {
                'action': 'WAIT',
                'message': 'Collecting data...',
                'score': 0,
                'confidence': 0
            }
        
        # Check market hours
        if not self.is_market_hours():
            return {
                'action': 'WAIT',
                'message': 'Outside market hours',
                'score': 0,
                'confidence': 0
            }
        
        # NEW: Check risk limits
        if not self.check_risk_limits():
            return {
                'action': 'WAIT',
                'message': 'Risk limits breached',
                'score': 0,
                'confidence': 0
            }
        
        current_bar = self.one_minute_bars[-1]
        previous_bar = self.one_minute_bars[-2]
        current_tick = self.tick_data[-1]
        
        session_vwap = self.calculate_session_vwap(self.one_minute_bars[-50:])
        atr = self.calculate_atr(self.one_minute_bars, 14)
        pressure_score = current_tick['order_book']['pressure_score']
        
        price_change = ((current_bar['close'] - previous_bar['close']) / previous_bar['close']) * 100
        
        avg_volume = sum(b['volume'] for b in self.one_minute_bars[-20:]) / 20
        volume_ratio = current_bar['volume'] / avg_volume if avg_volume > 0 else 1
        
        score = 0
        reasons = []
        
        # VWAP Position (25 points)
        if current_bar['close'] > session_vwap:
            score += 25
            reasons.append(f"✅ Above VWAP ({session_vwap:.2f})")
        else:
            score -= 25
            reasons.append(f"❌ Below VWAP ({session_vwap:.2f})")
        
        # Order Book Pressure (35 points)
        if pressure_score > 40:
            score += 35
            reasons.append(f"✅ Strong buying pressure (+{pressure_score:.1f})")
        elif pressure_score > 20:
            score += 20
            reasons.append(f"✅ Moderate buying pressure (+{pressure_score:.1f})")
        elif pressure_score < -40:
            score -= 35
            reasons.append(f"❌ Strong selling pressure ({pressure_score:.1f})")
        elif pressure_score < -20:
            score -= 20
            reasons.append(f"❌ Moderate selling pressure ({pressure_score:.1f})")
        
        # Price Action + Volume (25 points)
        if price_change > 0.3 and volume_ratio > 1.2:
            score += 25
            reasons.append(f"✅ Bullish move +{price_change:.2f}% with volume")
        elif price_change < -0.3 and volume_ratio > 1.2:
            score -= 25
            reasons.append(f"❌ Bearish move {price_change:.2f}% with volume")
        
        # Gamma Analysis (15 points)
        avg_gamma = sum(b['avg_gamma'] for b in self.one_minute_bars[-20:]) / 20
        if current_tick['gamma'] > avg_gamma * 1.5:
            score += 15
            reasons.append(f"✅ Gamma spike ({current_tick['gamma']:.4f})")
        
        confidence = min(abs(score), 100)
        
        # Entry Logic
        if score > 60 and confidence > 65:
            logger.info(f"BUY signal: score={score}, confidence={confidence}")
            return {
                'action': 'BUY',
                'symbol': current_tick['instrument_key'],
                'type': 'LONG',
                'entry': current_bar['close'],
                'stop_loss': current_bar['close'] - (atr * 1.5),
                'target': current_bar['close'] + (atr * 3),
                'quantity': self.default_quantity,
                'confidence': confidence,
                'score': score,
                'reasons': reasons,
                'signal_details': {
                    'vwap': session_vwap,
                    'atr': atr,
                    'pressure': pressure_score,
                    'volume_ratio': volume_ratio
                }
            }
        
        elif score < -60 and confidence > 65:
            logger.info(f"SELL signal: score={score}, confidence={confidence}")
            return {
                'action': 'SELL',
                'symbol': current_tick['instrument_key'],
                'type': 'SHORT',
                'entry': current_bar['close'],
                'stop_loss': current_bar['close'] + (atr * 1.5),
                'target': current_bar['close'] - (atr * 3),
                'quantity': self.default_quantity,
                'confidence': confidence,
                'score': score,
                'reasons': reasons,
                'signal_details': {
                    'vwap': session_vwap,
                    'atr': atr,
                    'pressure': pressure_score,
                    'volume_ratio': volume_ratio
                }
            }
        
        return {
            'action': 'NO_SIGNAL',
            'score': score,
            'confidence': confidence,
            'reasons': reasons,
            'signal_details': {
                'vwap': session_vwap,
                'pressure': pressure_score
            }
        }
    
    def update_daily_pnl(self, pnl):
        """Update daily P&L tracking"""
        self.daily_pnl += pnl
        self.daily_trades += 1
        logger.info(f"Daily P&L updated: {self.daily_pnl:.2f}, Trades: {self.daily_trades}")
    
    def reset_position(self):
        """Reset active position after exit"""
        self.active_position = None
        logger.info("Position reset")
    
    def get_order_book_pressure(self):
        """Get current order book pressure"""
        if self.tick_data:
            return self.tick_data[-1]['order_book']['pressure_score']
        return 0
    
    def get_vwap(self):
        """Get current VWAP"""
        if self.one_minute_bars:
            return self.calculate_session_vwap(self.one_minute_bars[-50:])
        return 0


logger.info("✅ Enhanced Futures Trading Engine Loaded")
logger.info("🛡️  Features: Exit Logic, Risk Management, Data Validation")