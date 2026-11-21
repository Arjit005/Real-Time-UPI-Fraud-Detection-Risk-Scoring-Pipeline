import React, { useState } from 'react';
import RiskBadge from './RiskBadge';
import { CheckCircle2, XCircle, MapPin, Smartphone, AlertTriangle, ArrowRight, BrainCircuit, ChevronDown, ChevronUp } from 'lucide-react';

export default function TransactionTable({ transactions, onReview, reviewingId }) {
  const [filter, setFilter] = useState('ALL');
  const [searchTerm, setSearchTerm] = useState('');
  const [expandedId, setExpandedId] = useState(null);

  const filtered = transactions.filter(t => {
    const matchesFilter =
      filter === 'ALL' ? true :
      filter === 'FLAGGED' ? (t.status === 'FLAGGED' || t.status === 'BLOCKED') :
      t.status === filter;

    const matchesSearch =
      t.senderUpi.toLowerCase().includes(searchTerm.toLowerCase()) ||
      t.receiverUpi.toLowerCase().includes(searchTerm.toLowerCase()) ||
      t.city.toLowerCase().includes(searchTerm.toLowerCase()) ||
      t.transactionId.toLowerCase().includes(searchTerm.toLowerCase());

    return matchesFilter && matchesSearch;
  });

  const toggleExpand = (id) => {
    setExpandedId(prev => (prev === id ? null : id));
  };

  const formatTime = (isoStr) => {
    if (!isoStr) return '—';
    try {
      const d = new Date(isoStr);
      return d.toLocaleTimeString('en-IN', { hour12: false });
    } catch {
      return isoStr;
    }
  };

  return (
    <div className="bg-[#111827] border border-gray-800 rounded-xl overflow-hidden shadow-2xl">
      {/* Table controls */}
      <div className="p-4 border-b border-gray-800 flex flex-col md:flex-row items-center justify-between gap-4">
        <div className="flex items-center gap-2">
          {['ALL', 'FLAGGED', 'APPROVED', 'PENDING'].map(tab => (
            <button
              key={tab}
              onClick={() => setFilter(tab)}
              className={`px-3 py-1.5 rounded-lg text-xs font-semibold transition-all ${
                filter === tab
                  ? 'bg-blue-600 text-white shadow-md shadow-blue-500/20'
                  : 'bg-gray-800/80 text-gray-400 hover:text-gray-200 hover:bg-gray-700'
              }`}
            >
              {tab}
            </button>
          ))}
        </div>

        <div className="w-full md:w-72">
          <input
            type="text"
            placeholder="Search VPA, city, or Txn ID..."
            value={searchTerm}
            onChange={(e) => setSearchTerm(e.target.value)}
            className="w-full bg-gray-900 border border-gray-700/80 rounded-lg px-3 py-1.5 text-xs text-gray-200 placeholder-gray-500 focus:outline-none focus:border-blue-500 transition-colors"
          />
        </div>
      </div>

      {/* Table content */}
      <div className="overflow-x-auto">
        <table className="w-full text-left text-xs text-gray-300">
          <thead className="bg-[#0B0F19] text-gray-400 uppercase tracking-wider text-[11px] font-semibold border-b border-gray-800">
            <tr>
              <th className="py-3 px-4">Time / ID</th>
              <th className="py-3 px-4">Sender & Receiver</th>
              <th className="py-3 px-4">Amount</th>
              <th className="py-3 px-4">Location & Device</th>
              <th className="py-3 px-4">Risk Evaluation</th>
              <th className="py-3 px-4">Explainable AI Breakdown</th>
              <th className="py-3 px-4 text-right">Analyst Action</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-800/60 font-normal">
            {filtered.length === 0 ? (
              <tr>
                <td colSpan="7" className="text-center py-12 text-gray-500">
                  No transactions match the selected filter or query.
                </td>
              </tr>
            ) : (
              filtered.map((t) => {
                const isFlagged = t.status === 'FLAGGED';
                const isProcessing = reviewingId === t.transactionId;
                const isExpanded = expandedId === t.transactionId;
                const b = t.scoreBreakdown;

                return (
                  <React.Fragment key={t.transactionId}>
                    <tr
                      className={`hover:bg-gray-800/40 transition-colors ${
                        isFlagged ? 'bg-red-950/10' : ''
                      }`}
                    >
                      <td className="py-3 px-4 whitespace-nowrap">
                        <div className="font-mono text-gray-300">{formatTime(t.createdAt)}</div>
                        <div className="text-[10px] text-gray-500 font-mono truncate max-w-[100px]" title={t.transactionId}>
                          {t.transactionId.substring(0, 8)}...
                        </div>
                      </td>

                      <td className="py-3 px-4">
                        <div className="font-medium text-white flex items-center gap-1.5">
                          <span className="truncate max-w-[130px] text-blue-300" title={t.senderUpi}>{t.senderUpi}</span>
                          <ArrowRight className="w-3 h-3 text-gray-500 flex-shrink-0" />
                          <span className="truncate max-w-[130px] text-gray-300" title={t.receiverUpi}>{t.receiverUpi}</span>
                        </div>
                      </td>

                      <td className="py-3 px-4 whitespace-nowrap">
                        <span className="font-bold text-white text-sm">
                          ₹{Number(t.amount).toLocaleString('en-IN', { minimumFractionDigits: 2 })}
                        </span>
                      </td>

                      <td className="py-3 px-4 whitespace-nowrap">
                        <div className="flex items-center gap-1 text-gray-300">
                          <MapPin className="w-3 h-3 text-blue-400" />
                          <span>{t.city}</span>
                        </div>
                        <div className="flex items-center gap-1 text-[11px] text-gray-500 mt-0.5">
                          <Smartphone className="w-3 h-3 text-gray-600" />
                          <span className="font-mono">{t.deviceId}</span>
                        </div>
                      </td>

                      <td className="py-3 px-4 whitespace-nowrap">
                        <RiskBadge score={t.riskScore} status={t.status} />
                      </td>

                      <td className="py-3 px-4 max-w-xs">
                        <div className="space-y-1">
                          {t.flagReason && (
                            <div className="text-[11px] text-rose-300/90 bg-rose-950/30 border border-rose-900/50 rounded p-1.5 leading-snug flex items-start gap-1">
                              <AlertTriangle className="w-3.5 h-3.5 text-rose-400 flex-shrink-0 mt-0.5" />
                              <span className="line-clamp-2">{t.flagReason}</span>
                            </div>
                          )}
                          <button
                            onClick={() => toggleExpand(t.transactionId)}
                            className="inline-flex items-center gap-1 text-[11px] text-blue-400 hover:text-blue-300 font-medium transition-colors"
                          >
                            <BrainCircuit className="w-3.5 h-3.5" />
                            <span>Explainable AI</span>
                            {isExpanded ? <ChevronUp className="w-3 h-3" /> : <ChevronDown className="w-3 h-3" />}
                          </button>
                        </div>
                      </td>

                      <td className="py-3 px-4 text-right whitespace-nowrap">
                        {isFlagged ? (
                          <div className="flex items-center justify-end gap-1.5">
                            <button
                              disabled={isProcessing}
                              onClick={() => onReview(t.transactionId, 'APPROVED', 'Analyst verified travel and baseline')}
                              title="Approve Transaction"
                              className="inline-flex items-center gap-1 bg-emerald-600 hover:bg-emerald-500 disabled:opacity-50 text-white px-2.5 py-1.5 rounded-lg text-xs font-semibold shadow-sm transition-all"
                            >
                              <CheckCircle2 className="w-3.5 h-3.5" />
                              <span>Approve</span>
                            </button>
                            <button
                              disabled={isProcessing}
                              onClick={() => onReview(t.transactionId, 'BLOCKED', 'Analyst confirmed fraudulent attack pattern')}
                              title="Confirm Fraud & Block"
                              className="inline-flex items-center gap-1 bg-red-600 hover:bg-red-500 disabled:opacity-50 text-white px-2.5 py-1.5 rounded-lg text-xs font-semibold shadow-sm transition-all"
                            >
                              <XCircle className="w-3.5 h-3.5" />
                              <span>Block</span>
                            </button>
                          </div>
                        ) : (
                          <span className="text-gray-500 text-[11px] font-mono">
                            {t.status === 'BLOCKED' ? 'BLOCKED' : 'RESOLVED'}
                          </span>
                        )}
                      </td>
                    </tr>

                    {/* Expandable Explainable AI Feature Contribution Breakdown */}
                    {isExpanded && (
                      <tr className="bg-gray-900/90 border-b border-gray-800">
                        <td colSpan="7" className="p-4">
                          <div className="bg-gray-950/80 border border-blue-900/30 rounded-lg p-3 text-xs">
                            <h4 className="font-semibold text-blue-300 flex items-center gap-1.5 mb-2">
                              <BrainCircuit className="w-4 h-4 text-blue-400" />
                              Feature Contribution Breakdown (Total Risk: {t.riskScore} / 100)
                            </h4>
                            <div className="grid grid-cols-2 md:grid-cols-4 gap-3 text-[11px]">
                              <div className="p-2 rounded bg-gray-900 border border-gray-800">
                                <span className="text-gray-400 block">Velocity Risk</span>
                                <span className="font-bold text-amber-400 text-sm">
                                  +{b?.velocityPoints ?? 0} pts
                                </span>
                                <span className="text-gray-500 block text-[10px]">
                                  {b?.velocityCount5m ?? 1} txns in 5 mins
                                </span>
                              </div>
                              <div className="p-2 rounded bg-gray-900 border border-gray-800">
                                <span className="text-gray-400 block">Geo-Location Risk</span>
                                <span className="font-bold text-rose-400 text-sm">
                                  +{b?.impossibleTravelPoints ?? 0} pts
                                </span>
                                <span className="text-gray-500 block text-[10px]">City velocity heuristic</span>
                              </div>
                              <div className="p-2 rounded bg-gray-900 border border-gray-800">
                                <span className="text-gray-400 block">User Dynamic Baseline</span>
                                <span className="font-bold text-indigo-400 text-sm">
                                  +{b?.baselineAnomalyPoints ?? 0} pts
                                </span>
                                <span className="text-gray-500 block text-[10px]">
                                  Rolling Avg: ₹{b?.userRollingAverage ?? '—'}
                                </span>
                              </div>
                              <div className="p-2 rounded bg-gray-900 border border-gray-800">
                                <span className="text-gray-400 block">IsolationForest ML</span>
                                <span className="font-bold text-emerald-400 text-sm">
                                  +{b?.mlAnomalyPoints ?? 0} pts
                                </span>
                                <span className="text-gray-500 block text-[10px]">
                                  Decision: {b?.rawModelDecisionScore ?? '—'}
                                </span>
                              </div>
                            </div>
                          </div>
                        </td>
                      </tr>
                    )}
                  </React.Fragment>
                );
              })
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
