import React, { useState, useEffect } from 'react';
import KpiCards from './components/KpiCards';
import TransactionTable from './components/TransactionTable';
import { Shield, RefreshCw, Radio, CheckCircle, AlertCircle } from 'lucide-react';

export default function App() {
  const [transactions, setTransactions] = useState([]);
  const [loading, setLoading] = useState(true);
  const [lastUpdated, setLastUpdated] = useState(null);
  const [reviewingId, setReviewingId] = useState(null);
  const [notification, setNotification] = useState(null);

  const fetchTransactions = async () => {
    try {
      const res = await fetch('/api/v1/transactions?limit=50');
      if (res.ok) {
        const data = await res.json();
        setTransactions(data);
        setLastUpdated(new Date().toLocaleTimeString('en-IN', { hour12: false }));
      }
    } catch (err) {
      console.error('Failed to poll transactions:', err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchTransactions();
    // Poll every 2 seconds
    const interval = setInterval(fetchTransactions, 2000);
    return () => clearInterval(interval);
  }, []);

  const handleReview = async (transactionId, newStatus, notes) => {
    setReviewingId(transactionId);
    try {
      const res = await fetch(`/api/v1/transactions/${transactionId}/review`, {
        method: 'PATCH',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          status: newStatus,
          reviewNotes: notes
        }),
      });

      if (res.ok) {
        setNotification({
          type: 'success',
          message: `Transaction ${transactionId.substring(0, 8)} marked as ${newStatus}`
        });
        await fetchTransactions();
      } else {
        const err = await res.text();
        setNotification({ type: 'error', message: `Review failed: ${err}` });
      }
    } catch (err) {
      setNotification({ type: 'error', message: `Network error: ${err.message}` });
    } finally {
      setReviewingId(null);
      setTimeout(() => setNotification(null), 4000);
    }
  };

  return (
    <div className="min-h-screen bg-[#0B0F19] text-gray-100 p-4 md:p-8">
      {/* Top Header */}
      <header className="flex flex-col md:flex-row md:items-center justify-between pb-6 mb-6 border-b border-gray-800 gap-4">
        <div className="flex items-center gap-3">
          <div className="p-3 bg-blue-600/20 border border-blue-500/40 rounded-xl text-blue-400">
            <Shield className="w-8 h-8" />
          </div>
          <div>
            <h1 className="text-xl md:text-2xl font-bold tracking-tight text-white flex items-center gap-2">
              UPI Real-Time Fraud Operations Center
              <span className="text-xs font-mono font-medium px-2 py-0.5 rounded bg-blue-900/60 text-blue-300 border border-blue-700/60">
                PROD v1.0
              </span>
            </h1>
            <p className="text-xs text-gray-400 mt-0.5">
              Hybrid Risk Scoring (Sliding Window Velocity + Impossible Travel + IsolationForest ML)
            </p>
          </div>
        </div>

        <div className="flex items-center gap-4">
          <div className="flex items-center gap-2 bg-gray-900/90 border border-gray-800 px-3 py-1.5 rounded-lg text-xs">
            <span className="relative flex h-2.5 w-2.5">
              <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75"></span>
              <span className="relative inline-flex rounded-full h-2.5 w-2.5 bg-emerald-500"></span>
            </span>
            <span className="text-gray-300 font-medium">Auto-polling (2s)</span>
            <span className="text-gray-500 font-mono text-[11px] ml-1">
              Updated: {lastUpdated || 'Connecting...'}
            </span>
          </div>

          <button
            onClick={fetchTransactions}
            className="p-2 rounded-lg bg-gray-800 hover:bg-gray-700 text-gray-300 hover:text-white transition-colors"
            title="Manual refresh"
          >
            <RefreshCw className="w-4 h-4" />
          </button>
        </div>
      </header>

      {/* Floating Notification */}
      {notification && (
        <div
          className={`fixed bottom-6 right-6 z-50 flex items-center gap-2 px-4 py-3 rounded-lg shadow-2xl border text-xs font-medium animate-bounce ${
            notification.type === 'success'
              ? 'bg-emerald-950 border-emerald-500/50 text-emerald-300'
              : 'bg-rose-950 border-rose-500/50 text-rose-300'
          }`}
        >
          {notification.type === 'success' ? (
            <CheckCircle className="w-4 h-4 text-emerald-400" />
          ) : (
            <AlertCircle className="w-4 h-4 text-rose-400" />
          )}
          <span>{notification.message}</span>
        </div>
      )}

      {/* KPI Cards */}
      <KpiCards transactions={transactions} />

      {/* Transaction Feed */}
      <div className="mt-6">
        <div className="flex items-center justify-between mb-3">
          <div className="flex items-center gap-2">
            <Radio className="w-4 h-4 text-rose-400 animate-pulse" />
            <h2 className="text-sm font-bold uppercase tracking-wider text-gray-300">
              Live Ingest & Risk Evaluation Stream
            </h2>
          </div>
          <span className="text-xs text-gray-500">Showing latest 50 transactions</span>
        </div>

        <TransactionTable
          transactions={transactions}
          onReview={handleReview}
          reviewingId={reviewingId}
        />
      </div>
    </div>
  );
}
