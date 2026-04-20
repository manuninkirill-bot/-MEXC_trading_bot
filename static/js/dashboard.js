class TradingDashboard {
    constructor() {
        this.lastUpdateTime = null;
        this.isUpdating = false;
        this.bindEvents();
        this.startDataUpdates();
        this.updateDashboard();
    }

    bindEvents() {
        document.getElementById('start-bot').addEventListener('click', () => this.startBot());
        document.getElementById('stop-bot').addEventListener('click', () => this.stopBot());
        document.getElementById('close-position').addEventListener('click', () => this.closePosition());
        document.getElementById('delete-trade').addEventListener('click', () => this.deleteLastTrade());
        document.getElementById('reset-balance').addEventListener('click', () => this.resetBalance());

        document.querySelectorAll('.leverage-btn').forEach(btn => {
            btn.addEventListener('click', () => this.setLeverage(parseInt(btn.dataset.leverage)));
        });
    }

    async setLeverage(leverage) {
        try {
            const response = await fetch('/api/set_leverage', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ leverage })
            });
            const data = await response.json();
            if (response.ok) {
                this.updateLeverageButtons(leverage);
                this.showNotification('success', data.message || `Плечо x${leverage} установлено`);
            } else {
                this.showNotification('error', data.error || 'Ошибка смены плеча');
            }
        } catch (error) {
            this.showNotification('error', 'Ошибка соединения');
        }
    }

    updateLeverageButtons(leverage) {
        document.querySelectorAll('.leverage-btn').forEach(btn => {
            const btnLev = parseInt(btn.dataset.leverage);
            if (btnLev === leverage) {
                btn.classList.add('active');
            } else {
                btn.classList.remove('active');
            }
        });
    }

    async startBot() {
        try {
            const response = await fetch('/api/start_bot', { method: 'POST', headers: { 'Content-Type': 'application/json' } });
            const data = await response.json();
            this.showNotification(response.ok ? 'success' : 'error', data.message || data.error || '');
        } catch (error) {
            this.showNotification('error', 'Server connection error');
        }
    }

    async stopBot() {
        try {
            const response = await fetch('/api/stop_bot', { method: 'POST', headers: { 'Content-Type': 'application/json' } });
            const data = await response.json();
            this.showNotification(response.ok ? 'success' : 'error', data.message || data.error || '');
        } catch (error) {
            this.showNotification('error', 'Server connection error');
        }
    }

    async closePosition() {
        try {
            const response = await fetch('/api/close_position', { method: 'POST', headers: { 'Content-Type': 'application/json' } });
            const data = await response.json();
            this.showNotification(response.ok ? 'success' : 'error', data.message || data.error || '');
        } catch (error) {
            this.showNotification('error', 'Server connection error');
        }
    }

    async deleteLastTrade() {
        try {
            const response = await fetch('/api/delete_last_trade', { method: 'POST', headers: { 'Content-Type': 'application/json' } });
            const data = await response.json();
            this.showNotification(response.ok ? 'success' : 'error', data.message || data.error || '');
            if (response.ok) this.updateDashboard();
        } catch (error) {
            this.showNotification('error', 'Server connection error');
        }
    }

    async resetBalance() {
        try {
            const response = await fetch('/api/reset_balance', { method: 'POST', headers: { 'Content-Type': 'application/json' } });
            const data = await response.json();
            this.showNotification(response.ok ? 'success' : 'error', data.message || data.error || '');
            if (response.ok) this.updateDashboard();
        } catch (error) {
            this.showNotification('error', 'Server connection error');
        }
    }

    async updateDashboard() {
        if (this.isUpdating) return;
        this.isUpdating = true;
        try {
            const response = await fetch('/api/status');
            if (!response.ok) return;
            const data = await response.json();

            // Bot status
            const statusBadge = document.getElementById('bot-status');
            if (data.bot_running) {
                statusBadge.textContent = 'RUNNING';
                statusBadge.className = 'badge bg-success fs-5';
            } else {
                statusBadge.textContent = 'STOPPED';
                statusBadge.className = 'badge bg-danger fs-5';
            }

            // Balance
            document.getElementById('balance').textContent = `$${parseFloat(data.balance).toFixed(2)}`;
            document.getElementById('available').textContent = `$${parseFloat(data.available).toFixed(2)}`;

            // Price
            if (data.current_price)
                document.getElementById('current-price').textContent = `$${parseFloat(data.current_price).toFixed(2)}`;

            // SAR directions
            if (data.sar_directions) this.updateSARDirections(data.sar_directions);

            // Position
            if (data.in_position && data.position) {
                document.getElementById('position-status').textContent = data.position.side.toUpperCase();
                this.updatePosition(data.position, data.current_price);
            } else {
                document.getElementById('position-status').textContent = 'No Position';
                this.clearPosition();
            }

            // Trades
            if (data.trades) this.updateTrades(data.trades);

            // Leverage buttons
            if (data.leverage) this.updateLeverageButtons(data.leverage);

            this.lastUpdateTime = new Date();
        } catch (error) {
            console.error('Dashboard update error:', error);
        } finally {
            this.isUpdating = false;
        }
    }

    updateSARDirections(directions) {
        if (!directions) return;
        const timeframes = ['1m', '5m', '30m'];
        let allMatch = true, matchDirection = null;

        timeframes.forEach(tf => {
            const element = document.getElementById(`sar-${tf}`);
            const container = document.getElementById(`sar-${tf}-container`);
            const direction = directions[tf];
            if (element && container) {
                element.className = 'badge sar-badge';
                if (direction === 'long') {
                    element.textContent = 'LONG';
                    element.classList.add('bg-success');
                    container.classList.remove('text-danger', 'text-muted');
                    container.classList.add('text-success');
                    if (matchDirection === null) matchDirection = 'long';
                    else if (matchDirection !== 'long') allMatch = false;
                } else if (direction === 'short') {
                    element.textContent = 'SHORT';
                    element.classList.add('bg-danger');
                    container.classList.remove('text-success', 'text-muted');
                    container.classList.add('text-danger');
                    if (matchDirection === null) matchDirection = 'short';
                    else if (matchDirection !== 'short') allMatch = false;
                } else {
                    element.textContent = 'N/A';
                    element.classList.add('bg-secondary');
                    container.classList.remove('text-success', 'text-danger');
                    container.classList.add('text-muted');
                    allMatch = false;
                }
            } else {
                allMatch = false;
            }
        });

        const signalEl = document.getElementById('signal-status');
        if (signalEl) {
            if (allMatch && matchDirection) {
                signalEl.textContent = matchDirection === 'long' ? 'LONG SIGNAL' : 'SHORT SIGNAL';
                signalEl.className = `badge signal-badge ${matchDirection === 'long' ? 'bg-success' : 'bg-danger'}`;
            } else {
                signalEl.textContent = 'NO SIGNAL';
                signalEl.className = 'badge bg-secondary signal-badge';
            }
        }
    }

    updatePosition(position, currentPrice) {
        document.getElementById('no-position').classList.add('d-none');
        document.getElementById('current-position').classList.remove('d-none');

        const sideBadge = document.getElementById('pos-side');
        if (sideBadge) {
            sideBadge.textContent = position.side.toUpperCase();
            sideBadge.className = position.side === 'long' ? 'badge bg-success ms-1' : 'badge bg-danger ms-1';
        }

        const colorClass = position.side === 'long' ? 'text-success ms-1' : 'text-danger ms-1';

        const entryEl = document.getElementById('pos-entry');
        if (entryEl) { entryEl.textContent = `$${parseFloat(position.entry_price).toFixed(2)}`; entryEl.className = colorClass; }

        const sizeEl = document.getElementById('pos-size');
        if (sizeEl) { sizeEl.textContent = `${parseFloat(position.size_base).toFixed(6)} ETH`; sizeEl.className = colorClass; }

        const notionalEl = document.getElementById('pos-notional');
        if (notionalEl) { notionalEl.textContent = `$${parseFloat(position.notional).toFixed(2)}`; notionalEl.className = colorClass; }

        const timeEl = document.getElementById('pos-time');
        if (timeEl && position.entry_time) {
            timeEl.textContent = new Date(position.entry_time).toLocaleTimeString();
            timeEl.className = colorClass;
        }

        const pnlEl = document.getElementById('pos-pnl');
        if (pnlEl && currentPrice) {
            const ep = parseFloat(position.entry_price);
            const sz = parseFloat(position.size_base);
            const nt = parseFloat(position.notional || ep * sz);
            let pnl = position.side === 'long' ? (currentPrice - ep) * sz : (ep - currentPrice) * sz;
            pnl -= Math.abs(nt) * 0.0003;
            pnlEl.textContent = `${pnl >= 0 ? '+' : ''}$${pnl.toFixed(2)} USDT`;
            pnlEl.className = pnl >= 0 ? 'text-success fw-bold ms-1' : 'text-danger fw-bold ms-1';
        }
    }

    clearPosition() {
        document.getElementById('no-position').classList.remove('d-none');
        document.getElementById('current-position').classList.add('d-none');
    }

    updateTrades(trades) {
        const container = document.getElementById('trades-container');
        const countEl = document.getElementById('trade-count');
        if (!container) return;

        if (!trades || trades.length === 0) {
            container.innerHTML = `<div class="text-center text-muted py-4"><i class="fas fa-clock fa-2x mb-3"></i><p>No completed trades</p></div>`;
            if (countEl) countEl.textContent = '';
            return;
        }

        if (countEl) countEl.textContent = `${trades.length} trades`;

        const recentTrades = trades.slice(0, 100);
        const html = recentTrades.map(trade => {
            const pnl = parseFloat(trade.pnl);
            const pnlClass = pnl >= 0 ? 'text-success' : 'text-danger';
            const sideClass = trade.side === 'long' ? 'bg-success' : 'bg-danger';
            const exitTime = trade.exit_time || trade.time;
            const exitDate = exitTime ? new Date(exitTime).toLocaleString() : 'N/A';
            return `
            <div class="list-group-item bg-dark border-secondary mb-2">
                <div class="d-flex justify-content-between align-items-center">
                    <div>
                        <span class="badge ${sideClass}">${trade.side.toUpperCase()}</span>
                        <span class="${pnlClass} fw-bold ms-2">${pnl >= 0 ? '+' : ''}$${pnl.toFixed(2)}</span>
                    </div>
                    <small class="text-muted">${exitDate}</small>
                </div>
                <div class="mt-1">
                    <small class="text-muted">Entry: $${trade.entry_price.toFixed(2)} → Exit: $${trade.exit_price.toFixed(2)}</small>
                </div>
            </div>`;
        }).join('');

        container.innerHTML = html;
    }

    showNotification(type, message) {
        const el = document.createElement('div');
        el.className = `alert alert-${type === 'error' ? 'danger' : 'success'} alert-dismissible fade show position-fixed`;
        el.style.cssText = 'top:20px;right:20px;z-index:9999;min-width:300px;';
        el.innerHTML = `${message}<button type="button" class="btn-close" data-bs-dismiss="alert"></button>`;
        document.body.appendChild(el);
        setTimeout(() => el.remove(), 5000);
    }

    startDataUpdates() {
        setInterval(() => this.updateDashboard(), 3000);
    }
}

document.addEventListener('DOMContentLoaded', () => new TradingDashboard());
