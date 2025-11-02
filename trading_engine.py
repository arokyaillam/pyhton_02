class TradingEngine:
    def __init__(self, database):
        self.db = database
        self.tick_data = []
        self.one_minute_bars = []
        self.active_position = None
        self.max_ticks = 10000
        self.max_bars = 500
    
    def extract_order_book(self, bid_ask_quote):
        if not bid_ask_quote:
            return {
                'pressure_score': 0,
                'total_bid_qty': 0,
                'total_ask_qty': 0,
                'best_bid': 0,
                'best_ask': 0
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
        
        pressure_score = top5_imb * 50 + mid10_imb * 30 + deep15_imb * 20
        
        return {
            'pressure_score': pressure_score,
            'total_bid_qty': total_bid,
            'total_ask_qty': total_ask,
            'best_bid': bid_ask_quote[0].get('bidP', 0),
            'best_ask': bid_ask_quote[0].get('askP', 0)
        }
    
    def process_tick(self, feed_data):
        try:
            feeds = feed_data.get('feeds', {})
            
            for instrument_key, feed in feeds.items():
                full_feed = feed.get('fullFeed', {}).get('marketFF', {})
                
                ltpc = full_feed.get('ltpc', {})
                market_level = full_feed.get('marketLevel', {})
                greeks = full_feed.get('optionGreeks', {})
                
                tick = {
                    'timestamp': int(ltpc.get('ltt', 0)),
                    'ltp': float(ltpc.get('ltp', 0)),
                    'ltq': int(ltpc.get('ltq', 0)),
                    'order_book': self.extract_order_book(market_level.get('bidAskQuote', [])),
                    'gamma': float(greeks.get('gamma', 0)),
                    'delta': float(greeks.get('delta', 0)),
                    'oi': int(full_feed.get('oi', 0)),
                    'iv': float(full_feed.get('iv', 0))
                }
                
                self.tick_data.append(tick)
                
                if len(self.tick_data) > self.max_ticks:
                    self.tick_data.pop(0)
                
                self.create_one_minute_bar()
        
        except Exception as e:
            print(f"Error processing tick: {e}")
    
    def create_one_minute_bar(self):
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
        total_value = sum(t['ltp'] * t['ltq'] for t in ticks)
        total_volume = sum(t['ltq'] for t in ticks)
        return total_value / total_volume if total_volume > 0 else ticks[0]['ltp']
    
    def calculate_session_vwap(self, bars):
        if not bars:
            return 0
        total_value = sum(b['vwap'] * b['volume'] for b in bars)
        total_volume = sum(b['volume'] for b in bars)
        return total_value / total_volume if total_volume > 0 else bars[0]['close']
    
    def calculate_atr(self, bars, period=14):
        if len(bars) < period + 1:
            return 1
        
        recent_bars = bars[-(period + 1):]
        tr_values = []
        
        for i in range(1, len(recent_bars)):
            hl = recent_bars[i]['high'] - recent_bars[i]['low']
            hc = abs(recent_bars[i]['high'] - recent_bars[i - 1]['close'])
            lc = abs(recent_bars[i]['low'] - recent_bars[i - 1]['close'])
            tr_values.append(max(hl, hc, lc))
        
        return sum(tr_values) / len(tr_values)
    
    def get_trading_decision(self):
        if len(self.one_minute_bars) < 50:
            return {'action': 'WAIT', 'message': 'Collecting data...'}
        
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
        
        if current_bar['close'] > session_vwap:
            score += 25
        else:
            score -= 25
        
        if pressure_score > 40:
            score += 35
        elif pressure_score < -40:
            score -= 35
        
        if price_change > 0.3 and volume_ratio > 1.2:
            score += 25
        elif price_change < -0.3 and volume_ratio > 1.2:
            score -= 25
        
        avg_gamma = sum(b['avg_gamma'] for b in self.one_minute_bars[-20:]) / 20
        if current_tick['gamma'] > avg_gamma * 1.5:
            score += 15
        
        confidence = min(abs(score), 100)
        
        if score > 50 and confidence > 60:
            return {
                'action': 'BUY',
                'symbol': 'NSE_FO|61755',
                'type': 'LONG',
                'entry': current_bar['close'],
                'stop_loss': current_bar['close'] - (atr * 1.5),
                'target': current_bar['close'] + (atr * 3),
                'quantity': 75,
                'confidence': confidence,
                'score': score
            }
        elif score < -50 and confidence > 60:
            return {
                'action': 'SELL',
                'symbol': 'NSE_FO|61755',
                'type': 'SHORT',
                'entry': current_bar['close'],
                'stop_loss': current_bar['close'] + (atr * 1.5),
                'target': current_bar['close'] - (atr * 3),
                'quantity': 75,
                'confidence': confidence,
                'score': score
            }
        
        return {'action': 'NO_SIGNAL', 'score': score, 'confidence': confidence}
    
    def get_order_book_pressure(self):
        if self.tick_data:
            return self.tick_data[-1]['order_book']['pressure_score']
        return 0
    
    def get_vwap(self):
        if self.one_minute_bars:
            return self.calculate_session_vwap(self.one_minute_bars[-50:])
        return 0
