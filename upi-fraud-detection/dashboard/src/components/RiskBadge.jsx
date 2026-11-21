import React from 'react';
import { ShieldCheck, ShieldAlert, ArrowUpRight, Clock, Ban } from 'lucide-react';

export default function RiskBadge({ score, status }) {
  let badgeColor = 'bg-emerald-500/10 text-emerald-400 border-emerald-500/30';
  let Icon = ShieldCheck;

  if (status === 'BLOCKED') {
    badgeColor = 'bg-rose-950/80 text-rose-300 border-rose-500/40';
    Icon = Ban;
  } else if (status === 'PENDING') {
    badgeColor = 'bg-slate-800 text-slate-300 border-slate-600/40';
    Icon = Clock;
  } else if (score >= 75 || status === 'FLAGGED') {
    badgeColor = 'bg-red-500/15 text-red-400 border-red-500/30';
    Icon = ShieldAlert;
  } else if (score >= 40) {
    badgeColor = 'bg-amber-500/15 text-amber-400 border-amber-500/30';
    Icon = ArrowUpRight;
  }

  return (
    <div className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-semibold border ${badgeColor}`}>
      <Icon className="w-3.5 h-3.5" />
      <span>{score !== undefined && score !== null ? `${score} / 100` : '—'}</span>
      <span className="opacity-60 text-[10px] uppercase font-mono tracking-wider ml-1">({status})</span>
    </div>
  );
}
