let eventSource = null;

function startTrading() {
    fetch('/api/start-trading', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ instruments: ['NSE_FO|61755'] })
    })
    .then(res => res.json())
    .then(data => {
        if (data.status === 'success') {
            document.getElementById('startBtn').classList.add('hidden');
            document.getElementById('stopBtn').classList.remove('hidden');
            document.getElementById('systemStatus').textContent = 'LIVE';
            
            connectSSE();
            loadStats();
            loadTrades();
        }
    })
    .catch(err => console.error('Error:', err));
}

function stopTrading() {
    fetch('/api/stop-trading', { method: 'POST' })
    .then(res => res.json())
    .then(data => {
        if (data.status === 'success') {
            document.getElementById('startBtn').classList.remove('hidden');
            document.getElementById('stopBtn').classList.add('hidden');
            document.getElementById('systemStatus').textContent = 'STOPPED';
            
            if (eventSource) {
                eventSource.close();
                eventSource = null;
            }
        }
    });
}

function connectSSE() {
    eventSource = new EventSource('/stream');
    
    eventSource.onmessage = function(event) {
        const data = JSON.parse(event.data);
        
        if (data.type === 'market_data') {
            updateLiveData(data.data);
        } else if (data.type === 'trade') {
            handleNewTrade(data.data);
        } else if (data.type === 'position_update') {
            updatePosition(data.data);
        }
    };
    
    eventSource.onerror = function(error) {
        console.error('SSE error:', error);
    };
}

function updateLiveData(data) {
    document.getElementById('ltp').textContent = '₹' + data.ltp.toFixed(2);
    document.getElementById('vwap').textContent = '₹' + data.vwap.toFixed(2);
    
    const pressure = document.getElementById('pressure');
    pressure.textContent = data.pressure.toFixed(1);
    pressure.className = data.pressure > 0 ? 
        'font-semibold text-green-400' : 'font-semibold text-red-400';
    
    document.getElementById('gamma').textContent = data.gamma.toFixed(4);
}

function handleNewTrade(trade) {
    loadStats();
    loadTrades();
    alert(`New ${trade.type} at ₹${trade.entry.toFixed(2)}`);
}

function updatePosition(position) {
    const div = document.getElementById('currentPosition');
    div.innerHTML = `
        <div class="space-y-4">
            <div class="flex justify-between">
                <span class="font-bold ${position.type === 'LONG' ? 'text-green-400' : 'text-red-400'}">
                    ${position.type}
                </span>
                <span class="text-2xl font-bold">₹${position.entry.toFixed(2)}</span>
            </div>
            <div class="grid grid-cols-2 gap-2 text-sm">
                <div class="flex justify-between">
                    <span class="text-gray-400">SL:</span>
                    <span>₹${position.stopLoss.toFixed(2)}</span>
                </div>
                <div class="flex justify-between">
                    <span class="text-gray-400">Target:</span>
                    <span>₹${position.target.toFixed(2)}</span>
                </div>
            </div>
        </div>
    `;
}

function loadStats() {
    fetch('/api/stats')
    .then(res => res.json())
    .then(data => {
        document.getElementById('totalPnL').textContent = data.total_pnl.toFixed(2) + '%';
        document.getElementById('winRate').textContent = data.win_rate.toFixed(1) + '%';
        document.getElementById('totalTrades').textContent = data.total_trades;
    });
}

function loadTrades() {
    fetch('/api/trades?limit=20')
    .then(res => res.json())
    .then(trades => {
        const tbody = document.getElementById('tradeHistory');
        
        if (trades.length === 0) {
            tbody.innerHTML = '<tr><td colspan="6" class="text-center py-12 text-gray-400">No trades yet</td></tr>';
            return;
        }
        
        tbody.innerHTML = trades.map(trade => `
            <tr class="border-b border-white/10 hover:bg-white/5">
                <td class="py-3 px-4 text-sm">${new Date(trade.entry_time).toLocaleTimeString()}</td>
                <td class="py-3 px-4">
                    <span class="px-2 py-1 rounded text-sm ${trade.trade_type === 'LONG' ? 'bg-green-600' : 'bg-red-600'}">
                        ${trade.trade_type}
                    </span>
                </td>
                <td class="py-3 px-4">₹${trade.entry_price.toFixed(2)}</td>
                <td class="py-3 px-4">₹${trade.exit_price ? trade.exit_price.toFixed(2) : '-'}</td>
                <td class="py-3 px-4">
                    <span class="${trade.pnl_percent >= 0 ? 'text-green-400' : 'text-red-400'}">
                        ${trade.pnl_percent ? (trade.pnl_percent >= 0 ? '+' : '') + trade.pnl_percent.toFixed(2) + '%' : '-'}
                    </span>
                </td>
                <td class="py-3 px-4 text-sm text-gray-400">${trade.exit_reason || '-'}</td>
            </tr>
        `).join('');
    });
}

setInterval(() => {
    if (document.getElementById('systemStatus').textContent === 'LIVE') {
        loadStats();
        loadTrades();
    }
}, 5000);