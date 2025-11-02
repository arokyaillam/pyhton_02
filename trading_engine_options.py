from datetime import datetime, time as dt_time


class NiftyOptionsTradingEngine:
    """Nifty Options Buying Strategy - FIXED VERSION"""
    
    def __init__(self, database):
        self.db = database
        self.tick_data = []
        self.one_minute_bars = []
        self.active_position = None
        self.max_ticks = 10000
        self.max_bars = 500
        
        self.max_loss_per_trade = 0.5
        self.target_profit = 1.0
        self.min_days_to_expiry = 2
    
    def extract_order_book(self, bid_ask_quote):
        """30-level order book with FIXED calc_imb"""
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
        
        # FIXED: Define calc_imb function properly
        def calc_imb(bid, ask):
            total = bid + ask
            return (bid - ask) / total if total > 0 else 0
        
        top5_imb = calc_imb(top5_bid, top5_ask)
        mid10_imb = calc_imb(mid10_bid, mid10_ask)
        deep15_imb = calc_imb(deep15_bid, deep15_ask)
        
        # CORRECTED: Deep levels get HIGHEST weight (40%)
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
            'spread_percent': spread_percent,
            # Additional details for UI
            'top5_imb': top5_imb,
            'mid10_imb': mid10_imb,
            'deep15_imb': deep15_imb
        }
    
    def process_tick(self, feed_data):
        """Process tick with full options data"""
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
                    'delta': float(greeks.get('delta', 0)),
                    'gamma': float(greeks.get('gamma', 0)),
                    'theta': float(greeks.get('theta', 0)),
                    'vega': float(greeks.get('vega', 0)),
                    'rho': float(greeks.get('rho', 0)),
                    'oi': int(full_feed.get('oi', 0)),
                    'iv': float(full_feed.get('iv', 0)),
                    'vtt': int(full_feed.get('vtt', 0)),
                    'ohlc_1d': ohlc[0] if len(ohlc) > 0 else {},
                    'ohlc_1m': ohlc[1] if len(ohlc) > 1 else {},
                    'instrument_key': instrument_key
                }
                
                self.tick_data.append(tick)
                if len(self.tick_data) > self.max_ticks:
                    self.tick_data.pop(0)
                
                self.create_one_minute_bar()
        
        except Exception as e:
            print(f"Error processing tick: {e}")
    
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
                    'avg_pressure': sum(t['order_book']['pressure_score'] for t in minute_ticks) / len(minute_ticks),
                    'avg_delta': sum(t['delta'] for t in minute_ticks) / len(minute_ticks),
                    'avg_gamma': sum(t['gamma'] for t in minute_ticks) / len(minute_ticks),
                    'avg_theta': sum(t['theta'] for t in minute_ticks) / len(minute_ticks),
                    'avg_vega': sum(t['vega'] for t in minute_ticks) / len(minute_ticks),
                    'avg_iv': sum(t['iv'] for t in minute_ticks) / len(minute_ticks),
                    'oi': minute_ticks[-1]['oi'],
                    'oi_change': 0
                }
                
                if len(self.one_minute_bars) > 0:
                    prev_oi = self.one_minute_bars[-1]['oi']
                    bar['oi_change'] = ((bar['oi'] - prev_oi) / prev_oi * 100) if prev_oi > 0 else 0
                
                self.one_minute_bars.append(bar)
                if len(self.one_minute_bars) > self.max_bars:
                    self.one_minute_bars.pop(0)
    
    def is_market_hours(self):
        """Check market hours"""
        now = datetime.now().time()
        return dt_time(9, 15) <= now <= dt_time(15, 30)
    
    def get_option_type(self, instrument_key):
        """Extract CE/PE from instrument key"""
        if 'CE' in instrument_key:
            return 'CE'
        elif 'PE' in instrument_key:
            return 'PE'
        return None
    
    def get_options_buying_signal(self):
        """Main options entry signal"""
        if len(self.one_minute_bars) < 50:
            return {'action': 'WAIT', 'message': 'Collecting data...', 'score': 0}
        
        if not self.is_market_hours():
            return {'action': 'WAIT', 'message': 'Outside market hours', 'score': 0}
        
        current_bar = self.one_minute_bars[-1]
        previous_bar = self.one_minute_bars[-2]
        current_tick = self.tick_data[-1]
        
        option_type = self.get_option_type(current_tick['instrument_key'])
        if not option_type:
            return {'action': 'WAIT', 'message': 'Not an option', 'score': 0}
        
        score = 0
        reasons = []
        signal_details = {}
        
        # 1. Order Book Pressure (30 points)
        pressure = current_tick['order_book']['pressure_score']
        signal_details['pressure'] = pressure
        if option_type == 'CE':
            if pressure > 50:
                score += 30
                reasons.append(f'✅ Strong CE buying (+{pressure:.1f})')
            elif pressure > 30:
                score += 20
                reasons.append(f'✅ Moderate CE buying (+{pressure:.1f})')
        else:
            if pressure > 50:
                score += 30
                reasons.append(f'✅ Strong PE buying (+{pressure:.1f})')
            elif pressure > 30:
                score += 20
                reasons.append(f'✅ Moderate PE buying (+{pressure:.1f})')
        
        # 2. Delta Analysis (20 points)
        if len(self.one_minute_bars) >= 5:
            delta_trend = current_bar['avg_delta'] - self.one_minute_bars[-5]['avg_delta']
            signal_details['delta_trend'] = delta_trend
            
            if option_type == 'CE':
                if delta_trend > 0.05:
                    score += 20
                    reasons.append(f'✅ Delta rising (+{delta_trend:.3f})')
                elif delta_trend > 0.02:
                    score += 10
            else:
                if delta_trend < -0.05:
                    score += 20
                    reasons.append(f'✅ Delta strengthening ({delta_trend:.3f})')
                elif delta_trend < -0.02:
                    score += 10
        
        # 3. Gamma Spike (20 points)
        avg_gamma = sum(b['avg_gamma'] for b in self.one_minute_bars[-20:]) / 20
        gamma_ratio = current_tick['gamma'] / avg_gamma if avg_gamma > 0 else 1
        signal_details['gamma_ratio'] = gamma_ratio
        
        if current_tick['gamma'] > avg_gamma * 1.5:
            score += 20
            reasons.append(f'✅ Gamma spike ({gamma_ratio:.2f}x)')
        elif current_tick['gamma'] > avg_gamma * 1.2:
            score += 10
            reasons.append(f'✅ Elevated gamma ({gamma_ratio:.2f}x)')
        
        # 4. IV Check (15 points)
        avg_iv = sum(b['avg_iv'] for b in self.one_minute_bars[-30:]) / 30
        iv_percentile = (current_tick['iv'] / avg_iv - 1) * 100 if avg_iv > 0 else 0
        signal_details['iv_percentile'] = iv_percentile
        
        if -10 < iv_percentile < 10:
            score += 15
            reasons.append(f'✅ IV normal ({iv_percentile:+.1f}%)')
        elif iv_percentile < -10:
            score += 10
            reasons.append(f'✅ IV low ({iv_percentile:+.1f}%)')
        
        # 5. OI Change (15 points)
        oi_change = current_bar['oi_change']
        price_change = ((current_bar['close'] - previous_bar['close']) / previous_bar['close']) * 100
        signal_details['oi_change'] = oi_change
        signal_details['price_change'] = price_change
        
        if oi_change > 5 and price_change > 0.5:
            score += 15
            reasons.append(f'✅ Fresh buildup (OI +{oi_change:.1f}%)')
        elif oi_change > 2 and price_change > 0.2:
            score += 8
        
        # 6. Theta Penalty
        if abs(current_tick['theta']) > 20:
            score -= 10
            reasons.append(f'⚠️ High theta decay ({current_tick["theta"]:.1f})')
        
        # 7. Spread Check
        spread = current_tick['order_book']['spread_percent']
        signal_details['spread'] = spread
        if spread > 5:
            score -= 10
            reasons.append(f'⚠️ Wide spread ({spread:.2f}%)')
        
        confidence = min(abs(score), 100)
        
        # Entry decision
        if score > 60 and confidence > 60:
            premium = current_bar['close']
            lots = self.calculate_lot_size(premium)
            
            return {
                'action': 'BUY',
                'option_type': option_type,
                'symbol': current_tick['instrument_key'],
                'entry': premium,
                'stop_loss': premium * (1 - self.max_loss_per_trade),
                'target': premium * (1 + self.target_profit),
                'quantity': lots,
                'confidence': confidence,
                'score': score,
                'reasons': reasons,
                'signal_details': signal_details,
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
            'reasons': reasons,
            'signal_details': signal_details
        }
    
    def calculate_lot_size(self, premium):
        """Calculate position size"""
        max_risk = 10000
        if premium > 0:
            max_lots = int(max_risk / (premium * 50))
            return max(1, min(max_lots, 3))
        return 1
    
    def check_exit_conditions(self, position):
        """Check exit conditions"""
        if not position or len(self.tick_data) == 0:
            return {'action': 'HOLD'}
        
        current_tick = self.tick_data[-1]
        current_price = current_tick['ltp']
        entry_price = position['entry']
        
        pnl_percent = ((current_price - entry_price) / entry_price) * 100
        
        # Stop Loss
        if current_price <= position['stop_loss']:
            return {
                'action': 'EXIT',
                'reason': 'STOP_LOSS_HIT',
                'exit_price': current_price,
                'pnl_percent': pnl_percent
            }
        
        # Target
        if current_price >= position['target']:
            return {
                'action': 'EXIT',
                'reason': 'TARGET_ACHIEVED',
                'exit_price': current_price,
                'pnl_percent': pnl_percent
            }
        
        # Delta Reversal
        if position['option_type'] == 'CE':
            if current_tick['delta'] < position['delta'] * 0.7:
                return {
                    'action': 'EXIT',
                    'reason': 'DELTA_REVERSAL',
                    'exit_price': current_price,
                    'pnl_percent': pnl_percent
                }
        else:
            if current_tick['delta'] > position['delta'] * 0.7:
                return {
                    'action': 'EXIT',
                    'reason': 'DELTA_REVERSAL',
                    'exit_price': current_price,
                    'pnl_percent': pnl_percent
                }
        
        # Order Book Reversal
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
        
        # EOD Square-off
        if datetime.now().time() >= dt_time(15, 15):
            return {
                'action': 'EXIT',
                'reason': 'END_OF_DAY_SQUAREOFF',
                'exit_price': current_price,
                'pnl_percent': pnl_percent
            }
        
        return {
            'action': 'HOLD',
            'current_price': current_price,
            'pnl_percent': pnl_percent
        }
    
    def get_trading_decision(self):
        """Main trading decision"""
        if self.active_position:
            return self.check_exit_conditions(self.active_position)
        return self.get_options_buying_signal()
    
    def get_order_book_pressure(self):
        """Get current pressure"""
        if self.tick_data:
            return self.tick_data[-1]['order_book']['pressure_score']
        return 0
    
    def get_current_greeks(self):
        """Get current Greeks"""
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


print("✅ Nifty Options Engine Ready!")
print("📊 Fixed: calc_imb function, Deep levels = 40% weight")
print("🎯 Enhanced: Signal details for UI")