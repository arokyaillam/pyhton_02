// static/js/app.js - FIXED VERSION with Memory Leak Fix & Error Handling

// Namespace to avoid global pollution
const TradingApp = (() => {
    // Private state
    let eventSource = null;
    let currentEngine = null;
    let signalUpdateInterval = null;
    let statsPollingInterval = null;
    
    // ===================================================================
    // UTILITY FUNCTIONS
    // ===================================================================
    
    function showNotification(message, type = 'info') {
        console.log(`[${type.toUpperCase()}] ${message}`);
        
        // TODO: Replace with proper toast library
        if (type === 'error') {
            alert(message);
        }
    }
    
    function fetchWithErrorHandling(url, options = {}) {
        return fetch(url, options)
            .then(res => {
                if (!res.ok) {
                    throw new Error(`HTTP ${res.status}: ${res.statusText}`);
                }
                return res.json();
            })
            .then(data => {
                if (data.status === 'error') {
                    throw new Error(data.message || 'Unknown error');
                }
                return data;
            });
    }
    
    function getScoreColor(score) {
        if (score > 60) return 'text-green-400';
        if (score > 30) return 'text-yellow-400';
        if (score > -30) return 'text-gray-400';
        if (score > -60) return 'text-orange-400';
        return 'text-red-400';
    }
    
    function getActionColor(action) {
        if (action === 'BUY') return 'text-green-400';
        if (action === 'SELL') return 'text-red-400';
        return 'text-gray-400';
    }
    
    // ===================================================================
    // INTERVAL MANAGEMENT (FIX FOR MEMORY LEAKS)
    // ===================================================================
    
    function startStatsPolling() {
        stopStatsPolling(); // Clear any existing interval
        
        statsPollingInterval = setInterval(() => {
            if (currentEngine) {
                loadStats();
                loadTrades();
            }
        }, 5000);
    }
    
    function stopStatsPolling() {
        if (statsPollingInterval) {
            clearInterval(statsPollingInterval);
            statsPollingInterval = null;
        }
    }
    
    function startSignalPolling() {
        stopSignalPolling(); // Clear any existing interval
        
        signalUpdateInterval = setInterval(loadSignalDetails, 2000);
    }
    
    function stopSignalPolling() {
        if (signalUpdateInterval) {
            clearInterval(signalUpdateInterval);
            signalUpdateInterval = null;
        }
    }
    
    // ===================================================================
    // BUTTON MANAGEMENT
    // ===================================================================
    
    function updateButtons() {
        const futuresBtn = document.getElementById('startFuturesBtn');
        const optionsBtn = document.getElementById('startOptionsBtn');
        const stopBtn = document.getElementById('stopBtn');
        
        if (currentEngine) {
            futuresBtn.classList.add('hidden');
            optionsBtn.classList.add('hidden');
            stopBtn.classList.remove('hidden');
        } else {
            futuresBtn.classList.remove('hidden');
            optionsBtn.classList.remove('hidden');
            stopBtn.classList.add('hidden');
        }
    }
    
    function updateEngineStatus(status, color) {
        const el = document.getElementById('engineType');
        el.textContent = status;
        
        const colors = {
            'blue': 'text-blue-400',
            'purple': 'text-purple-400',
            'gray': 'text-gray-400'
        };
        
        el.className = `text-2xl font-bold ${colors[color]} ${status !== 'STOPPED' ? 'pulse' : ''}`;
    }
    
    // ===================================================================
    // TRADING CONTROLS
    // ===================================================================
    
    function startFuturesTrading() {
        fetchWithErrorHandling('/api/start-trading', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ instruments: ['NSE_FO|61755'] })
        })
        .then(data => {
            currentEngine = 'futures';
            updateButtons();
            updateEngineStatus('FUTURES', 'blue');
            connectSSE();
            showNotification('Futures Trading Started', 'success');
        })
        .catch(err => {
            console.error('Error:', err);
            showNotification(`Failed to start futures trading: ${err.message}`, 'error');
        });
    }
    
    function startOptionsTrading() {
        fetchWithErrorHandling('/api/start-options-trading', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ instruments: ['NSE_FO|NIFTY2550619900CE'] })
        })
        .then(data => {
            currentEngine = 'options';
            updateButtons();
            updateEngineStatus('OPTIONS', 'purple');
            connectSSE();
            showNotification('Options Trading Started', 'success');
        })
        .catch(err => {
            console.error('Error:', err);
            showNotification(`Failed to start options trading: ${err.message}`, 'error');
        });
    }
    
    function stopTrading() {
        fetchWithErrorHandling('/api/stop-trading', { method: 'POST' })
        .then(data => {
            currentEngine = null;
            updateButtons();
            updateEngineStatus('STOPPED', 'gray');
            
            // FIXED: Properly cleanup all intervals and connections
            if (eventSource) {
                eventSource.close();
                eventSource = null;
            }
            
            stopSignalPolling();
            stopStatsPolling();
            
            showNotification('Trading Stopped', 'info');
        })
        .catch(err => {
            console.error('Error:', err);
            showNotification(`Failed to stop trading: ${err.message}`, 'error');
        });
    }
    
    // ===================================================================
    // SSE CONNECTION
    // ===================================================================
    
    function connectSSE() {
        // Close existing connection
        if (eventSource) {
            eventSource.close();
        }
        
        eventSource = new EventSource('/stream');
        
        eventSource.onmessage = function(event) {
            try {
                const data = JSON.parse(event.data);
                
                if (data.type === 'market_data') {
                    updateLiveData(data.data);
                } else if (data.type === 'trade') {
                    handleNewTrade(data.data);
                } else if (data.type === 'position_update') {
                    updatePosition(data.data);
                } else if (data.type === 'exit') {
                    handleTradeExit(data.data);
                }
            } catch (err) {
                console.error('Error parsing SSE message:', err);
            }
        };
        
        eventSource.onerror = function(error) {
            console.error('SSE error:', error);
            
            // Auto-reconnect after 5 seconds if still trading
            if (currentEngine && eventSource) {
                eventSource.close();
                eventSource = null;
                
                setTimeout(() => {
                    if (currentEngine) {
                        console.log('Attempting SSE reconnection...');
                        connectSSE();
                    }
                }, 5000);
            }
        };
        
        // Initial data load
        loadStats();
        loadTrades();
        loadSignalDetails();
        
        // Start polling intervals
        startSignalPolling();
        startStatsPolling();
    }
    
    // ===================================================================
    // LIVE DATA UPDATES
    // ===================================================================
    
    function updateLiveData(data) {
        const ltpEl = document.getElementById('ltp');
        if (ltpEl) ltpEl.textContent = '₹' + data.ltp.toFixed(2);
        
        // VWAP (futures only)
        if (data.vwap !== undefined) {
            const vwapEl = document.getElementById('vwap');
            if (vwapEl) vwapEl.textContent = '₹' + data.vwap.toFixed(2);
        }
        
        // Order Book Pressure
        const pressure = document.getElementById('pressure');
        if (pressure) {
            pressure.textContent = data.pressure.toFixed(1);
            pressure.className = data.pressure > 0 ? 
                'font-semibold text-lg text-green-400' : 
                'font-semibold text-lg text-red-400';
        }
        
        // Greeks
        const deltaEl = document.getElementById('delta');
        if (deltaEl) deltaEl.textContent = data.delta ? data.delta.toFixed(4) : '-';
        
        const gammaEl = document.getElementById('gamma');
        if (gammaEl) gammaEl.textContent = data.gamma ? data.gamma.toFixed(4) : '-';
        
        const ivEl = document.getElementById('iv');
        if (ivEl) ivEl.textContent = data.iv ? (data.iv * 100).toFixed(2) + '%' : '-';
    }
    
    // ===================================================================
    // SIGNAL DETAILS
    // ===================================================================
    
    function loadSignalDetails() {
        if (!currentEngine) return;
        
        fetchWithErrorHandling('/api/signal-details')
        .then(data => {
            if (data.score === undefined) return;
            
            // Update signal score
            const scoreEl = document.getElementById('signalScore');
            if (scoreEl) {
                scoreEl.textContent = data.score.toFixed(0);
                scoreEl.className = 'text-3xl font-bold ' + getScoreColor(data.score);
            }
            
            // Update meter
            updateSignalMeter(data.score, data.confidence || 0, data.action || 'WAIT');
            
            // Update order book visualization
            if (data.order_book) {
                updateOrderBookVisualization(data.order_book);
            }
            
            // Update signal reasons
            if (data.reasons && data.reasons.length > 0) {
                updateSignalReasons(data.reasons);
            }
        })
        .catch(err => {
            console.error('Signal details error:', err);
        });
    }
    
    function updateSignalMeter(score, confidence, action) {
        const meterScore = document.getElementById('meterScore');
        if (meterScore) meterScore.textContent = score.toFixed(0);
        
        const meterConfidence = document.getElementById('meterConfidence');
        if (meterConfidence) meterConfidence.textContent = confidence.toFixed(0) + '%';
        
        const actionEl = document.getElementById('meterAction');
        if (actionEl) {
            actionEl.textContent = action;
            actionEl.className = 'text-xl font-bold ' + getActionColor(action);
        }
        
        // Move marker
        const marker = document.getElementById('signalMarker');
        if (marker) {
            const position = ((score + 100) / 200) * 100; // -100 to +100 → 0% to 100%
            marker.style.left = Math.max(0, Math.min(100, position)) + '%';
        }
    }
    
    function updateOrderBookVisualization(orderBook) {
        updateOrderBookBar('top5', orderBook.top5_imb || 0);
        updateOrderBookBar('mid10', orderBook.mid10_imb || 0);
        updateOrderBookBar('deep15', orderBook.deep15_imb || 0);
        
        const spreadEl = document.getElementById('spread');
        if (spreadEl) spreadEl.textContent = orderBook.spread_percent.toFixed(2) + '%';
    }
    
    function updateOrderBookBar(level, imbalance) {
        const bar = document.getElementById(level + 'Bar');
        const label = document.getElementById(level + 'Imb');
        
        if (!bar || !label) return;
        
        // Convert -1 to +1 into 0% to 100%
        const position = ((imbalance + 1) / 2) * 100;
        bar.style.width = Math.max(0, Math.min(100, position)) + '%';
        
        label.textContent = (imbalance >= 0 ? '+' : '') + imbalance.toFixed(3);
        label.className = imbalance > 0 ? 'font-semibold text-green-400' : 
                         imbalance < 0 ? 'font-semibold text-red-400' : 
                         'font-semibold';
    }
    
    function updateSignalReasons(reasons) {
        const reasonsDiv = document.getElementById('signalReasons');
        if (!reasonsDiv) return;
        
        reasonsDiv.innerHTML = reasons.map(reason => {
            const isPositive = reason.includes('✅');
            const isWarning = reason.includes('⚠️');
            const color = isPositive ? 'text-green-400' : 
                         isWarning ? 'text-yellow-400' : 
                         'text-gray-400';
            
            return `<div class="p-2 rounded bg-white/5 ${color} text-sm">${reason}</div>`;
        }).join('');
    }
    
    // ===================================================================
    // POSITION MANAGEMENT
    // ===================================================================
    
    function updatePosition(position) {
        const div = document.getElementById('currentPosition');
        if (!div) return;
        
        const isLong = position.type === 'LONG' || position.option_type === 'CE';
        
        let typeText = position.type;
        if (position.option_type) {
            typeText = `${position.option_type} (${position.type})`;
        }
        
        // FIXED: Use snake_case properties from backend
        const stopLoss = position.stop_loss || position.stopLoss || 0;
        const target = position.target || 0;
        const entry = position.entry || 0;
        
        div.innerHTML = `
            <div class="grid grid-cols-2 lg:grid-cols-4 gap-6">
                <div class="p-4 rounded-lg ${isLong ? 'bg-green-900/30 glow-green' : 'bg-red-900/30 glow-red'}">
                    <p class="text-sm text-gray-400 mb-1">Type</p>
                    <p class="text-2xl font-bold ${isLong ? 'text-green-400' : 'text-red-400'}">
                        ${typeText}
                    </p>
                </div>
                
                <div class="p-4 rounded-lg bg-white/5">
                    <p class="text-sm text-gray-400 mb-1">Entry</p>
                    <p class="text-2xl font-bold">₹${entry.toFixed(2)}</p>
                    ${position.confidence ? `<p class="text-xs text-gray-400 mt-1">Confidence: ${position.confidence}%</p>` : ''}
                </div>
                
                <div class="p-4 rounded-lg bg-white/5">
                    <p class="text-sm text-gray-400 mb-1">Stop Loss</p>
                    <p class="text-2xl font-bold text-red-400">₹${stopLoss.toFixed(2)}</p>
                    <p class="text-xs text-gray-400 mt-1">Risk: ${((Math.abs(entry - stopLoss)) / entry * 100).toFixed(1)}%</p>
                </div>
                
                <div class="p-4 rounded-lg bg-white/5">
                    <p class="text-sm text-gray-400 mb-1">Target</p>
                    <p class="text-2xl font-bold text-green-400">₹${target.toFixed(2)}</p>
                    <p class="text-xs text-gray-400 mt-1">Reward: ${((Math.abs(target - entry)) / entry * 100).toFixed(1)}%</p>
                </div>
            </div>
            
            ${position.delta ? `
            <div class="mt-4 p-4 rounded-lg bg-white/5">
                <p class="text-sm text-gray-400 mb-3">Greeks & Metrics</p>
                <div class="grid grid-cols-2 lg:grid-cols-5 gap-4 text-center">
                    <div>
                        <p class="text-xs text-gray-400">Delta</p>
                        <p class="font-semibold text-lg">${position.delta.toFixed(3)}</p>
                    </div>
                    <div>
                        <p class="text-xs text-gray-400">Gamma</p>
                        <p class="font-semibold text-lg">${position.gamma ? position.gamma.toFixed(4) : '-'}</p>
                    </div>
                    <div>
                        <p class="text-xs text-gray-400">Theta</p>
                        <p class="font-semibold text-lg text-red-400">${position.theta ? position.theta.toFixed(2) : '-'}</p>
                    </div>
                    <div>
                        <p class="text-xs text-gray-400">IV</p>
                        <p class="font-semibold text-lg">${position.iv ? (position.iv * 100).toFixed(1) + '%' : '-'}</p>
                    </div>
                    <div>
                        <p class="text-xs text-gray-400">Quantity</p>
                        <p class="font-semibold text-lg">${position.quantity || 0} lots</p>
                    </div>
                </div>
            </div>
            ` : ''}
        `;
    }
    
    function handleNewTrade(trade) {
        loadStats();
        loadTrades();
        
        const engineType = trade.engine_type || 'trade';
        const typeText = trade.option_type ? 
            `${trade.option_type} ${trade.type}` : trade.type;
        
        showNotification(
            `New ${engineType.toUpperCase()}: ${typeText} at ₹${trade.entry.toFixed(2)}`,
            'success'
        );
    }
    
    function handleTradeExit(exitData) {
        loadStats();
        loadTrades();
        
        const pnlText = exitData.pnl >= 0 ? 
            `+₹${exitData.pnl.toFixed(2)}` : 
            `-₹${Math.abs(exitData.pnl).toFixed(2)}`;
        
        showNotification(
            `Position Closed: ${pnlText} (${exitData.pnl_percent.toFixed(2)}%) - ${exitData.reason}`,
            exitData.pnl >= 0 ? 'success' : 'info'
        );
    }
    
    // ===================================================================
    // STATS & TRADES
    // ===================================================================
    
    function loadStats() {
        fetchWithErrorHandling('/api/stats')
        .then(data => {
            const pnlEl = document.getElementById('totalPnL');
            if (pnlEl) {
                pnlEl.textContent = data.total_pnl.toFixed(2) + '%';
                pnlEl.className = 'text-3xl font-bold ' + 
                    (data.total_pnl >= 0 ? 'text-green-400' : 'text-red-400');
            }
            
            const winRateEl = document.getElementById('winRate');
            if (winRateEl) winRateEl.textContent = data.win_rate.toFixed(1) + '%';
            
            const tradesEl = document.getElementById('totalTrades');
            if (tradesEl) tradesEl.textContent = data.total_trades;
        })
        .catch(err => console.error('Stats error:', err));
    }
    
    function loadTrades() {
        fetchWithErrorHandling('/api/trades?limit=10')
        .then(trades => {
            const tbody = document.getElementById('tradeHistory');
            if (!tbody) return;
            
            if (trades.length === 0) {
                tbody.innerHTML = `
                    <tr>
                        <td colspan="8" class="text-center py-12 text-gray-400">
                            No trades yet
                        </td>
                    </tr>
                `;
                return;
            }
            
            tbody.innerHTML = trades.map(trade => `
                <tr class="border-b border-white/10 hover:bg-white/5 transition-all">
                    <td class="py-3 px-4 text-sm">${new Date(trade.entry_time).toLocaleTimeString('en-IN')}</td>
                    <td class="py-3 px-4">
                        <span class="px-2 py-1 rounded text-sm ${trade.trade_type === 'LONG' ? 'bg-green-600' : 'bg-red-600'}">
                            ${trade.trade_type}
                        </span>
                    </td>
                    <td class="py-3 px-4 font-semibold">₹${trade.entry_price.toFixed(2)}</td>
                    <td class="py-3 px-4">${trade.exit_price ? '₹' + trade.exit_price.toFixed(2) : '-'}</td>
                    <td class="py-3 px-4 text-red-400 text-sm">₹${trade.stop_loss ? trade.stop_loss.toFixed(2) : '-'}</td>
                    <td class="py-3 px-4 text-green-400 text-sm">₹${trade.target ? trade.target.toFixed(2) : '-'}</td>
                    <td class="py-3 px-4">
                        <span class="${trade.pnl_percent >= 0 ? 'text-green-400' : 'text-red-400'} font-semibold">
                            ${trade.pnl_percent ? (trade.pnl_percent >= 0 ? '+' : '') + trade.pnl_percent.toFixed(2) + '%' : '-'}
                        </span>
                    </td>
                    <td class="py-3 px-4 text-sm text-gray-400">${trade.exit_reason || '-'}</td>
                </tr>
            `).join('');
        })
        .catch(err => console.error('Trades error:', err));
    }
    
    // ===================================================================
    // PUBLIC API
    // ===================================================================
    
    return {
        startFuturesTrading,
        startOptionsTrading,
        stopTrading,
        init: () => {
            console.log('✅ Trading App Initialized (Fixed Version)');
            console.log('🔧 Features: Memory Leak Fix, Error Handling, Proper Cleanup');
        }
    };
})();

// Initialize on page load
document.addEventListener('DOMContentLoaded', () => {
    TradingApp.init();
});

// Export functions to global scope for onclick handlers
window.startFuturesTrading = TradingApp.startFuturesTrading;
window.startOptionsTrading = TradingApp.startOptionsTrading;
window.stopTrading = TradingApp.stopTrading;