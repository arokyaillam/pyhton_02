# ===================================================================
# trading_engine_options.py - Nifty Options Buying Strategy
# Focus: CE/PE buying only, No selling/writing
# ===================================================================

from datetime import datetime, time as dt_time
import math


class NiftyOptionsTradingEngine:
    """
    Nifty Options Buying Strategy
    - Only BUY CE (Calls) or BUY PE (Puts)
    - No option writing/selling
    - Focus on ATM/OTM options
    - Greeks-based entry/exit
    """
    
    def __init__(self, database):
        self.db = database
        self.tick_data = []
        self.one_minute_bars = []
        self.active_position = None
        self.max_ticks = 10000
        self.max_bars = 500
        
        # Options specific settings
        self.max_loss_per_trade = 0.5  # 50% loss = exit
        self.target_profit = 1.0  # 100% profit = exit
        self.min_days_to_expiry = 2  # Don't trade if < 2 days to expiry
    
    def extract_order_book(self, bid_ask_quote):
        """30-level order book analysis."""
        if not bid_ask_quote:
            return {
                'pressure_score': 0,
                'total_bid_qty': 0,
                'total_ask_qty': 0,
                'best_bid': 0,
                'best_ask': 0,
                'spread_percent': 0
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
        
        # Weight distribution - DEEP LEVELS MATTER!
        # Top 5: Retail traders (30% weight)
        # Mid 10: Small institutions (30% weight)  
        # Deep 15: BIG INSTITUTIONS (40% weight) ← MOST IMPORTANT!
        
        top5_imb = calc_imb(top5_bid, top5_ask)
        mid10_imb = calc_imb(mid10_bid, mid10_ask)
        deep15_imb = calc_imb(deep15_bid, deep15_ask)
        
        # CORRECTED: Deep levels get HIGHEST weight (institutional orders)
        pressure_score = (top5_imb * 30) + (mid10_imb * 30) + (deep15_imb * 40)
        
        best_bid = bid_ask_quote[0].get('bidP', 0)
        best_ask = bid_ask_quote[0].get('askP', 0)
        mid_price = (best_bid + best_ask) / 2
        spread_percent = ((best_ask - best_bid) / mid_price * 100) if mid_price > 0 else 0
        
        return {
            'pressure_score': pressure_score,
            'total_bid_qty': total_bid,
            'total_ask_qty': total_ask,
            'best_bid': best_bid,
            'best_ask': best_ask,
            'spread_percent': spread_percent
        }
    
    def process_tick(self, feed_data):
        """Process incoming tick with options data."""
        try:
            feeds = feed_data.get('feeds', {})
            
            for instrument_key, feed in feeds.items():
                full_feed = feed.get('fullFeed', {}).get('marketFF', {})
                
                ltpc = full_feed.get('ltpc', {})
                market_level = full_feed.get('marketLevel', {})
                greeks = full_feed.get('optionGreeks', {})
                ohlc = full_feed.get('marketOHLC', {}).get('ohlc', [])
                
                tick = {
                    'timestamp': int(ltpc.get('ltt', 0)),
                    'ltp': float(ltpc.get('ltp', 0)),
                    'ltq': int(ltpc.get('ltq', 0)),
                    'order_book': self.extract_order_book(market_level.get('bidAskQuote', [])),
                    
                    # Options Greeks (Critical for options!)
                    'delta': float(greeks.get('delta', 0)),
                    'gamma': float(greeks.get('gamma', 0)),
                    'theta': float(greeks.get('theta', 0)),
                    'vega': float(greeks.get('vega', 0)),
                    'rho': float(greeks.get('rho', 0)),
                    
                    # Options specific
                    'oi': int(full_feed.get('oi', 0)),
                    'iv': float(full_feed.get('iv', 0)),
                    'vtt': int(full_feed.get('vtt', 0)),
                    
                    # OHLC data
                    'ohlc_1d': ohlc[0] if len(ohlc) > 0 else {},
                    'ohlc_1m': ohlc[1] if len(ohlc) > 1 else {},
                    
                    # Extract from instrument key
                    'instrument_key': instrument_key
                }
                
                self.tick_data.append(tick)
                
                if len(self.tick_data) > self.max_ticks:
                    self.tick_data.pop(0)
                
                self.create_one_minute_bar()
        
        except Exception as e:
            print(f"Error processing tick: {e}")
    
    def create_one_minute_bar(self):
        """Create 1-minute bars from ticks."""
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
                    'avg_pressure': sum(t['order_book']['pressure_score'] for t in minute_ticks) / len(minute_ticks),
                    
                    # Options Greeks averages
                    'avg_delta': sum(t['delta'] for t in minute_ticks) / len(minute_ticks),
                    'avg_gamma': sum(t['gamma'] for t in minute_ticks) / len(minute_ticks),
                    'avg_theta': sum(t['theta'] for t in minute_ticks) / len(minute_ticks),
                    'avg_vega': sum(t['vega'] for t in minute_ticks) / len(minute_ticks),
                    'avg_iv': sum(t['iv'] for t in minute_ticks) / len(minute_ticks),
                    
                    'oi': minute_ticks[-1]['oi'],
                    'oi_change': 0  # Calculate later
                }
                
                # Calculate OI change
                if len(self.one_minute_bars) > 0:
                    prev_oi = self.one_minute_bars[-1]['oi']
                    bar['oi_change'] = ((bar['oi'] - prev_oi) / prev_oi * 100) if prev_oi > 0 else 0
                
                self.one_minute_bars.append(bar)
                
                if len(self.one_minute_bars) > self.max_bars:
                    self.one_minute_bars.pop(0)
    
    def is_market_hours(self):
        """Check if current time is within market hours."""
        now = datetime.now().time()
        market_open = dt_time(9, 15)
        market_close = dt_time(15, 30)
        return market_open <= now <= market_close
    
    def get_option_type(self, instrument_key):
        """Extract option type from instrument key."""
        if 'CE' in instrument_key:
            return 'CE'
        elif 'PE' in instrument_key:
            return 'PE'
        return None
    
    def analyze_nifty_trend(self):
        """
        Analyze Nifty spot trend from recent bars.
        Returns: 'BULLISH', 'BEARISH', 'NEUTRAL'
        """
        if len(self.one_minute_bars) < 20:
            return 'NEUTRAL'
        
        recent_bars = self.one_minute_bars[-20:]
        
        # Simple trend: compare last 5 bars avg vs previous 15 bars avg
        last_5_avg = sum(b['close'] for b in recent_bars[-5:]) / 5
        prev_15_avg = sum(b['close'] for b in recent_bars[-20:-5]) / 15
        
        change_percent = ((last_5_avg - prev_15_avg) / prev_15_avg) * 100
        
        if change_percent > 0.3:
            return 'BULLISH'
        elif change_percent < -0.3:
            return 'BEARISH'
        else:
            return 'NEUTRAL'
    
    def get_options_buying_signal(self):
        """
        Main strategy for Nifty Options BUYING only.
        Returns CE or PE buy signal based on multiple factors.
        """
        if len(self.one_minute_bars) < 50:
            return {'action': 'WAIT', 'message': 'Collecting data...'}
        
        if not self.is_market_hours():
            return {'action': 'WAIT', 'message': 'Outside market hours'}
        
        current_bar = self.one_minute_bars[-1]
        previous_bar = self.one_minute_bars[-2]
        current_tick = self.tick_data[-1]
        
        # Get option type
        option_type = self.get_option_type(current_tick['instrument_key'])
        if not option_type:
            return {'action': 'WAIT', 'message': 'Not an option instrument'}
        
        # ===== OPTIONS BUYING CRITERIA =====
        
        score = 0
        reasons = []
        
        # 1. ORDER BOOK PRESSURE (30 points)
        pressure = current_tick['order_book']['pressure_score']
        if option_type == 'CE':
            if pressure > 50:
                score += 30
                reasons.append('Strong CE buying pressure')
            elif pressure > 30:
                score += 20
                reasons.append('Moderate CE buying')
        else:  # PE
            if pressure > 50:
                score += 30
                reasons.append('Strong PE buying pressure')
            elif pressure > 30:
                score += 20
                reasons.append('Moderate PE buying')
        
        # 2. DELTA ANALYSIS (20 points)
        # For buying: Look for increasing delta
        if len(self.one_minute_bars) >= 5:
            delta_trend = current_bar['avg_delta'] - self.one_minute_bars[-5]['avg_delta']
            
            if option_type == 'CE':
                if delta_trend > 0.05:  # Delta increasing (getting ITM)
                    score += 20
                    reasons.append('Delta increasing (CE gaining value)')
                elif delta_trend > 0.02:
                    score += 10
            else:  # PE
                if delta_trend < -0.05:  # Delta becoming more negative
                    score += 20
                    reasons.append('Delta increasing (PE gaining value)')
                elif delta_trend < -0.02:
                    score += 10
        
        # 3. GAMMA SPIKE (20 points)
        # High gamma = price will move fast if direction confirmed
        avg_gamma = sum(b['avg_gamma'] for b in self.one_minute_bars[-20:]) / 20
        if current_tick['gamma'] > avg_gamma * 1.5:
            score += 20
            reasons.append('Gamma spike - explosive move potential')
        elif current_tick['gamma'] > avg_gamma * 1.2:
            score += 10
            reasons.append('Elevated gamma')
        
        # 4. IMPLIED VOLATILITY (15 points)
        # Buy when IV is not too high (avoid expensive options)
        avg_iv = sum(b['avg_iv'] for b in self.one_minute_bars[-30:]) / 30
        iv_percentile = (current_tick['iv'] / avg_iv - 1) * 100
        
        if -10 < iv_percentile < 10:  # IV near normal
            score += 15
            reasons.append('IV at reasonable levels')
        elif iv_percentile < -10:  # IV low
            score += 10
            reasons.append('IV below average (cheaper options)')
        
        # 5. OPEN INTEREST CHANGE (15 points)
        # Increasing OI with price rise = fresh buying
        oi_change = current_bar['oi_change']
        price_change = ((current_bar['close'] - previous_bar['close']) / previous_bar['close']) * 100
        
        if option_type == 'CE':
            if oi_change > 5 and price_change > 0.5:
                score += 15
                reasons.append('Fresh CE long buildup')
            elif oi_change > 2 and price_change > 0.2:
                score += 8
        else:  # PE
            if oi_change > 5 and price_change > 0.5:
                score += 15
                reasons.append('Fresh PE long buildup')
            elif oi_change > 2 and price_change > 0.2:
                score += 8
        
        # 6. THETA CONSIDERATION (Penalty)
        # High theta decay = avoid buying (time is against you)
        if abs(current_tick['theta']) > 20:
            score -= 10
            reasons.append('⚠️ High theta decay')
        
        # 7. SPREAD CHECK
        # Wide spread = illiquid, avoid
        if current_tick['order_book']['spread_percent'] > 5:
            score -= 10
            reasons.append('⚠️ Wide bid-ask spread')
        
        # 8. NIFTY TREND CONFIRMATION (Bonus)
        nifty_trend = self.analyze_nifty_trend()
        if option_type == 'CE' and nifty_trend == 'BULLISH':
            score += 10
            reasons.append('Nifty trend bullish (supports CE)')
        elif option_type == 'PE' and nifty_trend == 'BEARISH':
            score += 10
            reasons.append('Nifty trend bearish (supports PE)')
        
        # ===== DECISION =====
        
        confidence = min(abs(score), 100)
        
        # Entry conditions
        if score > 60 and confidence > 60:
            # Calculate position size based on option price
            premium = current_bar['close']
            lots = self.calculate_lot_size(premium)
            
            return {
                'action': 'BUY',
                'option_type': option_type,
                'symbol': current_tick['instrument_key'],
                'entry': premium,
                'stop_loss': premium * (1 - self.max_loss_per_trade),  # 50% max loss
                'target': premium * (1 + self.target_profit),  # 100% profit
                'quantity': lots,
                'confidence': confidence,
                'score': score,
                'reasons': reasons,
                
                # Options specific data
                'delta': current_tick['delta'],
                'gamma': current_tick['gamma'],
                'iv': current_tick['iv'],
                'theta': current_tick['theta'],
                'oi_change': oi_change
            }
        
        return {
            'action': 'NO_SIGNAL',
            'score': score,
            'confidence': confidence,
            'reasons': reasons
        }
    
    def calculate_lot_size(self, premium):
        """
        Calculate lot size based on premium price.
        Lower premium = more lots (but cap at max risk)
        """
        max_risk_per_trade = 10000  # ₹10,000 max risk per trade
        
        if premium > 0:
            # Nifty lot size = 50
            max_lots = int(max_risk_per_trade / (premium * 50))
            return max(1, min(max_lots, 3))  # Min 1 lot, Max 3 lots
        
        return 1
    
    def check_exit_conditions(self, position):
        """
        Check if position should be exited.
        Options-specific exit conditions.
        """
        if not position or len(self.tick_data) == 0:
            return {'action': 'HOLD'}
        
        current_tick = self.tick_data[-1]
        current_price = current_tick['ltp']
        entry_price = position['entry']
        
        # Calculate P&L percentage
        pnl_percent = ((current_price - entry_price) / entry_price) * 100
        
        # EXIT 1: Stop Loss Hit (50% loss)
        if current_price <= position['stop_loss']:
            return {
                'action': 'EXIT',
                'reason': 'STOP_LOSS_HIT',
                'exit_price': current_price,
                'pnl_percent': pnl_percent
            }
        
        # EXIT 2: Target Hit (100% profit)
        if current_price >= position['target']:
            return {
                'action': 'EXIT',
                'reason': 'TARGET_ACHIEVED',
                'exit_price': current_price,
                'pnl_percent': pnl_percent
            }
        
        # EXIT 3: Delta reversal (option losing value)
        if position['option_type'] == 'CE':
            if current_tick['delta'] < position['delta'] * 0.7:  # Delta dropped 30%
                return {
                    'action': 'EXIT',
                    'reason': 'DELTA_REVERSAL',
                    'exit_price': current_price,
                    'pnl_percent': pnl_percent
                }
        else:  # PE
            if current_tick['delta'] > position['delta'] * 0.7:  # Delta weakening
                return {
                    'action': 'EXIT',
                    'reason': 'DELTA_REVERSAL',
                    'exit_price': current_price,
                    'pnl_percent': pnl_percent
                }
        
        # EXIT 4: Order book reversal
        pressure = current_tick['order_book']['pressure_score']
        if position['option_type'] == 'CE' and pressure < -40:
            return {
                'action': 'EXIT',
                'reason': 'ORDER_BOOK_REVERSAL',
                'exit_price': current_price,
                'pnl_percent': pnl_percent
            }
        elif position['option_type'] == 'PE' and pressure > 40:
            return {
                'action': 'EXIT',
                'reason': 'ORDER_BOOK_REVERSAL',
                'exit_price': current_price,
                'pnl_percent': pnl_percent
            }
        
        # EXIT 5: End of day (3:15 PM - square off)
        now = datetime.now().time()
        if now >= dt_time(15, 15):
            return {
                'action': 'EXIT',
                'reason': 'END_OF_DAY_SQUAREOFF',
                'exit_price': current_price,
                'pnl_percent': pnl_percent
            }
        
        # Continue holding
        return {
            'action': 'HOLD',
            'current_price': current_price,
            'pnl_percent': pnl_percent
        }
    
    def get_trading_decision(self):
        """Main entry point for trading decision."""
        # Check for exit if position exists
        if self.active_position:
            return self.check_exit_conditions(self.active_position)
        
        # Otherwise look for entry
        return self.get_options_buying_signal()
    
    def get_order_book_pressure(self):
        """Get current order book pressure."""
        if self.tick_data:
            return self.tick_data[-1]['order_book']['pressure_score']
        return 0
    
    def get_current_greeks(self):
        """Get current Greeks values."""
        if self.tick_data:
            tick = self.tick_data[-1]
            return {
                'delta': tick['delta'],
                'gamma': tick['gamma'],
                'theta': tick['theta'],
                'vega': tick['vega'],
                'iv': tick['iv']
            }
        return {}


print("✅ Nifty Options Buying Strategy Ready!")
print("📊 Focus: CE/PE buying only")
print("🎯 Entry: Score > 60, Confidence > 60%")
print("🛑 Stop Loss: 50% of premium")
print("💰 Target: 100% profit")