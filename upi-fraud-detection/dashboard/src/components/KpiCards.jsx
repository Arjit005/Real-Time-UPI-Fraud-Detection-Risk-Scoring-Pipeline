import React from 'react';
import { Activity, ShieldCheck, ShieldAlert, IndianRupee } from 'lucide-react';

export default function KpiCards({ transactions }) {
  const totalCount = transactions.length;
  const approvedCount = transactions.filter(t => t.status === 'APPROVED').length;
  const flaggedCount = transactions.filter(t => t.status === 'FLAGGED').length;
  const blockedCount = transactions.filter(t => t.status === 'BLOCKED').length;

  const totalVolume = transactions.reduce((acc, t) => acc + (Number(t.amount) || 0), 0);

  const formatCurrency = (val) => {
    return new Intl.NumberFormat('en-IN', {
      style: 'currency',
      currency: 'INR',
      maximumFractionDigits: 0
    }).format(val);
  };

  const cards = [
    {
      title: 'Total Transactions',
      value: totalCount,
      sub: `${transactions.filter(t => t.status === 'PENDING').length} pending processing`,
      icon: Activity,
      color: 'text-blue-400',
      border: 'border-blue-500/20'
    },
    {
      title: 'Approved Clean',
      value: approvedCount,
      sub: totalCount > 0 ? `${Math.round((approvedCount / totalCount) * 100)}% approval rate` : '0%',
      icon: ShieldCheck,
      color: 'text-emerald-400',
      border: 'border-emerald-500/20'
    },
    {
      title: 'Flagged / High Risk',
      value: flaggedCount + blockedCount,
      sub: `${flaggedCount} active review, ${blockedCount} blocked`,
      icon: ShieldAlert,
      color: 'text-rose-400',
      border: 'border-rose-500/20'
    },
    {
      title: 'Total Volume',
      value: formatCurrency(totalVolume),
      sub: 'Processed through gateway',
      icon: IndianRupee,
      color: 'text-amber-400',
      border: 'border-amber-500/20'
    }
  ];

  return (
    <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4 mb-6">
      {cards.map((card, i) => {
        const Icon = card.icon;
        return (
          <div
            key={i}
            className={`bg-[#111827] border ${card.border} rounded-xl p-5 shadow-lg relative overflow-hidden backdrop-blur-sm`}
          >
            <div className="flex items-center justify-between">
              <div>
                <p className="text-xs uppercase tracking-wider font-semibold text-gray-400 mb-1">
                  {card.title}
                </p>
                <h3 className="text-2xl font-bold text-white tracking-tight">{card.value}</h3>
              </div>
              <div className={`p-3 rounded-lg bg-gray-800/80 ${card.color}`}>
                <Icon className="w-5 h-5" />
              </div>
            </div>
            <p className="text-xs text-gray-400 mt-3 flex items-center gap-1">
              <span className="w-1.5 h-1.5 rounded-full bg-gray-500 inline-block"></span>
              {card.sub}
            </p>
          </div>
        );
      })}
    </div>
  );
}
