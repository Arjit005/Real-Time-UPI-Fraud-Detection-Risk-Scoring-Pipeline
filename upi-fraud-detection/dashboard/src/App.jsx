import React, { useState, useEffect, useRef } from 'react';
import KpiCards from './components/KpiCards';
import TransactionTable from './components/TransactionTable';
import { Shield, RefreshCw, Radio, CheckCircle, AlertCircle, Play, Key, AlertTriangle } from 'lucide-react';

const safeGetStorage = (key) => {
  try {
    return typeof window !== 'undefined' && window.sessionStorage ? sessionStorage.getItem(key) || '' : '';
  } catch {
    return '';
  }
};

const safeSetStorage = (key, value) => {
  try {
    if (typeof window !== 'undefined' && window.sessionStorage) {
      if (value) {
        sessionStorage.setItem(key, value);
      } else {
        sessionStorage.removeItem(key);
      }
    }
  } catch {
    // Fall back to in-memory state
  }
};

export default function App() {
  const [transactions, setTransactions] = useState([]);
  const [loading, setLoading] = useState(true);
  const [lastUpdated, setLastUpdated] = useState(null);
  const [reviewingIds, setReviewingIds] = useState(new Set());
  const [notification, setNotification] = useState(null);
  const [simulating, setSimulating] = useState(false);
  const [staleError, setStaleError] = useState(null);
  const [apiKey, setApiKey] = useState(() => safeGetStorage('analyst_api_key'));
  const [showKeyPrompt, setShowKeyPrompt] = useState(false);

  const inFlightRef = useRef(false);
  const notifyTimeoutRef = useRef(null);
  const refreshQueuedRef = useRef(false);
  const abortControllerRef = useRef(null);

  useEffect(() => {
    return () => {
      if (notifyTimeoutRef.current) {
        clearTimeout(notifyTimeoutRef.current);
        notifyTimeoutRef.current = null;
      }
      if (abortControllerRef.current) {
        abortControllerRef.current.abort();
      }
    };
  }, []);

  const setAppNotification = (notif, timeoutMs = 4000) => {
    if (notifyTimeoutRef.current) {
      clearTimeout(notifyTimeoutRef.current);
      notifyTimeoutRef.current = null;
    }
    setNotification(notif);
    if (notif) {
      notifyTimeoutRef.current = setTimeout(() => {
        setNotification(null);
        notifyTimeoutRef.current = null;
      }, timeoutMs);
    }
  };

  const saveApiKey = (newKey) => {
    setApiKey(newKey);
    safeSetStorage('analyst_api_key', newKey);
    setShowKeyPrompt(false);
  };

  // Calls Vercel Serverless Function /api/transactions
  const fetchTransactions = async (forced = false) => {
    if (inFlightRef.current && !forced) {
      refreshQueuedRef.current = true;
      return;
    }
    if (forced && abortControllerRef.current) {
      abortControllerRef.current.abort();
    }
    inFlightRef.current = true;
    const controller = new AbortController();
    abortControllerRef.current = controller;

    try {
      const headers = {};
      if (apiKey) {
        headers['X-API-Key'] = apiKey;
      }
      const res = await fetch('/api/transactions?limit=50', {
        headers,
        signal: controller.signal
      });
      if (res.ok) {
        const data = await res.json();
        if (abortControllerRef.current !== controller) return;
        if (!Array.isArray(data)) {
          throw new Error('Unexpected transaction response format');
        }
        setTransactions(data);
        setLastUpdated(new Date().toLocaleTimeString('en-IN', { hour12: false }));
        setStaleError(null);
      } else {
        const errText = await res.text();
        if (abortControllerRef.current !== controller) return;
        setStaleError(`Failed to poll latest transactions (${res.status}): ${errText}`);
      }
    } catch (err) {
      if (err.name === 'AbortError' || abortControllerRef.current !== controller) {
        return; // Superseded by a newer fetch
      }
      console.error('Failed to poll transactions:', err);
      setStaleError(`Network error while polling: ${err.message}`);
    } finally {
      if (abortControllerRef.current === controller) {
        inFlightRef.current = false;
        setLoading(false);
        if (refreshQueuedRef.current) {
          refreshQueuedRef.current = false;
          fetchTransactions(true);
        }
      }
    }
  };

  useEffect(() => {
    // Cancel previous in-flight fetch on key change and trigger fresh fetch
    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
    }
    inFlightRef.current = false;
    fetchTransactions(true);

    // Poll every 2 seconds
    const interval = setInterval(() => fetchTransactions(false), 2000);
    return () => {
      clearInterval(interval);
      if (abortControllerRef.current) {
        abortControllerRef.current.abort();
      }
    };
  }, [apiKey]);

  const handleReview = async (transactionId, newStatus, notes) => {
    setReviewingIds(prev => new Set(prev).add(transactionId));
    try {
      const headers = {
        'Content-Type': 'application/json',
      };
      if (apiKey) {
        headers['X-API-Key'] = apiKey;
      }
      const res = await fetch('/api/transactions', {
        method: 'PATCH',
        headers,
        body: JSON.stringify({
          transactionId,
          status: newStatus,
          reviewNotes: notes
        }),
      });

      if (res.ok) {
        setAppNotification({
          type: 'success',
          message: `Transaction ${transactionId.substring(0, 8)} marked as ${newStatus}`
        });
        await fetchTransactions(true);
      } else {
        const err = await res.text();
        setAppNotification({ type: 'error', message: `Review failed: ${err}` });
      }
    } catch (err) {
      setAppNotification({ type: 'error', message: `Network error: ${err.message}` });
    } finally {
      setReviewingIds(prev => {
        const next = new Set(prev);
        next.delete(transactionId);
        return next;
      });
    }
  };

  // Instant Web Simulator: Allows testing right from the live UI
  const triggerSimulation = async () => {
    setSimulating(true);
    setAppNotification({ type: 'success', message: 'Simulating live UPI transactions...' }, 6000);

    const testTxns = [
      { senderUpi: 'priya.patel@okaxis', receiverUpi: 'swiggy@icici', amount: 480.0, city: 'Bengaluru', deviceId: 'pixel_9' },
      { senderUpi: 'rohit.sharma@okhdfc', receiverUpi: 'zomato@hdfcbank', amount: 1250.0, city: 'Mumbai', deviceId: 'ios_17' },
      { senderUpi: 'teleport.attacker@oksbi', receiverUpi: 'cashout_mule@paytm', amount: 95000.0, city: 'Delhi', deviceId: 'rooted_x80' }
    ];

    let succeeded = 0;
    let failed = 0;
    const errors = [];

    try {
      const headers = { 'Content-Type': 'application/json' };
      if (apiKey) {
        headers['X-API-Key'] = apiKey;
      }

      for (const t of testTxns) {
        try {
          const res = await fetch('/api/transactions', {
            method: 'POST',
            headers,
            body: JSON.stringify(t)
          });
          if (!res.ok) {
            const errText = await res.text();
            failed++;
            errors.push(`${res.status}: ${errText}`);
          } else {
            succeeded++;
          }
        } catch (err) {
          failed++;
          errors.push(err.message);
        }
      }
      await fetchTransactions(true);
      if (failed === 0) {
        setAppNotification({ type: 'success', message: `Injected ${succeeded} transactions successfully (including ₹95,000 High-Risk Outlier)!` }, 5000);
      } else {
        setAppNotification({ type: 'error', message: `Simulation finished: ${succeeded} succeeded, ${failed} failed (${errors[0] || 'Unknown error'})` }, 6000);
      }
    } catch (e) {
      setAppNotification({ type: 'error', message: 'Simulation error: ' + e.message }, 6000);
    } finally {
      setSimulating(false);
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
              <span className="text-xs font-mono font-medium px-2 py-0.5 rounded bg-emerald-900/60 text-emerald-300 border border-emerald-700/60">
                LIVE CLOUD
              </span>
            </h1>
            <p className="text-xs text-gray-400 mt-0.5">
              Hybrid Risk Scoring (Velocity + Impossible Travel + IsolationForest ML) connected to Aiven Cloud
            </p>
          </div>
        </div>

        <div className="flex items-center gap-3">
          <button
            onClick={() => setShowKeyPrompt(!showKeyPrompt)}
            className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold border transition-all ${
              apiKey
                ? 'bg-emerald-950/40 border-emerald-500/50 text-emerald-300 hover:bg-emerald-900/50'
                : 'bg-amber-950/40 border-amber-500/50 text-amber-300 hover:bg-amber-900/50'
            }`}
            title="Set Analyst API Key (stored for session only)"
          >
            <Key className="w-3.5 h-3.5" />
            <span>{apiKey ? 'API Key Set' : 'Set API Key'}</span>
          </button>

          <button
            onClick={triggerSimulation}
            disabled={simulating}
            className="flex items-center gap-1.5 bg-gradient-to-r from-blue-600 to-indigo-600 hover:from-blue-500 hover:to-indigo-500 disabled:opacity-50 text-white px-3.5 py-1.5 rounded-lg text-xs font-semibold shadow-md shadow-blue-500/20 transition-all"
            title="Inject test normal & high-risk transactions"
          >
            <Play className="w-3.5 h-3.5 fill-white" />
            <span>{simulating ? 'Simulating...' : 'Simulate Traffic'}</span>
          </button>

          <div className="flex items-center gap-2 bg-gray-900/90 border border-gray-800 px-3 py-1.5 rounded-lg text-xs">
            <span className="relative flex h-2.5 w-2.5">
              <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75"></span>
              <span className="relative inline-flex rounded-full h-2.5 w-2.5 bg-emerald-500"></span>
            </span>
            <span className="text-gray-300 font-medium">Cloud Active (2s)</span>
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

      {/* API Key Modal / Prompt */}
      {showKeyPrompt && (
        <div className="mb-6 p-4 rounded-xl bg-gray-900/90 border border-blue-500/40 shadow-xl flex flex-col sm:flex-row items-center gap-3">
          <div className="flex items-center gap-2 text-xs font-semibold text-gray-200">
            <Key className="w-4 h-4 text-blue-400" />
            <span>Analyst API Key:</span>
          </div>
          <input
            type="password"
            placeholder="Enter X-API-Key..."
            defaultValue={apiKey}
            id="analystApiKeyInput"
            className="flex-1 bg-gray-950 border border-gray-700 rounded-lg px-3 py-1.5 text-xs text-white placeholder-gray-500 focus:outline-none focus:border-blue-500"
          />
          <div className="flex gap-2">
            <button
              onClick={() => {
                const val = document.getElementById('analystApiKeyInput')?.value || '';
                saveApiKey(val);
              }}
              className="bg-blue-600 hover:bg-blue-500 text-white text-xs px-3 py-1.5 rounded-lg font-semibold"
            >
              Save Key
            </button>
            <button
              onClick={() => setShowKeyPrompt(false)}
              className="bg-gray-800 hover:bg-gray-700 text-gray-300 text-xs px-3 py-1.5 rounded-lg"
            >
              Cancel
            </button>
          </div>
        </div>
      )}

      {/* Stale Polling Error Banner */}
      {staleError && (
        <div className="mb-6 p-3 rounded-xl bg-amber-950/60 border border-amber-500/60 text-amber-200 flex items-center justify-between text-xs font-medium">
          <div className="flex items-center gap-2">
            <AlertTriangle className="w-4 h-4 text-amber-400 flex-shrink-0" />
            <span>Data may be stale: {staleError}</span>
          </div>
          <button
            onClick={fetchTransactions}
            className="underline hover:text-white ml-2"
          >
            Retry now
          </button>
        </div>
      )}

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
          <span className="text-xs text-gray-500">Showing latest 50 transactions from Aiven PostgreSQL</span>
        </div>

        <TransactionTable
          transactions={transactions}
          loading={loading}
          onReview={handleReview}
          reviewingIds={reviewingIds}
        />
      </div>
    </div>
  );
}
