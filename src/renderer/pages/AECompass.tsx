import { useEffect, useRef, useState } from 'react';
import {
  ArrowUpRight, Bot, Calendar, ChevronRight, CheckCircle2, Clock3,
  Command, Flame, Gauge, Moon, Search, Sparkles, Sun, Target,
  TrendingUp, AlertTriangle, Users, LogOut,
} from 'lucide-react';
import { api, MetricsSummary, ForecastSummary, GongSignal, PipelineDeal } from '../data/api';

type Tone = 'green' | 'violet' | 'amber' | 'rose';
type CompassView = 'My day' | 'My deals' | 'Progress';
type Period = 'This Q' | 'Next Q' | 'Full year';
const CircleCheck = CheckCircle2;


const periodCopy: Record<Period, { eyebrow: string; title: string; subtitle: string; focus: string }> = {
  'This Q': { eyebrow: 'Tuesday, August 26 · Your cockpit', title: 'Hello', subtitle: 'Here’s the shortest path to a strong week.', focus: 'Close the loop on this quarter’s active deals.' },
  'Next Q': { eyebrow: 'Next quarter · Build the runway', title: 'Let’s make next quarter easier', subtitle: 'Your next-quarter view is about enough quality pipe—not busywork.', focus: 'Create and qualify pipe before next quarter needs it.' },
  'Full year': { eyebrow: 'FY27 · The bigger picture', title: 'Keep the year moving', subtitle: 'A simple annual view of where momentum is building and where to place your bets.', focus: 'Protect the year by balancing signed revenue, AI, and New Business.' },
};
const progressSnapshots: Record<Period, Array<[string, string, string, number, string]>> = {
  'This Q': [],
  'Next Q': [],
  'Full year': [],
};
type S1Opportunity = { name: string; amount: string; rating: string; categories: string[]; reason: string; tone: Tone; crmOpportunityId: string };

const toneClasses: Record<Tone, { card: string; dot: string; text: string }> = {
  green: { card: 'bg-[#effcf5] border-[#c9f1dc]', dot: 'bg-[#18b86a]', text: 'text-[#087344]' },
  violet: { card: 'bg-[#f5f1ff] border-[#ddd0ff]', dot: 'bg-[#8055e8]', text: 'text-[#6033bd]' },
  amber: { card: 'bg-[#fff8e7] border-[#f4df9d]', dot: 'bg-[#f2a400]', text: 'text-[#9c6500]' },
  rose: { card: 'bg-[#fff1f1] border-[#f5cccc]', dot: 'bg-[#e45b63]', text: 'text-[#b53643]' },
};
const currentWeekPace = 20;
function paceTone(percent: number): Tone {
  if (percent >= currentWeekPace) return 'green';
  if (percent >= currentWeekPace - 4) return 'amber';
  return 'rose';
}
const overallTone = paceTone(72);
const progressTargets: Record<string, number> = { Quota: 195000, Forecast: 195000, AI: 88000, 'New Business': 49000, Pipeline: 460000 };
const compactMoney = (value: number) => value >= 1000 ? `$${Math.round(value / 1000)}K` : `$${value}`;
const signedByPeriod: Record<Period, number> = { 'This Q': 2000, 'Next Q': 0, 'Full year': 31000 };
const CURRENT_QUARTER = 'FY2027Q3';
const NEXT_QUARTER = 'FY2027Q4';
const FISCAL_QUARTERS = ['FY2027Q1', 'FY2027Q2', 'FY2027Q3', 'FY2027Q4'];
type LiveCompassData = { forecast: ForecastSummary | null; metrics: MetricsSummary | null; pipeline: PipelineDeal[]; gongSignals?: GongSignal[]; gtmiPipeline?: { total: number; ai: number; nb: number; deal_count: number; ai_deal_count: number; nb_deal_count: number; quarter: string } | null };
type FiscalYearQuarterData = { forecast: ForecastSummary; metrics: MetricsSummary };
type DealCard = { name: string; account: string; amount: string; stage: string; health: string; tone: Tone; note: string; action: string; quarter: Period; crmOpportunityId?: string };
const salesforceOpportunityUrl = (id?: string) => id ? `https://zendesk.my.salesforce.com/lightning/r/Opportunity/${encodeURIComponent(id)}/view` : null;
const salesforceSearchUrl = (term: string) => `https://zendesk.my.salesforce.com/_ui/search/ui?searchTerm=${encodeURIComponent(term)}`;
// Precise CRM record link when a matching live pipeline row is found, else a SFDC search by name.
const cockpitCrmUrl = (pipeline: PipelineDeal[], name: string) => {
  const hit = pipeline.find((row) => (row.opportunity_name || '').includes(name) || (row.crm_account_name || '').includes(name));
  return salesforceOpportunityUrl(hit?.crm_opportunity_id) || salesforceSearchUrl(name);
};

type CockpitRow = { name: string; meta: string; reason: string; action: string; crmOpportunityId: string };
const stageNumber = (row: PipelineDeal) => Number((row.stage_name || '').match(/\d+/)?.[0] || 0);
const rowAmount = (row: PipelineDeal) => compactMoney(Number(row.product_booking_arr_usd || row.product_arr_usd || 0));
const s1Analysis = (signal?: GongSignal) => {
  if (!signal) return 'No verified Gong call summary or next step is available for this opportunity.';
  const parts = [
    signal.last_call_brief ? `Gong summary: ${signal.last_call_brief}` : '',
    signal.last_call_key_points ? `Key points: ${signal.last_call_key_points}` : '',
    signal.last_call_next_steps ? `Next step: ${signal.last_call_next_steps}` : '',
  ].filter(Boolean);
  return parts.join(' · ') || 'Gong call found, but no summary or next step was captured.';
};
const daysToClose = (row: PipelineDeal) => row.closedate ? Math.ceil((new Date(`${row.closedate}T00:00:00`).getTime() - Date.now()) / 86400000) : null;
const isBlank = (value: unknown) => value === null || value === undefined || String(value).trim() === '';
const isMissingValue = (value: unknown) => isBlank(value) || ['missing', 'false', 'no', 'none', 'n/a'].includes(String(value).trim().toLowerCase());

function liveCockpitRows(check: string, pipeline: PipelineDeal[]): CockpitRow[] {
  const openRows = pipeline.filter((row) => stageNumber(row) >= 2 && stageNumber(row) <= 6);
  if (check === 'Close-plan watch') {
    return openRows.filter((row) => { const days = daysToClose(row); const earlyCloseRisk = days !== null && days >= 0 && days <= 10 && stageNumber(row) < 4; const pastDue = days !== null && days < 0; const pullForward = days !== null && days > 10 && days <= 45; return earlyCloseRisk || pastDue || pullForward; }).map((row) => {
      const days = daysToClose(row);
      const earlyCloseRisk = days !== null && days >= 0 && days <= 10 && stageNumber(row) < 4;
      const reason = earlyCloseRisk ? `The deal closes in ${days} day${days === 1 ? '' : 's'} but is still below Stage 04.` : `The deal closes in ${days} days, so an earlier close-plan conversation could protect the date.`;
      return { name: row.opportunity_name || row.crm_account_name, meta: `${rowAmount(row)} · Stage ${String(stageNumber(row)).padStart(2, '0')}`, reason, action: earlyCloseRisk ? 'Advance qualification' : 'Review close plan', crmOpportunityId: row.crm_opportunity_id };
    });
  }
  if (check === 'Deal hygiene') {
    const quoteData = pipeline.some((row) => !isBlank(row.quote_status));
    return openRows.filter((row) => {
      const days = daysToClose(row);
      const stage = stageNumber(row);
      const earlyStageClose = days !== null && days >= 0 && days <= 10 && stage <= 4;
      const lateStageNoQuote = quoteData && stage >= 4 && stage <= 6 && isMissingValue(row.quote_status);
      const pastDue = days !== null && days < 0;
      return earlyStageClose || lateStageNoQuote || pastDue;
    }).map((row) => {
      const days = daysToClose(row);
      const stage = stageNumber(row);
      const earlyStageClose = days !== null && days >= 0 && days <= 10 && stage <= 4;
      const lateStageNoQuote = quoteData && stage >= 4 && stage <= 6 && isMissingValue(row.quote_status);
      const pastDue = days !== null && days < 0;
      const reason = pastDue
        ? `The close date passed ${Math.abs(days || 0)} day${Math.abs(days || 0) === 1 ? '' : 's'} ago; check whether the date still reflects reality.`
        : earlyStageClose
          ? `This Stage ${String(stage).padStart(2, '0')} opportunity closes in ${days} day${days === 1 ? '' : 's'} and is still early in the cycle.`
          : 'This late-stage opportunity has no quote recorded.';
      return { name: row.opportunity_name || row.crm_account_name, meta: `${rowAmount(row)} · Stage ${String(stage).padStart(2, '0')}`, reason, action: pastDue ? 'Check close date' : earlyStageClose ? 'Advance qualification' : 'Add quote coverage', crmOpportunityId: row.crm_opportunity_id };
    });
  }
  if (check === 'Buying group readiness') {
    const hasBuyingGroupData = pipeline.some((row) => Object.prototype.hasOwnProperty.call(row, 'zendesk_executive_connect'));
    if (!hasBuyingGroupData) return [];
    return openRows.filter((row) => {
      const totalArr = Number(row.product_arr_usd || 0);
      return totalArr >= 100000 && isBlank(row.zendesk_executive_connect);
    }).map((row) => {
      const reason = 'This $100K+ opportunity has a blank Zendesk Executive Connect field.';
      return {
      name: row.opportunity_name || row.crm_account_name,
      meta: `${compactMoney(Number(row.product_arr_usd || 0))} · Stage ${String(stageNumber(row)).padStart(2, '0')}`,
      reason,
      action: 'Add executive connection',
      crmOpportunityId: row.crm_opportunity_id,
      };
    });
  }
  return [];
}

function liveDealCards(rows: PipelineDeal[]): DealCard[] {
  return rows.filter((row) => {
    const stage = Number((row.stage_name || '').match(/^\d+/)?.[0] || 0);
    return stage >= 2 && stage <= 6;
  }).map((row, index) => {
    const stageNumber = Number((row.stage_name || '').match(/^\d+/)?.[0] || 0);
    const daysToClose = row.closedate ? Math.ceil((new Date(`${row.closedate}T00:00:00`).getTime() - Date.now()) / 86400000) : null;
    const tone: Tone = daysToClose !== null && daysToClose <= 10 ? 'rose' : stageNumber >= 5 ? 'green' : 'amber';
    const action = stageNumber >= 6 ? 'Confirm the close path' : stageNumber === 5 ? 'Lock the decision step' : 'Advance the value conversation';
    const timing = daysToClose === null ? `Stage ${String(stageNumber).padStart(2, '0')} · close date unavailable` : `Stage ${String(stageNumber).padStart(2, '0')} · closes in ${Math.max(daysToClose, 0)} days`;
    return {
      crmOpportunityId: row.crm_opportunity_id,
      name: row.opportunity_name || row.crm_account_name || `Opportunity ${index + 1}`,
      account: `${row.opportunity_type || 'Opportunity'} · ${row.crm_account_name || 'Account'}`,
      amount: compactMoney(row.product_arr_usd || row.product_booking_arr_usd || 0),
      stage: timing,
      health: tone === 'rose' ? 'At risk' : tone === 'green' ? 'Strong' : 'Watch',
      tone,
      note: `${timing}. Use the next customer step to move this deal forward.`,
      action,
      quarter: (row.close_fiscal_quarter === NEXT_QUARTER ? 'Next Q' : 'This Q') as Period,
    };
  });
}
function CockpitDetail({ check, onClose, pipeline }: { check: string; onClose: () => void; pipeline: PipelineDeal[] }) {
  const dealsForCheck = liveCockpitRows(check, pipeline);
  const buyingGroupData = pipeline.some((row) => !isBlank(row.has_executive_relationships) || !isBlank(row.zendesk_executive_connect) || !isBlank(row.economic_buyer_status) || !isBlank(row.executive_sponsor_status));
  const emptyMessage = check === 'Buying group readiness' && !buyingGroupData
    ? 'Zendesk Executive Connect is not present in the current Salesforce feed yet, so Compass cannot verify this check.'
    : 'No verified opportunities match this check in the current Salesforce data.';
  return <div className="fixed inset-0 z-50 flex items-center justify-center bg-[#17221c]/30 p-6 backdrop-blur-sm" onClick={onClose}><section className="max-h-[80vh] w-full max-w-[860px] overflow-y-auto rounded-2xl border border-[#cddbc7] bg-[#fbfdf8] p-5 shadow-2xl dark:border-[#344635] dark:bg-[#172018]" onClick={(event) => event.stopPropagation()}><div className="flex items-start justify-between gap-3"><div><p className="text-[10px] font-bold uppercase tracking-[0.14em] text-[#4b7853]">Cockpit detail</p><h3 className="mt-1 text-sm font-bold">{check}</h3><p className="mt-1 text-xs text-[#879289]">{dealsForCheck.length} verified matching opportunit{dealsForCheck.length === 1 ? 'y' : 'ies'} · live data</p></div><button onClick={onClose} className="rounded-lg px-2 py-1 text-[10px] font-bold text-[#78867b] hover:bg-white dark:hover:bg-[#263126]">Close</button></div>{dealsForCheck.length ? <div className="mt-4 overflow-x-auto rounded-xl border border-[#e5ebe2] bg-white dark:border-[#344635] dark:bg-[#1a231c]"><table className="w-full min-w-[720px] text-left"><thead><tr className="border-b border-[#eef1ed] text-[9px] font-bold uppercase tracking-[0.14em] text-[#9aa59c] dark:border-[#344635]"><th className="px-4 py-3">Opportunity</th><th className="px-4 py-3">Stage</th><th className="px-4 py-3">ARR</th><th className="px-4 py-3">Why flagged</th><th className="px-4 py-3">Action</th></tr></thead><tbody>{dealsForCheck.map((item) => { const [arr, stage] = item.meta.split(" · "); return <tr key={item.crmOpportunityId} className="border-b border-[#f0f2ef] last:border-0 dark:border-[#29352b]"><td className="px-4 py-4 text-xs font-bold">{item.name}</td><td className="px-4 py-4 text-[10px] text-[#6e7b72]">{stage}</td><td className="px-4 py-4 text-xs font-bold">{arr}</td><td className="px-4 py-4 text-[10px] leading-relaxed text-[#78847b] dark:text-[#aebcaf]">{item.reason}</td><td className="px-4 py-4"><div className="flex items-center gap-3"><span className="text-[10px] font-bold text-[#4b7853]">{item.action}</span><a href={salesforceOpportunityUrl(item.crmOpportunityId) || salesforceSearchUrl(item.name)} target="_blank" rel="noreferrer" className="whitespace-nowrap rounded-lg bg-[#203b29] px-3 py-2 text-[10px] font-bold text-[#d9f579] hover:bg-[#31553b]">Open in CRM ↗</a></div></td></tr>})}</tbody></table></div> : <div className="mt-4 rounded-xl border border-dashed border-[#cddbc7] bg-white/70 p-5 text-xs leading-relaxed text-[#78847b] dark:border-[#344635] dark:bg-white/5">{emptyMessage}</div>}</section></div>;
}
function DealsNeedingYou({ deals: liveDeals }: { deals: DealCard[] }) {
  const items = liveDeals.slice(0, 3);
  return <section className="mt-5 rounded-2xl border border-[#f5cccc] bg-[#fff7f7] p-5 dark:border-[#5a3035] dark:bg-[#261b1d]"><div className="flex items-start justify-between gap-3"><div><div className="flex items-center gap-2"><AlertTriangle className="h-4 w-4 text-[#e45b63]" /><h2 className="text-sm font-bold">Deals needing you</h2></div><p className="mt-1 text-xs text-[#9b7376] dark:text-[#d8b9bb]">A short, specific list of deals where one action can change the outcome.</p></div><span className="rounded-full bg-white/80 px-2.5 py-1 text-[10px] font-bold text-[#b53643] dark:bg-white/10">{items.length} priorities</span></div><div className="mt-4 divide-y divide-[#f2dede] rounded-xl border border-[#f2dede] bg-white dark:divide-[#5a3035] dark:border-[#5a3035] dark:bg-[#1f1719]">{items.map((item) => { const c = toneClasses[item.tone]; const crmUrl = salesforceOpportunityUrl(item.crmOpportunityId); return <div key={item.name} className="flex flex-col gap-3 p-4 sm:flex-row sm:items-center sm:justify-between"><div><p className="text-xs font-bold">{item.name}</p><p className="mt-1 text-[10px] font-semibold text-[#526258] dark:text-[#d8c4c6]">{item.amount} · {item.stage}</p><p className="mt-1 text-[10px] leading-relaxed text-[#78847b] dark:text-[#bfaeb0]">Why it needs you: {item.note}</p></div>{(() => { const url = crmUrl || salesforceSearchUrl(item.name); return <a href={url} target="_blank" rel="noreferrer" className={`shrink-0 rounded-lg px-3 py-2 text-[10px] font-bold ${c.card} ${c.text}`}>{item.action} <ArrowUpRight className="ml-1 inline h-3 w-3" /></a>; })()}</div>})}</div></section>;
}

function VerifiedDataNotice({ title, message }: { title: string; message: string }) {
  return <section className="mt-8 rounded-2xl border border-dashed border-[#cddbc7] bg-[#fbfdf8] p-6 dark:border-[#344635] dark:bg-[#172018]"><p className="text-[10px] font-bold uppercase tracking-[0.16em] text-[#4b7853] dark:text-[#d9f579]">Verified data only</p><h2 className="mt-2 text-base font-bold">{title}</h2><p className="mt-2 max-w-2xl text-xs leading-relaxed text-[#78847b] dark:text-[#b8c7b9]">{message}</p></section>;
}

function NextQuarterRunway({ data }: { data: LiveCompassData }) {
  const quota = data.forecast?.quota || 0;
  const forecast = data.forecast?.forecast || 0;
  const pipeline = data.metrics?.open_pipeline_total || 0;
  const ai = data.metrics?.open_pipeline_ai || 0;
  const nb = data.metrics?.open_pipeline_nb || 0;
  const pipelineDeals = data.metrics?.open_deal_count || 0;
  const aiDeals = data.metrics?.open_pipeline_ai_deal_count || 0;
  const nbDeals = data.metrics?.open_pipeline_nb_deal_count || 0;
  const hasData = Boolean(data.pipeline.length || quota > 0 || forecast > 0 || signed > 0 || pipeline > 0);
  const card = (label: string, value: string, meta: string, tone: Tone) => { const c = toneClasses[tone]; return <div className={`rounded-xl border p-4 ${c.card}`}><div className="flex items-center justify-between"><p className={`text-[10px] font-bold uppercase tracking-[0.12em] ${c.text}`}>{label}</p><span className={`h-2 w-2 rounded-full ${c.dot}`} /></div><p className="mt-3 text-2xl font-bold text-[#1a2a20] dark:text-white">{value}</p><p className={`mt-1 text-[10px] font-semibold ${c.text}`}>{meta}</p></div>; };
  return <section className="mt-8 overflow-hidden rounded-2xl border border-[#dfe9b4] bg-[#f7fbdc] p-5 shadow-[0_8px_30px_rgba(33,54,37,0.05)] dark:border-[#526238] dark:bg-[#27321e]"><div className="flex flex-col justify-between gap-3 sm:flex-row sm:items-start"><div><p className="text-[10px] font-bold uppercase tracking-[0.2em] text-[#5d7c39] dark:text-[#d9f579]">Next quarter runway</p><h2 className="mt-1 text-xl font-bold tracking-[-0.03em] text-[#243d2b] dark:text-white">Give future-you a head start.</h2><p className="mt-1 text-xs text-[#6e7e63] dark:text-[#c6d2bd]">Quota and forecast from Clari; pipeline from Salesforce—filtered to FY2027Q4. Signed is not part of this view.</p></div><span className="rounded-full bg-white/75 px-3 py-2 text-[10px] font-bold text-[#4b7853] dark:bg-white/10 dark:text-[#d9f579]">FY2027 Q4</span></div>{hasData ? <><div className="mt-5 grid gap-3 sm:grid-cols-2 lg:grid-cols-3">{card('Quota', compactMoney(quota), data.forecast ? 'Target to plan against' : 'Quota not loaded', 'green')}{card('Forecast', compactMoney(forecast), data.forecast ? `${Math.round((forecast / Math.max(quota, 1)) * 100)}% of quota` : 'Forecast not loaded', 'green')}{card('Pipeline', compactMoney(pipeline), `${pipelineDeals} opportunities · ${quota ? (pipeline / Math.max(quota, 1)).toFixed(1) : '—'}× quota`, 'amber')}</div><div className="mt-3 grid gap-3 sm:grid-cols-2"><div className="rounded-xl bg-white/75 p-4 dark:bg-white/10"><p className="text-[10px] font-bold uppercase tracking-[0.12em] text-[#6033bd] dark:text-[#d9caff]">AI pipeline</p><p className="mt-2 text-xl font-bold text-[#6033bd] dark:text-[#d9caff]">{compactMoney(ai)}</p><p className="mt-1 text-[10px] font-semibold text-[#6033bd] dark:text-[#d9caff]">{aiDeals} open opportunities · {compactMoney(quota * 0.45)} AI target · {quota ? (ai / Math.max(quota * 0.45, 1)).toFixed(1) : '—'}× of target</p></div><div className="rounded-xl bg-white/75 p-4 dark:bg-white/10"><p className="text-[10px] font-bold uppercase tracking-[0.12em] text-[#9c6500] dark:text-[#f5d68b]">New Business pipeline</p><p className="mt-2 text-xl font-bold text-[#9c6500] dark:text-[#f5d68b]">{compactMoney(nb)}</p><p className="mt-1 text-[10px] font-semibold text-[#9c6500] dark:text-[#f5d68b]">{nbDeals} open opportunities · {compactMoney(quota * 0.25)} NB target · {quota ? (nb / Math.max(nb ? quota * 0.25 : 1, 1)).toFixed(1) : '—'}× of target</p></div></div></> : <div className="mt-5 rounded-xl border border-dashed border-[#cddbc7] bg-white/60 p-4 text-xs leading-relaxed text-[#6e7e63] dark:border-[#526238] dark:bg-white/5 dark:text-[#c6d2bd]">No verified FY2027Q4 records are present in the loaded feeds yet. The view is connected and will populate as soon as the same sources include next-quarter rows.</div>}</section>;
  /* Legacy mock layout intentionally removed: Next Quarter must use the same live sources as This Quarter. */
  /* istanbul ignore next */
  return <section className="mt-8 overflow-hidden rounded-2xl border border-[#dfe9b4] bg-[#f7fbdc] p-5 shadow-[0_8px_30px_rgba(33,54,37,0.05)] dark:border-[#526238] dark:bg-[#27321e]"><div className="flex flex-col justify-between gap-3 sm:flex-row sm:items-start"><div><p className="text-[10px] font-bold uppercase tracking-[0.2em] text-[#5d7c39] dark:text-[#d9f579]">Next quarter runway</p><h2 className="mt-1 text-xl font-bold tracking-[-0.03em] text-[#243d2b] dark:text-white">Give future-you a head start.</h2><p className="mt-1 text-xs text-[#6e7e63] dark:text-[#c6d2bd]">A quick read on whether your next quarter has enough shape before it arrives.</p></div><span className="rounded-full bg-white/75 px-3 py-2 text-[10px] font-bold text-[#4b7853] dark:bg-white/10 dark:text-[#d9f579]">FY27 Q3 · planning view</span></div><div className="mt-5 grid gap-3 sm:grid-cols-2 lg:grid-cols-4"><div className="rounded-xl bg-white/75 p-4 dark:bg-white/10"><p className="text-[10px] font-bold uppercase tracking-[0.12em] text-[#6e7e63] dark:text-[#c6d2bd]">Quota</p><p className="mt-2 text-2xl font-bold text-[#243d2b] dark:text-white">$210K</p><p className="mt-1 text-[10px] font-semibold text-[#5d7c39] dark:text-[#d9f579]">Target to plan against</p></div><div className="rounded-xl bg-white/75 p-4 dark:bg-white/10"><p className="text-[10px] font-bold uppercase tracking-[0.12em] text-[#6e7e63] dark:text-[#c6d2bd]">Total pipeline</p><p className="mt-2 text-2xl font-bold text-[#243d2b] dark:text-white">$157K</p><p className="mt-1 text-[10px] font-semibold text-[#a26700]">0.7× coverage · needs build</p></div><div className="rounded-xl bg-white/75 p-4 dark:bg-white/10"><p className="text-[10px] font-bold uppercase tracking-[0.12em] text-[#6e7e63] dark:text-[#c6d2bd]">AI runway</p><p className="mt-2 text-2xl font-bold text-[#6033bd] dark:text-[#d9caff]">$108K</p><p className="mt-1 text-[10px] font-semibold text-[#6033bd] dark:text-[#d9caff]">5 open opportunities</p></div><div className="rounded-xl bg-white/75 p-4 dark:bg-white/10"><p className="text-[10px] font-bold uppercase tracking-[0.12em] text-[#6e7e63] dark:text-[#c6d2bd]">New business runway</p><p className="mt-2 text-2xl font-bold text-[#9c6500] dark:text-[#f5d68b]">$49K</p><p className="mt-1 text-[10px] font-semibold text-[#9c6500] dark:text-[#f5d68b]">3 open opportunities</p></div></div><div className="mt-4 grid gap-3 md:grid-cols-4"><div className="rounded-xl border border-[#dfe9b4] bg-white/55 p-3 dark:border-[#526238] dark:bg-white/5"><p className="text-[10px] font-bold uppercase tracking-[0.12em] text-[#5d7c39] dark:text-[#d9f579]">Timing</p><p className="mt-2 text-xs font-semibold text-[#36473b] dark:text-white">Create before the quarter starts</p><p className="mt-1 text-[10px] leading-relaxed text-[#6e7e63] dark:text-[#c6d2bd]">Prioritize early-stage accounts with a dated next step, not just more volume.</p></div><div className="rounded-xl border border-[#ddd0ff] bg-white/55 p-3 dark:border-[#526238] dark:bg-white/5"><p className="text-[10px] font-bold uppercase tracking-[0.12em] text-[#6033bd] dark:text-[#d9caff]">Whitespace</p><p className="mt-2 text-xs font-semibold text-[#36473b] dark:text-white">Find the next product motion</p><p className="mt-1 text-[10px] leading-relaxed text-[#6e7e63] dark:text-[#c6d2bd]">Use existing accounts to uncover credible AI or expansion paths.</p></div><div className="rounded-xl border border-[#dfe9b4] bg-white/55 p-3 dark:border-[#526238] dark:bg-white/5"><p className="text-[10px] font-bold uppercase tracking-[0.12em] text-[#5d7c39] dark:text-[#d9f579]">Access</p><p className="mt-2 text-xs font-semibold text-[#36473b] dark:text-white">Map the buying group</p><p className="mt-1 text-[10px] leading-relaxed text-[#6e7e63] dark:text-[#c6d2bd]">Make sure every promising opportunity has a path to the decision maker.</p></div><div className="rounded-xl border border-[#dfe9b4] bg-white/55 p-3 dark:border-[#526238] dark:bg-white/5"><p className="text-[10px] font-bold uppercase tracking-[0.12em] text-[#5d7c39] dark:text-[#d9f579]">Data readiness</p><p className="mt-2 text-xs font-semibold text-[#36473b] dark:text-white">Keep the story usable</p><p className="mt-1 text-[10px] leading-relaxed text-[#6e7e63] dark:text-[#c6d2bd]">Clean owner, stage, close date, forecast, and next step before kickoff.</p></div></div><section className="mt-4 rounded-xl border border-[#e5ebe2] bg-white/70 p-4 dark:border-[#526238] dark:bg-white/5"><div className="flex items-center justify-between gap-3"><div><p className="text-[10px] font-bold uppercase tracking-[0.14em] text-[#4b7853] dark:text-[#d9f579]">Whitespace to explore</p><p className="mt-1 text-xs text-[#6e7e63] dark:text-[#c6d2bd]">A short list of accounts where the next conversation could open a new motion.</p></div><span className="rounded-full bg-[#eef8dc] px-2.5 py-1 text-[10px] font-bold text-[#4b7853] dark:bg-white/10 dark:text-[#d9f579]">3 targets</span></div><div className="mt-3 grid gap-2 lg:grid-cols-3"><div className="rounded-lg border border-[#ddd0ff] bg-[#faf8ff] p-3 dark:border-[#493a70] dark:bg-[#211b31]"><div className="flex items-center justify-between"><p className="text-xs font-bold">Northstar Bank</p><span className="text-[9px] font-bold text-[#6033bd]">AI</span></div><p className="mt-2 text-[10px] leading-relaxed text-[#6e6880] dark:text-[#c8bddc]">Existing Suite motion and active value conversation suggest a credible AI workflow to explore.</p><p className="mt-2 text-[10px] font-semibold text-[#6033bd]">Next: ask where automation is still manual ↗</p></div><div className="rounded-lg border border-[#f4df9d] bg-[#fffaf0] p-3 dark:border-[#67552b] dark:bg-[#2d281c]"><div className="flex items-center justify-between"><p className="text-xs font-bold">Pinecrest Health</p><span className="text-[9px] font-bold text-[#9c6500]">New Business</span></div><p className="mt-2 text-[10px] leading-relaxed text-[#756b59] dark:text-[#d8cba9]">A credible prospect with engagement but no recent AI motion; qualify the first business problem.</p><p className="mt-2 text-[10px] font-semibold text-[#9c6500]">Next: lead with the use case, not the product ↗</p></div><div className="rounded-lg border border-[#c9f1dc] bg-[#effcf5] p-3 dark:border-[#31553b] dark:bg-[#1b2a20]"><div className="flex items-center justify-between"><p className="text-xs font-bold">GlobeTel</p><span className="text-[9px] font-bold text-[#087344]">AI</span></div><p className="mt-2 text-[10px] leading-relaxed text-[#5f7768] dark:text-[#c5dbc9]">The prior security conversation is a natural opening to position a more complete AI and governance story.</p><p className="mt-2 text-[10px] font-semibold text-[#087344]">Next: reconnect on the unresolved concern ↗</p></div></div></section><p className="mt-3 text-center text-[10px] italic text-[#8a958b] dark:text-[#aebcaf]">Tiny nudge for the road: when you’re opening a new conversation, it’s always okay to bring AI along for the ride.</p><div className="mt-4 flex flex-col justify-between gap-2 rounded-xl border border-[#dfe9b4] bg-white/60 px-4 py-3 sm:flex-row sm:items-center dark:border-[#526238] dark:bg-white/5"><p className="text-xs font-semibold text-[#36473b] dark:text-white">Runway read: <span className="text-[#9c6500]">not enough yet</span> — build at least $473K more to reach 3× coverage.</p><p className="text-[10px] font-bold text-[#4b7853] dark:text-[#d9f579]">Best first move: create AI + NB pipe this week ↗</p></div></section>;
}

function FiscalYearPerformance({ data }: { data: FiscalYearQuarterData[] }) {
  const money = (value: number) => compactMoney(value || 0);
  const percent = (actual: number, target: number) => target > 0 ? `${Math.round((actual / target) * 100)}%` : '—';
  const label = (quarter: string) => quarter.replace('FY2027', 'FY27 ');
  const totals = data.reduce((sum, row) => ({ quota: sum.quota + (row.forecast.quota || 0), bookings: sum.bookings + (row.metrics.bookings_total || 0), forecast: sum.forecast + (row.forecast.forecast || 0) }), { quota: 0, bookings: 0, forecast: 0 });
  const totalAttainment = totals.quota ? Math.round((totals.bookings / totals.quota) * 100) : 0;
  const quarterCount = data.filter((row) => row.forecast.quota > 0 || row.metrics.bookings_total > 0).length;
  return <section className="mt-5 rounded-2xl border border-[#e5ebe2] bg-white p-5 shadow-[0_8px_30px_rgba(33,54,37,0.04)] dark:border-[#29352b] dark:bg-[#1a231c]"><div className="flex flex-col justify-between gap-2 sm:flex-row sm:items-start"><div><p className="text-[10px] font-bold uppercase tracking-[0.16em] text-[#4b7853] dark:text-[#d9f579]">Fiscal year rhythm</p><h2 className="mt-1 text-base font-bold">Quarter-by-quarter performance</h2><p className="mt-1 text-xs text-[#879289]">Quota and forecast from Clari; bookings from Salesforce.</p></div><span className="rounded-full bg-[#eef8dc] px-3 py-1.5 text-[10px] font-bold text-[#4b7853] dark:bg-[#293c29] dark:text-[#d9f579]">FY2027 · {quarterCount}/4 loaded</span></div><div className="mt-5 grid gap-3 sm:grid-cols-3"><div className="rounded-xl bg-[#effcf5] p-4 dark:bg-white/5"><p className="text-[10px] font-bold uppercase tracking-[0.12em] text-[#087344]">FY quota</p><p className="mt-2 text-xl font-bold">{money(totals.quota)}</p></div><div className="rounded-xl bg-[#effcf5] p-4 dark:bg-white/5"><p className="text-[10px] font-bold uppercase tracking-[0.12em] text-[#087344]">FY bookings</p><p className="mt-2 text-xl font-bold">{money(totals.bookings)}</p><p className="mt-1 text-[10px] font-semibold text-[#087344]">{totalAttainment}% of FY quota</p></div><div className="rounded-xl bg-[#f5f1ff] p-4 dark:bg-white/5"><p className="text-[10px] font-bold uppercase tracking-[0.12em] text-[#6033bd]">FY forecast</p><p className="mt-2 text-xl font-bold text-[#6033bd]">{money(totals.forecast)}</p><p className="mt-1 text-[10px] font-semibold text-[#6033bd]">{totals.quota ? Math.round((totals.forecast / totals.quota) * 100) : 0}% of FY quota</p></div></div><div className="mt-5 overflow-x-auto"><table className="w-full min-w-[820px] text-left"><thead><tr className="border-b border-[#eef1ed] text-[9px] font-bold uppercase tracking-[0.14em] text-[#9aa59c] dark:border-[#29352b]"><th className="pb-3 pl-2">Quarter</th><th className="pb-3">Quota</th><th className="pb-3">Quota vs bookings</th><th className="pb-3">AI | Target vs bookings</th><th className="pb-3">NB | Target vs bookings</th></tr></thead><tbody>{FISCAL_QUARTERS.map((quarter) => { const row = data.find((item) => item.forecast.quarter === quarter); const quota = row?.forecast.quota || 0; const bookings = row?.metrics.bookings_total || 0; const aiTarget = quota * 0.45; const nbTarget = quota * 0.25; return <tr key={quarter} className="border-b border-[#f0f2ef] last:border-0 dark:border-[#29352b]"><td className="py-4 pl-2 text-xs font-bold">{label(quarter)}</td><td className="py-4 text-xs font-bold">{money(quota)}</td><td className="py-4 text-[10px] font-semibold text-[#087344]">{money(bookings)} · {percent(bookings, quota)}</td><td className="py-4 text-[10px] font-semibold text-[#6033bd]"><p>Target: {money(aiTarget)}</p><p className="mt-1">Bookings: {percent(row?.metrics.bookings_ai || 0, aiTarget)}</p></td><td className="py-4 text-[10px] font-semibold text-[#9c6500]"><p>Target: {money(nbTarget)}</p><p className="mt-1">Bookings: {percent(row?.metrics.bookings_nb || 0, nbTarget)}</p></td></tr>; })}</tbody></table></div><p className="mt-3 text-[10px] italic text-[#9aa59c]">AI target is 45% of quarterly quota. New Business target is 25% of quarterly quota. Bookings percentages use Salesforce signed bookings against each target.</p></section>;
}

function CurrentQuarterInsights({ current, metrics }: { current: ForecastSummary; metrics: MetricsSummary | null }) {
  const quota = Number(current.quota || 0);
  const bookings = Number(metrics?.bookings_total || 0);
  const forecast = Number(current.forecast || 0);
  const pipeline = Number(metrics?.open_pipeline_total || 0);
  const remaining = Math.max(quota - bookings, 0);
  const pipelineTarget = remaining * 3;
  const coverage = pipelineTarget > 0 ? pipeline / pipelineTarget : 0;
  const quarterStart = new Date('2026-08-01T00:00:00').getTime();
  const quarterEnd = new Date('2026-10-31T23:59:59').getTime();
  const elapsed = Math.min(Math.max((Date.now() - quarterStart) / Math.max(quarterEnd - quarterStart, 1), 0), 1);
  const expectedBookings = quota * elapsed;
  const pace = expectedBookings > 0 ? bookings / expectedBookings : 0;
  const forecastGap = Math.max(quota - forecast, 0);
  const aiTarget = quota * 0.45;
  const nbTarget = quota * 0.25;
  const aiRemaining = Math.max(aiTarget - Number(metrics?.bookings_ai || 0), 0);
  const nbRemaining = Math.max(nbTarget - Number(metrics?.bookings_nb || 0), 0);
  const freshness = metrics?.data_as_of ? new Date(metrics.data_as_of).toLocaleString([], { dateStyle: 'medium', timeStyle: 'short' }) : null;
  const card = (label: string, value: string, note: string, tone: Tone) => { const c = toneClasses[tone]; return <div className={`rounded-xl border p-4 ${c.card}`}><p className={`text-[10px] font-bold uppercase tracking-[0.12em] ${c.text}`}>{label}</p><p className="mt-2 text-xl font-bold text-[#1a2a20] dark:text-white">{value}</p><p className={`mt-1 text-[10px] font-semibold leading-relaxed ${c.text}`}>{note}</p></div>; };
  return <section className="mt-5"><div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-5"><div>{card('Remaining quota gap', compactMoney(remaining), `${compactMoney(bookings)} booked against ${compactMoney(quota)} quota`, remaining === 0 ? 'green' : 'amber')}</div><div>{card('Forecast gap vs quota', compactMoney(forecastGap), `${compactMoney(forecast)} forecast against ${compactMoney(quota)} quota`, forecastGap === 0 ? 'green' : 'amber')}</div><div>{card('Pipeline coverage', pipelineTarget ? `${coverage.toFixed(1)}×` : '—', pipelineTarget ? `${compactMoney(pipeline)} open · ${compactMoney(pipelineTarget)} needed for 3×` : 'No remaining quota gap to cover', coverage >= 1 ? 'green' : 'rose')}</div><div>{card('AI remaining target', compactMoney(aiRemaining), `${compactMoney(aiTarget)} target · ${compactMoney(metrics?.bookings_ai || 0)} booked`, aiRemaining === 0 ? 'green' : 'violet')}</div><div>{card('NB remaining target', compactMoney(nbRemaining), `${compactMoney(nbTarget)} target · ${compactMoney(metrics?.bookings_nb || 0)} booked`, nbRemaining === 0 ? 'green' : 'amber')}</div></div><div className="mt-3 flex flex-wrap items-center justify-between gap-2 rounded-xl border border-dashed border-[#cddbc7] bg-[#fbfdf8] px-4 py-3 text-[10px] text-[#78867b] dark:border-[#344635] dark:bg-[#172018]"><span className={`font-semibold ${pace >= 1 ? 'text-[#087344]' : 'text-[#9c6500]'}`}>Pacing: {expectedBookings ? `${Math.round(pace * 100)}% of expected bookings` : 'Unavailable until quota is loaded'}</span><span>{freshness ? `Data refreshed ${freshness}` : 'Data freshness unavailable from loaded sources'}</span></div></section>;
}

function YearHighlights() {
  return <VerifiedDataNotice title="Highlights are waiting for verified data" message="Wins will appear here only when they can be calculated from the current verified feed." />;
  return <section className="mt-8 rounded-2xl border border-[#dfe9b4] bg-[#f7fbdc] p-5 shadow-[0_8px_30px_rgba(33,54,37,0.05)] dark:border-[#526238] dark:bg-[#27321e]"><div className="flex items-center justify-between gap-3"><div><p className="text-[10px] font-bold uppercase tracking-[0.16em] text-[#5d7c39] dark:text-[#d9f579]">Your wins so far</p><h2 className="mt-1 text-xl font-bold tracking-[-0.03em] text-[#243d2b] dark:text-white">Good work deserves a highlight.</h2><p className="mt-1 text-xs text-[#6e7e63] dark:text-[#c6d2bd]">A quick reminder of the momentum you’ve already created this year.</p></div><span className="rounded-full bg-white/75 px-3 py-2 text-[10px] font-bold text-[#4b7853] dark:bg-white/10 dark:text-[#d9f579]">FY27 highlights</span></div><div className="mt-5 grid gap-3 md:grid-cols-3"><div className="rounded-xl bg-white/75 p-4 dark:bg-white/10"><p className="text-[10px] font-bold uppercase tracking-[0.12em] text-[#5d7c39] dark:text-[#d9f579]">Largest deal advanced</p><p className="mt-2 text-2xl font-bold text-[#243d2b] dark:text-white">$184K</p><p className="mt-1 text-[10px] font-semibold text-[#5d7c39] dark:text-[#d9f579]">Acme Health · Stage 06</p><p className="mt-2 text-[10px] leading-relaxed text-[#6e7e63] dark:text-[#c6d2bd]">You moved your biggest opportunity into solution validation — that is meaningful momentum.</p></div><div className="rounded-xl bg-white/75 p-4 dark:bg-white/10"><p className="text-[10px] font-bold uppercase tracking-[0.12em] text-[#6033bd] dark:text-[#d9caff]">AI motion unlocked</p><p className="mt-2 text-2xl font-bold text-[#6033bd] dark:text-[#d9caff]">3 lines</p><p className="mt-1 text-[10px] font-semibold text-[#6033bd] dark:text-[#d9caff]">AI product conversations</p><p className="mt-2 text-[10px] leading-relaxed text-[#6e6880] dark:text-[#c8bddc]">You’re creating a multi-product motion, not just a single-threaded deal.</p></div><div className="rounded-xl bg-white/75 p-4 dark:bg-white/10"><p className="text-[10px] font-bold uppercase tracking-[0.12em] text-[#9c6500] dark:text-[#f5d68b]">Buyer momentum</p><p className="mt-2 text-2xl font-bold text-[#9c6500] dark:text-[#f5d68b]">4 accounts</p><p className="mt-1 text-[10px] font-semibold text-[#9c6500] dark:text-[#f5d68b]">buyer paths identified</p><p className="mt-2 text-[10px] leading-relaxed text-[#756b59] dark:text-[#d8cba9]">More than one stakeholder is in the story — a stronger foundation for durable deals.</p></div></div></section>;
}

function ForecastMix() {
  const segments = [['Commit', '$0', 0, 'bg-[#2f5a3b]'], ['Most Likely', '$126K', 36, 'bg-[#8fd27e]'], ['Best Case', '$228K', 64, 'bg-[#f2b90d]'], ['Remaining pipe', '$0', 0, 'bg-[#b8c3bc]']];
  return <section className="rounded-2xl border border-[#e5ebe2] bg-white p-5 shadow-[0_8px_30px_rgba(33,54,37,0.04)] dark:border-[#29352b] dark:bg-[#1a231c]"><div className="flex items-center justify-between gap-3"><div><p className="text-[10px] font-bold uppercase tracking-[0.16em] text-[#4b7853] dark:text-[#d9f579]">Deal backing</p><h2 className="mt-1 text-sm font-bold">Forecast mix at a glance</h2></div><span className="text-xs font-bold text-[#526258] dark:text-[#c8d4c7]">13 open deals · $354K</span></div><div className="mt-6 flex h-5 overflow-hidden rounded-full bg-[#edf1ed] dark:bg-[#29352b]">{segments.map(([label, value, width, color]) => <div key={label} title={`${label}: ${value}`} className={`${color} h-full ${Number(width) > 0 ? '' : 'hidden'}`} style={{ width: `${width}%` }} />)}</div><div className="mt-4 grid gap-3 sm:grid-cols-4">{segments.map(([label, value, width, color]) => <div key={label} className="flex items-center gap-2"><span className={`h-2.5 w-2.5 shrink-0 rounded-full ${color}`} /><div><p className="text-[10px] font-semibold text-[#68766d] dark:text-[#c8d4c7]">{label}</p><p className="text-xs font-bold">{value}</p></div></div>)}</div></section>;
}

function QuarterProgressDetails() {
  return <VerifiedDataNotice title="Detailed quarter data is not loaded" message="The dashboard will show verified linearity, forecast mix, and stage detail when those feeds are available." />;
  const [pipelineTrend, setPipelineTrend] = useState<'WoW' | 'MoM'>('MoM');
  const pipelineView = pipelineTrend === 'MoM'
    ? { period: 'Quarter runway · FY27 Q3', amount: '$238K', count: '12 opportunities', segments: [['Month 1 · Aug', '$108K', '5 opps', 45], ['Month 2 · Sep', '$76K', '4 opps', 32], ['Month 3 · Oct', '$54K', '3 opps', 23]] }
    : { period: 'Quarter runway · weekly view', amount: '$42K', count: '2 opportunities', segments: [['Week 1', '$42K', '2 opps', 32], ['Week 2', '$0', '0 opps', 0], ['Week 3', '$0', '0 opps', 0], ['Week 4', '$0', '0 opps', 0]] };
  const forecast = [['Commit', '$0', '0 deals', 4, 'green'], ['Most Likely', '$126K', '5 deals', 38, 'green'], ['Best Case', '$228K', '8 deals', 68, 'amber'], ['Remaining pipe', '$0', '0 deals', 0, 'gray']];
  const stages = [['02 · Confirm Need', '$78K', '4 deals', 34], ['04 · Establish Value', '$48K', '1 deal', 21], ['06 · Validate Solution', '$228K', '8 deals', 100]];
  return <div className="progress-details mt-5 space-y-5">
    <div className="grid gap-5 xl:grid-cols-2">
      <section className="rounded-2xl border border-[#e5ebe2] bg-white p-5 shadow-[0_8px_30px_rgba(33,54,37,0.04)] dark:border-[#29352b] dark:bg-[#1a231c]"><div className="flex items-center justify-between"><div><p className="text-[10px] font-bold uppercase tracking-[0.16em] text-[#4b7853] dark:text-[#d9f579]">Revenue rhythm</p><h2 className="mt-1 text-sm font-bold">Monthly linearity · Signed</h2></div><span className="text-xs font-bold text-[#526258] dark:text-[#c8d4c7]">$2K total</span></div><div className="mt-6 flex items-center gap-4"><div className="w-24 shrink-0"><p className="text-xs font-semibold">Month 1</p><p className="mt-1 text-[10px] text-[#879289]">Aug</p></div><div className="h-3 flex-1 rounded-full bg-[#edf1ed] dark:bg-[#29352b]"><div className="h-3 w-[12%] rounded-full bg-[#2f5a3b]" /></div><span className="text-xs font-bold">$2K</span><span className="text-[10px] text-[#9aa59c]">1 deal</span></div></section>
      <section className="rounded-2xl border border-[#e5ebe2] bg-white p-5 shadow-[0_8px_30px_rgba(33,54,37,0.04)] dark:border-[#29352b] dark:bg-[#1a231c]"><div className="flex items-center justify-between"><div><p className="text-[10px] font-bold uppercase tracking-[0.16em] text-[#4b7853] dark:text-[#d9f579]">Pipeline created</p><h2 className="mt-1 text-sm font-bold">Next-quarter runway</h2></div><button type="button" onClick={() => setPipelineTrend(pipelineTrend === 'MoM' ? 'WoW' : 'MoM')} className="rounded-lg bg-[#203b29] px-2 py-1 text-[10px] font-bold text-[#d9f579]" aria-label="Switch pipeline trend">{pipelineTrend}</button></div><div className="mt-5 rounded-xl bg-[#f8faf7] p-4 dark:bg-white/5"><div className="flex items-center justify-between"><div><p className="text-[10px] font-bold uppercase tracking-[0.14em] text-[#879289]">{pipelineView.period}</p><p className="mt-1 text-xl font-bold">{pipelineView.amount}</p></div><span className="text-[10px] text-[#9aa59c]">{pipelineView.count}</span></div><div className="mt-3 flex h-2 overflow-hidden rounded-full bg-[#e8eee7] dark:bg-[#29352b]">{pipelineView.segments.map(([label, value, count, width]) => <div key={label as string} title={`${label}: ${value}`} className={`h-full bg-[#23b86b] ${Number(width) === 0 ? 'hidden' : ''}`} style={{ width: `${width}%` }} />)}</div><div className="mt-3 grid grid-cols-3 gap-2">{pipelineView.segments.filter(([, , , width]) => Number(width) > 0).map(([label, value, count]) => <div key={label as string}><p className="text-[9px] font-semibold text-[#879289]">{label}</p><p className="text-[10px] font-bold">{value} · {count}</p></div>)}</div></div></section>
    </div>
    <ForecastMix />
    <section className="rounded-2xl border border-[#e5ebe2] bg-white p-5 shadow-[0_8px_30px_rgba(33,54,37,0.04)] dark:border-[#29352b] dark:bg-[#1a231c]"><div className="flex items-center justify-between"><div><p className="text-[10px] font-bold uppercase tracking-[0.16em] text-[#4b7853] dark:text-[#d9f579]">Deal backing</p><h2 className="mt-1 text-sm font-bold">Forecast confidence at a glance</h2></div><span className="text-xs font-bold text-[#526258] dark:text-[#c8d4c7]">13 open deals · $354K</span></div><div className="mt-6 grid gap-5 md:grid-cols-4">{forecast.map(([label, value, count, width, tone]) => <div key={label as string}><div className="flex items-center justify-between"><p className="text-xs font-semibold text-[#68766d] dark:text-[#c8d4c7]">{label}</p><span className="text-xs font-bold">{value}</span></div><div className="mt-2 h-2 rounded-full bg-[#edf1ed] dark:bg-[#29352b]"><div className={`h-2 rounded-full ${tone === 'amber' ? 'bg-[#f2b90d]' : tone === 'gray' ? 'bg-[#b8c3bc]' : 'bg-[#8fd27e]'}`} style={{ width: `${width}%` }} /></div><p className="mt-2 text-[10px] text-[#9aa59c]">{count}</p></div>)}</div></section>
    <section className="rounded-2xl border border-[#e5ebe2] bg-white p-5 shadow-[0_8px_30px_rgba(33,54,37,0.04)] dark:border-[#29352b] dark:bg-[#1a231c]"><div className="flex items-center justify-between"><div><p className="text-[10px] font-bold uppercase tracking-[0.16em] text-[#4b7853] dark:text-[#d9f579]">Stage distribution</p><h2 className="mt-1 text-sm font-bold">Open pipeline by stage</h2></div><span className="text-[10px] text-[#9aa59c]">This Quarter</span></div><div className="mt-6 grid gap-5 md:grid-cols-3">{stages.map(([label, value, count, height]) => <div key={label as string} className="flex flex-col items-center"><div className="flex h-28 w-full max-w-[180px] items-end justify-center rounded-xl bg-[#f8faf7] px-5 dark:bg-white/5"><div className="w-14 rounded-t-xl bg-gradient-to-t from-[#2f5a3b] to-[#9bd98b]" style={{ height: `${height}%` }} /></div><p className="mt-3 text-center text-[10px] font-semibold text-[#68766d] dark:text-[#c8d4c7]">{label}</p><p className="mt-1 text-sm font-bold">{value}</p><p className="text-[10px] text-[#9aa59c]">{count}</p></div>)}</div></section>
  </div>;
}

function ProgressView({ period, setPeriod, liveData, fiscalYearData }: { period: Period; setPeriod: (value: Period) => void; liveData: LiveCompassData; fiscalYearData: FiscalYearQuarterData[] }) {
  const selectedPeriod = period === 'Full year' ? 'Full year' : 'This Q';
  const current = liveData.forecast;
  const metrics = liveData.metrics;
  const liveSnapshots = current ? {
    'This Q': [['Quota', metrics?.bookings_total ?? 0, current.quota ? `${Math.round(((metrics?.bookings_total ?? 0) / current.quota) * 100)}% of quota` : 'No quota loaded', current.quota ? ((metrics?.bookings_total ?? 0) / current.quota) * 100 : 0, ''], ['Forecast', current.forecast, current.quota ? `${Math.round((current.forecast / current.quota) * 100)}% of quota` : 'No quota loaded', current.quota ? (current.forecast / current.quota) * 100 : 0, ''], ['AI', metrics?.bookings_ai ?? 0, `${metrics?.bookings_ai_deal_count ?? 0} opps · ${current.ai_target ? Math.round(((metrics?.bookings_ai ?? 0) / current.ai_target) * 100) : 0}% of AI target`, current.ai_target ? ((metrics?.bookings_ai ?? 0) / current.ai_target) * 100 : 0, metrics ? `${compactMoney(metrics.open_pipeline_ai)} · ${metrics.open_pipeline_ai_deal_count} opps` : ''], ['New Business', metrics?.bookings_nb ?? 0, `${metrics?.bookings_nb_deal_count ?? 0} opps · ${current.nb_target ? Math.round(((metrics?.bookings_nb ?? 0) / current.nb_target) * 100) : 0}% of NB target`, current.nb_target ? ((metrics?.bookings_nb ?? 0) / current.nb_target) * 100 : 0, metrics ? `${compactMoney(metrics.open_pipeline_nb)} · ${metrics.open_pipeline_nb_deal_count} opps` : ''], ['Pipeline', metrics?.open_pipeline_total ?? current.pipeline, `${metrics?.open_deal_count ?? 0} opps · open pipeline`, current.quota ? ((metrics?.open_pipeline_total ?? current.pipeline) / current.quota) * 100 : 0, '']]
  } : null;
  const rows = liveSnapshots?.[selectedPeriod] ?? [];
  return <div className="mx-auto max-w-[1320px] px-6 py-8 sm:px-10"><div className="flex flex-col justify-between gap-3 sm:flex-row sm:items-end"><div><p className="text-[10px] font-bold uppercase tracking-[0.2em] text-[#51865c]">Your progress, in plain English</p><h1 className="mt-2 text-3xl font-bold tracking-[-0.04em]">{selectedPeriod === 'This Q' ? 'Quarter scorecard' : 'Fiscal-year scorecard'}</h1><p className="mt-2 text-sm text-[#78847b]">The progress view for the period you picked—quota, forecast, AI, New Business, and pipeline.</p></div><span className="rounded-full bg-[#eef8dc] px-3 py-2 text-[10px] font-bold text-[#4b7853] dark:bg-[#293c29] dark:text-[#d9f579]">{selectedPeriod === 'This Q' ? CURRENT_QUARTER : 'Fiscal year'}</span></div><div className="mt-6 flex flex-wrap items-center gap-2"><span className="mr-1 text-[10px] font-bold uppercase tracking-[0.14em] text-[#8a958b]">Progress for</span>{(['This Q', 'Full year'] as Period[]).map((item) => <button key={item} onClick={() => setPeriod(item)} className={`rounded-full px-3 py-1.5 text-[10px] font-bold ${selectedPeriod === item ? 'bg-[#203b29] text-[#d9f579]' : 'border border-[#dfe8d7] bg-white text-[#718077] dark:border-[#344635] dark:bg-[#1a231c] dark:text-[#c8d4c7]'}`}>{item === 'This Q' ? 'This Quarter' : 'Fiscal Year'}</button>)}</div>{selectedPeriod === 'This Q' && (rows.length ? <><div className="mt-8 grid gap-3 sm:grid-cols-2 xl:grid-cols-6">{rows.map(([label, rawValue, meta, score, pipe]) => { const target = current ? (label === 'Quota' || label === 'Forecast' ? current.quota : label === 'AI' ? current.quota * 0.45 : label === 'New Business' ? current.quota * 0.25 : label === 'Pipeline' ? Math.max(current.quota - (metrics?.bookings_total || 0), 0) * 3 : progressTargets[label]) : progressTargets[label]; const actual = Number(rawValue); const progressPercent = target ? (actual / target) * 100 : Number(score); const c = toneClasses[paceTone(progressPercent)]; const remaining = Math.max(target - actual, 0); const displayLabel = label === 'Quota' ? 'Quota progress' : label === 'Forecast' ? 'Forecast progress' : label === 'AI' ? 'AI progress' : label === 'New Business' ? 'New business progress' : 'Pipeline progress'; return <div key={label} className={`min-h-[164px] rounded-2xl border p-4 ${c.card} ${label === 'Quota' || label === 'Forecast' ? 'xl:col-span-3' : 'xl:col-span-2'}`}><div className="flex items-center justify-between"><p className={`text-[10px] font-bold uppercase tracking-[0.12em] ${c.text}`}>{displayLabel}</p><span className={`h-2 w-2 rounded-full ${c.dot}`} /></div><p className="mt-5 text-2xl font-bold text-[#1a2a20] dark:text-white">{compactMoney(actual)}</p><p className={`mt-3 text-[11px] font-semibold leading-relaxed ${c.text}`}>{label === 'Pipeline' ? 'Total pipeline' : label === 'Quota' ? 'Quota' : label === 'Forecast' ? 'Forecast' : label === 'AI' ? 'AI signed' : label === 'New Business' ? 'New Business signed' : 'Pipeline'} · {Math.round(progressPercent)}% of target · {remaining === 0 ? 'On target' : `${compactMoney(remaining)} to go`}</p>{pipe && <p className={`mt-3 text-[11px] font-semibold ${c.text}`}>Open Pipe: {pipe}</p>}</div>})}</div><CurrentQuarterInsights current={current} metrics={metrics} /></> : <VerifiedDataNotice title="No verified progress data loaded" message="This period will remain empty until quota, forecast, and outcome records are available for the signed-in profile." />)}{selectedPeriod === 'Full year' && <FiscalYearPerformance data={fiscalYearData} />}</div>;
}


function CompassSecondaryView({ view, activeDeal, setActiveDeal, period, setPeriod, liveData, fiscalYearData }: { view: CompassView; activeDeal: number; setActiveDeal: (value: number) => void; period: Period; setPeriod: (value: Period) => void; liveData: LiveCompassData; fiscalYearData: ForecastSummary[] }) {
  const liveDeals = liveDealCards(liveData.pipeline);
  const deal = liveDeals[activeDeal];
  const displayDeals = liveDeals;
  const dealsForPeriod = displayDeals.filter((item) => period === 'This Q' ? item.quarter === 'This Q' : item.quarter === period);
  const s1ForPeriod: S1Opportunity[] = liveData.pipeline
    .filter((row) => stageNumber(row) === 1)
    .map((row) => ({
      name: row.opportunity_name || row.crm_account_name || 'Unnamed opportunity',
      crmOpportunityId: row.crm_opportunity_id,
      amount: rowAmount(row),
      rating: 'Review',
      categories: [],
      reason: s1Analysis(liveData.gongSignals?.find((signal) => signal.crm_opportunity_id === row.crm_opportunity_id)),
      tone: 'violet' as Tone,
    }));
  if (view === 'Progress') return <ProgressView period={period} setPeriod={setPeriod} liveData={liveData} fiscalYearData={fiscalYearData} />;
  if (view === 'My deals') return <div className="mx-auto max-w-[1320px] px-6 py-8 sm:px-10"><p className="text-[10px] font-bold uppercase tracking-[0.2em] text-[#51865c]">Your book of business</p><h1 className="mt-2 text-3xl font-bold tracking-[-0.04em]">My deals</h1><p className="mt-2 text-sm text-[#78847b]">A calm, focused view of the opportunities that need your attention.</p><div className="mt-5 flex items-center gap-2"><span className="mr-1 text-[10px] font-bold uppercase tracking-[0.14em] text-[#8a958b]">View</span>{(["This Q", "Next Q"] as Period[]).map((item) => <button key={item} onClick={() => setPeriod(item)} className={`rounded-full px-3 py-1.5 text-[10px] font-bold ${period === item ? "bg-[#203b29] text-[#d9f579]" : "border border-[#dfe8d7] bg-white text-[#718077] dark:border-[#344635] dark:bg-[#1a231c] dark:text-[#c8d4c7]"}`}>{item === "This Q" ? "This Quarter" : "Next Quarter"}</button>)}</div><div className="mt-5 overflow-hidden rounded-2xl border border-[#e5ebe2] bg-white shadow-[0_8px_30px_rgba(33,54,37,0.04)] dark:border-[#29352b] dark:bg-[#1a231c]"><div className="flex items-center justify-between border-b border-[#eef1ed] px-5 py-4 dark:border-[#29352b]"><div><h2 className="text-sm font-bold">Active deals · Stage 2–06</h2><p className="mt-1 text-[10px] text-[#8a958b]">All open opportunities in this quarter’s active selling stages.</p></div></div><div className="max-h-[420px] overflow-y-auto"><div className="grid grid-cols-[1.3fr_0.8fr_0.7fr_0.6fr_1fr] border-b border-[#eef1ed] px-5 py-3 text-[9px] font-bold uppercase tracking-[0.14em] text-[#9aa59c] dark:border-[#29352b]"><span>Opportunity</span><span>Stage</span><span>Amount</span><span>Health</span><span>Next best move</span></div>{dealsForPeriod.filter((item) => !item.stage.startsWith('01')).map((item) => { const index = displayDeals.indexOf(item); const c = toneClasses[item.tone]; const crmUrl = salesforceOpportunityUrl(item.crmOpportunityId) || salesforceSearchUrl(item.name); return <button key={item.name} onClick={() => setActiveDeal(index)} className={`grid w-full grid-cols-[1.3fr_0.8fr_0.7fr_0.6fr_1fr] items-center px-5 py-5 text-left transition hover:bg-[#fbfdf8] dark:hover:bg-[#202b22] ${activeDeal === index ? 'bg-[#f7fbe9] dark:bg-[#263526]' : ''}`}><span><a href={crmUrl} target="_blank" rel="noreferrer" onClick={(event) => event.stopPropagation()} className="text-xs font-bold hover:underline">{item.name}</a><p className="mt-1 text-[10px] text-[#8a958b]">{item.account}</p></span><span className="text-[10px] text-[#6e7b72]">{item.stage}</span><span className="text-xs font-bold">{item.amount}</span><span><span className={`inline-flex items-center gap-1.5 rounded-full px-2 py-1 text-[9px] font-bold ${c.text} ${c.card}`}><span className={`h-1.5 w-1.5 rounded-full ${c.dot}`} />{item.health}</span></span><span className={`text-[10px] font-semibold ${c.text}`}>{item.action}</span></button> })}</div></div><div className="mt-5 rounded-2xl border border-dashed border-[#cddbc7] bg-[#fbfdf8] p-4 text-[10px] text-[#78867b] dark:border-[#344635] dark:bg-[#172018]">Select a deal to carry it into your deal brief and next-step view.</div><div className="mt-8 rounded-2xl border border-[#ddd0ff] bg-[#faf8ff] p-5 dark:border-[#493a70] dark:bg-[#211b31]"><div className="flex items-start justify-between gap-4"><div><div className="flex items-center gap-2"><span className="rounded-md bg-[#e8ddff] px-2 py-1 text-[10px] font-bold text-[#6033bd]">S1 OPPORTUNITIES</span><h2 className="text-sm font-bold">Promising early signals</h2></div></div><span className="rounded-full bg-white/75 px-2.5 py-1 text-[10px] font-bold text-[#6033bd] dark:bg-white/10 dark:text-[#d9caff]">{s1ForPeriod.length} to review</span></div><div className="mt-5 space-y-3">{s1ForPeriod.map((item) => { const c = toneClasses[item.tone]; return <button key={item.name} onClick={() => setActiveDeal(displayDeals.findIndex((dealItem) => dealItem.name === item.name))} className="grid w-full gap-4 rounded-xl border border-[#ebe4ff] bg-white/80 p-4 text-left transition hover:border-[#b6a0ff] dark:border-[#493a70] dark:bg-white/5 md:grid-cols-[1fr_110px_1.5fr]"><span><a href={salesforceOpportunityUrl(item.crmOpportunityId) || salesforceSearchUrl(item.name)} target="_blank" rel="noreferrer" onClick={(event) => event.stopPropagation()} className="text-xs font-bold hover:underline">{item.name}</a><p className="mt-1 text-[10px] text-[#8a958b]">Stage 01 · Qualify · {item.amount}</p></span><span className={`self-start rounded-lg px-2 py-2 text-center text-[10px] font-bold ${c.card} ${c.text}`}>{item.rating}<br /><span className="text-[9px] font-medium">S1 rating</span></span><span><span className={`text-[10px] font-bold ${c.text}`}>{item.categories.join(' · ')}</span><p className="mt-1 text-[10px] leading-relaxed text-[#78847b] dark:text-[#c8bddc]">{item.reason}</p></span></button> })}</div></div></div>;
  return <div className="mx-auto max-w-[1320px] px-6 py-8 sm:px-10"><div className="flex flex-col justify-between gap-3 sm:flex-row sm:items-end"><div><p className="text-[10px] font-bold uppercase tracking-[0.2em] text-[#51865c]">Your progress, in plain English</p><h1 className="mt-2 text-3xl font-bold tracking-[-0.04em]">{period === 'This Q' ? 'Quarter scorecard' : period === 'Next Q' ? 'Next-quarter runway' : 'Full-year scorecard'}</h1><p className="mt-2 text-sm text-[#78847b]">The progress view for the period you picked—quota, forecast, AI, New Business, and pipeline.</p></div><span className="rounded-full bg-[#eef8dc] px-3 py-2 text-[10px] font-bold text-[#4b7853] dark:bg-[#293c29] dark:text-[#d9f579]">Sample view · {period === 'This Q' ? 'FY27 Q2' : period === 'Next Q' ? 'FY27 Q3' : 'FY27'}</span></div><div className="mt-6 flex flex-wrap items-center gap-2"><span className="mr-1 text-[10px] font-bold uppercase tracking-[0.14em] text-[#8a958b]">Progress for</span>{(['This Q', 'Full year'] as Period[]).map((item) => <button key={item} onClick={() => setPeriod(item)} className={`rounded-full px-3 py-1.5 text-[10px] font-bold ${period === item ? 'bg-[#203b29] text-[#d9f579]' : 'border border-[#dfe8d7] bg-white text-[#718077] dark:border-[#344635] dark:bg-[#1a231c] dark:text-[#c8d4c7]'}`}>{item === 'This Q' ? 'This Quarter' : 'Fiscal Year'}</button>)}</div>{period !== 'Full year' && <div className="mt-8 grid gap-3 sm:grid-cols-2 xl:grid-cols-6">{progressSnapshots[period].map(([label, value, meta, score, pipe]) => { const target = progressTargets[label]; const actual = label === 'Quota' || label === 'Forecast' ? signedByPeriod[period] : label === 'AI' ? 600 : label === 'New Business' ? 0 : 354000; const progressPercent = target ? (actual / target) * 100 : Number(score); const c = toneClasses[paceTone(progressPercent)]; const remaining = Math.max(target - actual, 0); const displayLabel = label === 'Quota' ? 'Quota progress' : label === 'Forecast' ? 'Forecast progress' : label === 'AI' ? 'AI progress' : label === 'New Business' ? 'New business progress' : label === 'Pipeline' ? 'Pipeline progress' : label; const actualLabel = label === 'Quota' || label === 'Forecast' || label === 'AI' || label === 'New Business' ? 'Signed' : 'Total pipeline'; return <div key={label} className={`min-h-[164px] rounded-2xl border p-4 ${c.card} ${label === 'Quota' || label === 'Forecast' ? 'xl:col-span-3' : 'xl:col-span-2'}`}><div className="flex items-center justify-between"><p className={`text-[10px] font-bold uppercase tracking-[0.12em] ${c.text}`}>{displayLabel}</p><span className={`h-2 w-2 rounded-full ${c.dot}`} /></div><p className="mt-5 text-2xl font-bold text-[#1a2a20] dark:text-white">{value}{meta.match(/[0-9]+ opps?|[0-9]+ deals?/)?.[0] && <span className={`text-base font-semibold ${c.text}`}> | {meta.match(/[0-9]+ opps?|[0-9]+ deals?/)?.[0]}</span>}</p><p className={`mt-3 text-[11px] font-semibold leading-relaxed ${c.text}`}>{actualLabel} {compactMoney(actual)} · {Math.round(progressPercent)}% of target · {remaining === 0 ? 'On target' : `${compactMoney(remaining)} to go`}</p>{pipe && <p className={`mt-3 text-[11px] font-semibold ${c.text}`}>Open Pipe: {pipe}</p>}</div>})}</div>}{period === 'Full year' && <YearHighlights />}{period === 'Full year' && <FiscalYearPerformance />}</div>;
}

function FloatingCompass({ viewerName, isAdmin, pipelineCount }: { viewerName: string; isAdmin: boolean; pipelineCount: number }) {
  const [question, setQuestion] = useState('');
  const [assistantAnswer, setAssistantAnswer] = useState('');
  const [assistantLoading, setAssistantLoading] = useState(false);
  const [assistantHistory, setAssistantHistory] = useState<Array<{ role: 'user' | 'assistant'; text: string }>>([]);
  const [open, setOpen] = useState(false);
  const [pos, setPos] = useState({ x: 0, y: 0 });
  const [panelPos, setPanelPos] = useState({ x: 0, y: 0 });
  const [ready, setReady] = useState(false);
  const drag = useRef<{ ox: number; oy: number; moved: boolean } | null>(null);

  useEffect(() => {
    setPos({ x: window.innerWidth - 76, y: window.innerHeight - 96 });
    setReady(true);
  }, []);
  useEffect(() => {
    setAssistantAnswer('');
    setAssistantHistory([]);
  }, [viewerName]);

  const askCompass = async () => {
    if (!question.trim() || assistantLoading) return;
    const asked = question.trim();
    setAssistantLoading(true);
    setAssistantAnswer('Thinking…');
    try {
      const result = await api.askCompass(asked, isAdmin ? 'all' : viewerName, CURRENT_QUARTER, assistantHistory);
      setAssistantAnswer(result.answer);
      setAssistantHistory((items) => [...items, { role: 'user', text: asked }, { role: 'assistant', text: result.answer }].slice(-20));
      setQuestion('');
    } catch {
      setAssistantAnswer('I hit a snag while checking your deals. Please try that again.');
    } finally {
      setAssistantLoading(false);
    }
  };

  const onPointerDown = (e: any) => {
    const originX = open ? panelPos.x : pos.x;
    const originY = open ? panelPos.y : pos.y;
    drag.current = { ox: e.clientX - originX, oy: e.clientY - originY, moved: false };
    try { (e.currentTarget as HTMLElement).setPointerCapture(e.pointerId); } catch { /* noop */ }
  };
  const onPointerMove = (e: any) => {
    if (!drag.current) return;
    const nx = e.clientX - drag.current.ox;
    const ny = e.clientY - drag.current.oy;
    if (Math.abs(nx - pos.x) > 3 || Math.abs(ny - pos.y) > 3) drag.current.moved = true;
    const maxX = window.innerWidth - (open ? panelWidth + 12 : 64);
    const maxY = window.innerHeight - (open ? panelHeight + 12 : 64);
    if (open) {
      setPanelPos({ x: Math.max(12, Math.min(nx, maxX)), y: Math.max(12, Math.min(ny, maxY)) });
    } else {
      setPos({ x: Math.max(8, Math.min(nx, maxX)), y: Math.max(8, Math.min(ny, maxY)) });
    }
  };
  const onPointerUp = () => {
    const moved = drag.current?.moved;
    drag.current = null;
    if (!moved && !open) {
      setPanelPos({ x: panelLeft, y: panelTop });
      setOpen(true);
    }
  };

  if (!ready) return null;

  const panelWidth = Math.min(420, window.innerWidth - 24);
  const panelHeight = Math.min(240, window.innerHeight - 24);
  const panelLeft = Math.max(12, Math.min(pos.x - panelWidth + 48, window.innerWidth - panelWidth - 12));
  const panelTop = Math.max(12, Math.min(pos.y - panelHeight + 80, window.innerHeight - panelHeight - 12));

  return (
    <div style={{ position: 'fixed', left: open ? panelPos.x : pos.x, top: open ? panelPos.y : pos.y, zIndex: 70 }} className="touch-none select-none">
      {open ? (
        <div style={{ width: panelWidth, maxHeight: panelHeight }} className="overflow-hidden rounded-2xl border border-[#2a3b28] bg-[#203b29] text-white shadow-[0_18px_40px_rgba(17,30,22,0.4)]">
          <div onPointerDown={onPointerDown} onPointerMove={onPointerMove} onPointerUp={onPointerUp} className="flex cursor-grab items-center gap-2 px-3 py-2.5 active:cursor-grabbing">
            <Bot className="h-4 w-4 text-[#d9f579]" />
            <p className="text-xs font-bold">Ask Compass</p>
            <span className="ml-auto rounded-full bg-white/10 px-2 py-0.5 text-[9px] text-[#d9f579]">beta</span>
            <button type="button" onPointerDown={(event) => event.stopPropagation()} onClick={() => setOpen(false)} aria-label="Minimize Ask Compass" className="ml-1 rounded-md px-1.5 py-0.5 text-[11px] font-bold text-white/70 hover:bg-white/10">✕</button>
          </div>
          <div className="px-3 pb-3">
            <div className="max-h-[90px] overflow-y-auto rounded-xl bg-white/10 p-3">
              <p className={`text-[10px] leading-relaxed text-white/80 ${assistantLoading ? 'animate-pulse' : ''}`}>{assistantAnswer || (pipelineCount ? `I found ${pipelineCount} current-quarter opportunities. Ask me to narrow the view.` : 'Ask me about a deal, your pipeline, AI, or your next best move.')}</p>
            </div>
            <div className="mt-2 flex gap-2">
              <input value={question} onChange={(e) => setQuestion(e.target.value)} onKeyDown={(e) => { if (e.key === 'Enter') askCompass(); }} disabled={assistantLoading} className="min-w-0 flex-1 rounded-lg border border-white/15 bg-white/10 px-2.5 py-2 text-[11px] text-white outline-none placeholder:text-white/45 disabled:cursor-wait disabled:opacity-60" placeholder={assistantLoading ? 'Compass is thinking…' : 'Ask about a deal...'} />
              <button onClick={askCompass} disabled={assistantLoading || !question.trim()} className="rounded-lg bg-[#d9f579] px-3 py-2 text-[11px] font-bold text-[#25402c] disabled:cursor-wait disabled:opacity-60">{assistantLoading ? 'Thinking…' : 'Ask'}</button>
            </div>
            <div className="mt-2 flex flex-wrap gap-1.5">
              {['What changed this week?', 'Which deals are at risk?', 'Show my AI opportunities'].map((p) => (
                <button key={p} onClick={() => setQuestion(p)} className="rounded-full bg-white/10 px-2 py-1 text-[9px] font-semibold text-[#d9f579] hover:bg-white/20">{p}</button>
              ))}
            </div>
          </div>
        </div>
      ) : (
        <button onPointerDown={onPointerDown} onPointerMove={onPointerMove} onPointerUp={onPointerUp} aria-label="Open Ask Compass" title={assistantAnswer ? 'Open Ask Compass — your last answer is waiting' : 'Open Ask Compass'} className="relative flex h-12 w-12 items-center justify-center rounded-full bg-[#203b29] text-[#d9f579] shadow-[0_8px_24px_rgba(32,59,41,0.35)] ring-1 ring-white/10 transition hover:scale-105 active:scale-95">
          <Bot className="h-5 w-5" />
          {assistantAnswer && <span aria-label="Saved answer" className="absolute -right-0.5 -top-0.5 h-3 w-3 rounded-full border-2 border-[#f7faf5] bg-[#d9f579]" />}
        </button>
      )}
    </div>
  );
}

export default function AECompass({ viewerName, isAdmin, dark, toggleTheme, onLogout }: { viewerName: string; isAdmin: boolean; dark: boolean; toggleTheme: () => void; onLogout: () => void }) {
  const [activeDeal, setActiveDeal] = useState(0);
  const [activeView, setActiveView] = useState<CompassView>('My day');
  const [period, setPeriod] = useState<Period>('This Q');
  const [activeCockpit, setActiveCockpit] = useState<string | null>(null);
  const [liveData, setLiveData] = useState<LiveCompassData>({ forecast: null, metrics: null, pipeline: [] });
  const [nextData, setNextData] = useState<LiveCompassData>({ forecast: null, metrics: null, pipeline: [], gtmiPipeline: null });
  const [fiscalYearData, setFiscalYearData] = useState<FiscalYearQuarterData[]>([]);
  const liveDeals = liveDealCards(liveData.pipeline);
  const displayedDeals = liveDeals;

  useEffect(() => {
    let active = true;
    const scope = (quarter: string) => [
      api.getForecast(isAdmin ? 'all' : viewerName, quarter),
      api.getMetricsSummary(isAdmin ? { all: '1', quarter } : { owner_name: viewerName, quarter }),
      api.getPipeline(isAdmin ? { all: '1', quarter } : { owner_name: viewerName, quarter }),
    ];
    Promise.all(scope(CURRENT_QUARTER)).then(([forecast, metrics, pipeline]) => {
      if (active) setLiveData({ forecast, metrics, pipeline, gongSignals: [] });
      api.getGong(pipeline.filter((row) => stageNumber(row) === 1).map((row) => row.crm_opportunity_id)).then((gong) => {
        if (active) setLiveData((current) => ({ ...current, gongSignals: gong.signals }));
      }).catch(() => { /* Gong is optional; Salesforce data should still render. */ });
    }).catch(() => { /* Keep the shell usable when the local data server is offline. */ });
    Promise.all([
      ...scope(NEXT_QUARTER),
      api.getGtmiPipelineSummary(isAdmin ? { all: '1', quarter: NEXT_QUARTER } : { owner_name: viewerName, quarter: NEXT_QUARTER }),
    ]).then(([forecast, metrics, pipeline, gtmiPipeline]) => {
      if (active) setNextData({ forecast, metrics, pipeline, gtmiPipeline, gongSignals: [] });
      api.getGong(pipeline.filter((row) => stageNumber(row) === 1).map((row) => row.crm_opportunity_id)).then((gong) => {
        if (active) setNextData((current) => ({ ...current, gongSignals: gong.signals }));
      }).catch(() => { /* Gong is optional; Next-quarter deals should still render. */ });
    }).catch(() => { /* Next-quarter data may not be available in the loaded feeds. */ });
    Promise.all(FISCAL_QUARTERS.map((quarter) => Promise.all([
      api.getForecast(isAdmin ? 'all' : viewerName, quarter),
      api.getMetricsSummary(isAdmin ? { all: '1', quarter } : { owner_name: viewerName, quarter }),
    ]).then(([forecast, metrics]) => ({ forecast, metrics }))))
      .then((rows) => { if (active) setFiscalYearData(rows); })
      .catch(() => { if (active) setFiscalYearData([]); });
    return () => { active = false; };
  }, [viewerName, isAdmin]);
  const myDayCards = [
    ['Quota progress', liveData.forecast && liveData.metrics ? `${Math.round((liveData.metrics.bookings_total / Math.max(liveData.forecast.quota, 1)) * 100)}%` : 'Loading…', liveData.forecast && liveData.metrics ? `${compactMoney(Math.max(liveData.forecast.quota - liveData.metrics.bookings_total, 0))} to go` : 'Reading current quarter', 'green', TrendingUp],
    ['Forecast progress', liveData.forecast ? `${Math.round((liveData.forecast.forecast / Math.max(liveData.forecast.quota, 1)) * 100)}%` : 'Loading…', liveData.forecast ? `${compactMoney(Math.max(liveData.forecast.quota - liveData.forecast.forecast, 0))} to go` : 'Reading current quarter', 'green', TrendingUp],
    ['Signed this quarter', liveData.metrics ? compactMoney(liveData.metrics.bookings_total) : 'Loading…', liveData.metrics ? `${liveData.metrics.bookings_deal_count} opportunities` : 'Reading current quarter', 'violet', Target],
    ['Open pipeline', liveData.metrics ? compactMoney(liveData.metrics.open_pipeline_total) : 'Loading…', liveData.metrics ? `${liveData.metrics.open_deal_count} opportunities` : 'Reading current quarter', 'amber', Gauge],
  ] as const;


  return (
    <div className="min-h-screen bg-[#f7f8f5] text-[#17221c] selection:bg-[#d9f579] dark:bg-[#111712] dark:text-[#f1f5ec]">
      <aside className="fixed inset-y-0 left-0 hidden w-[248px] flex-col border-r border-[#e6ebe4] bg-white px-5 py-6 dark:border-[#29352b] dark:bg-[#1a231c] lg:flex">
        <div className="flex items-center gap-3"><div className="flex h-9 w-9 -rotate-6 items-center justify-center rounded-xl bg-[#d9f579] text-[#203b29] shadow-[3px_3px_0_#a6d894]">⌁</div><div><p className="text-sm font-bold tracking-tight">AE Compass</p><p className="text-[10px] text-[#8a958b]">your deal co-pilot</p></div></div>
        <div className="mt-10 space-y-1">
          {['My day', 'My deals', 'Progress'].map((item, index) => <button key={item} onClick={() => setActiveView(item as CompassView)} className={`flex w-full items-center gap-3 rounded-xl px-3 py-2.5 text-left text-xs font-semibold ${activeView === item ? 'bg-[#eef8dc] text-[#2e603d] dark:bg-[#293c29] dark:text-[#d9f579]' : 'text-[#7c887f] hover:bg-[#f5f7f3] dark:hover:bg-[#223024]'}`}><span className="w-4 text-center">{index === 0 ? '✦' : index === 1 ? '◌' : '↗'}</span>{item}</button>)}
        </div>
        <div className="mt-auto"><div className="rounded-2xl bg-[#203b29] p-4 text-white"><p className="text-[10px] font-bold uppercase tracking-[0.16em] text-[#d9f579]">Compass tip</p><p className="mt-2 text-xs leading-relaxed text-white/75">The best next step is usually smaller than the whole deal.</p><button className="mt-3 flex items-center gap-1 text-[10px] font-bold text-[#d9f579]">Open my playbook <ArrowUpRight className="h-3 w-3" /></button></div></div>
      </aside>

      <main className="lg:ml-[248px]">
        <header className="flex items-center justify-between border-b border-[#e6ebe4] bg-white/80 px-6 py-4 backdrop-blur dark:border-[#29352b] dark:bg-[#111712]/80 sm:px-10"><div className="flex items-center gap-3"><div className="relative"><Search className="absolute left-3 top-2.5 h-3.5 w-3.5 text-[#9aa59c]" /><input className="w-48 rounded-lg border border-[#e6ebe4] bg-[#fbfcfa] py-2 pl-9 pr-3 text-xs outline-none focus:border-[#8fc45e] dark:border-[#29352b] dark:bg-[#1a231c] sm:w-64" placeholder="Search deals, accounts..." /></div><span className="hidden items-center gap-1.5 text-[10px] text-[#879289] sm:flex"><Command className="h-3 w-3" /> K</span></div><div className="flex items-center gap-3"><button onClick={toggleTheme} className="rounded-lg p-2 text-[#829087] hover:bg-[#f1f4ef] dark:hover:bg-[#223024]" aria-label="Toggle theme">{dark ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}</button><div className="flex items-center gap-2 border-l border-[#e6ebe4] pl-3 dark:border-[#29352b]"><div className="flex h-7 w-7 items-center justify-center rounded-full bg-[#d9f579] text-[10px] font-bold text-[#25402c]">{viewerName.split(' ').map((part) => part[0]).join('').slice(0, 2).toUpperCase()}</div><span className="hidden text-xs font-semibold sm:inline">{viewerName}</span></div><div className="h-6 w-px bg-[#e6ebe4] dark:bg-[#29352b]" /><button onClick={onLogout} className="flex items-center gap-1.5 rounded-lg px-2 py-2 text-[10px] font-semibold text-[#829087] transition-colors hover:bg-[#f1f4ef] hover:text-[#2e603d] dark:text-[#9eafa0] dark:hover:bg-[#223024] dark:hover:text-[#d9f579]" aria-label="Log out"><LogOut className="h-3.5 w-3.5" /><span className="hidden sm:inline">Log out</span></button></div></header>

        {activeView === 'My day' ? <div className="mx-auto max-w-[1320px] px-6 py-8 sm:px-10">
          <div className="flex flex-col justify-between gap-4 sm:flex-row sm:items-end"><div><p className="text-[10px] font-bold uppercase tracking-[0.2em] text-[#51865c]">{periodCopy[period].eyebrow}</p><h1 className="mt-2 text-3xl font-bold tracking-[-0.04em] sm:text-4xl">{period === 'This Q' ? `Hello, ${viewerName.trim().split(/\s+/)[0] || viewerName}` : periodCopy[period].title} <span className="text-[#8bb848]">✦</span></h1><p className="mt-2 text-sm text-[#78847b]">{periodCopy[period].subtitle}</p></div><div className="flex items-center gap-2 rounded-full border border-[#dfe8d7] bg-white px-3 py-2 text-[10px] font-semibold text-[#4b7853] shadow-sm dark:border-[#344635] dark:bg-[#1a231c] dark:text-[#c8e890]"><span className="h-2 w-2 rounded-full bg-[#23c16b]" /> All systems clear · data synced 12m ago</div></div>

          <div className="mt-6 flex flex-wrap items-center gap-2"><span className="mr-1 text-[10px] font-bold uppercase tracking-[0.14em] text-[#8a958b]">View lens</span>{(['This Q', 'Next Q'] as Period[]).map((item) => <button key={item} onClick={() => setPeriod(item)} className={`rounded-full px-3 py-1.5 text-[10px] font-bold transition ${period === item ? 'bg-[#203b29] text-[#d9f579] shadow-sm' : 'border border-[#dfe8d7] bg-white text-[#718077] hover:border-[#b6d874] dark:border-[#344635] dark:bg-[#1a231c] dark:text-[#c8d4c7]'}`}>{item === 'This Q' ? 'This Quarter' : item === 'Next Q' ? 'Next Quarter' : 'Fiscal Year'}</button>)}</div>

          {period === 'Next Q' ? <NextQuarterRunway data={nextData} /> : <section className="mt-8 grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
            {myDayCards.map(([label, value, meta, tone, Icon]) => { const c = toneClasses[label === 'Quota progress' || label === 'Forecast progress' ? overallTone : tone as Tone]; const I = Icon as typeof TrendingUp; return <div key={label} className={`rounded-2xl border p-4 ${c.card}`}><div className="flex items-center justify-between"><p className={`text-[10px] font-bold uppercase tracking-[0.14em] ${c.text}`}>{label}</p><I className={`h-4 w-4 ${c.text}`} /></div><p className="mt-4 text-2xl font-bold tracking-tight text-[#1a2a20] dark:text-white">{value}</p><p className={`mt-1 text-[11px] font-medium ${c.text}`}>{meta}</p></div> })}
          </section>}

          {period !== 'Next Q' && <DealsNeedingYou deals={liveDeals} />}

          {period !== 'Next Q' && <><section className="mt-5 rounded-2xl border border-[#dfe9b4] bg-[#f7fbdc] p-5 shadow-[0_8px_30px_rgba(33,54,37,0.04)] dark:border-[#526238] dark:bg-[#27321e]"><div className="flex flex-col justify-between gap-4 sm:flex-row sm:items-center"><div className="flex items-start gap-3"><div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-[#d9f579] text-[#31553b]">↗</div><div><p className="text-[10px] font-bold uppercase tracking-[0.16em] text-[#5d7c39] dark:text-[#d9f579]">{period === 'This Q' ? 'This week’s compass check' : period === 'Next Q' ? 'Next quarter runway' : 'Full-year compass check'}</p><h2 className="mt-1 text-sm font-bold text-[#243d2b] dark:text-white">{period === 'This Q' ? 'Create enough pipe to keep next quarter from becoming a plot twist.' : period === 'Next Q' ? 'Build quality pipe now, while there is still time to shape it.' : 'Keep signed revenue strong while creating the next wave of AI and New Business.'}</h2><p className="mt-1 max-w-2xl text-xs leading-relaxed text-[#6e7e63] dark:text-[#c6d2bd]">{periodCopy[period].focus} AI and New Business are the two motions worth checking before Friday—not because you’re behind, but because early pipe gives both motions room to mature.</p></div></div><div className="flex shrink-0 gap-2"><span className="rounded-full bg-white/75 px-3 py-2 text-[10px] font-bold text-[#6033bd] dark:bg-white/10 dark:text-[#d9caff]">AI · 3 active lines</span><span className="rounded-full bg-white/75 px-3 py-2 text-[10px] font-bold text-[#9c6500] dark:bg-white/10 dark:text-[#f5d68b]">NB · build coverage</span></div></div></section>

          <section className="mt-5 grid gap-5">
            <div className="rounded-2xl border border-[#e5ebe2] bg-white p-5 shadow-[0_8px_30px_rgba(33,54,37,0.04)] dark:border-[#29352b] dark:bg-[#1a231c]"><div className="flex items-start justify-between"><div><div className="flex items-center gap-2"><Sparkles className="h-4 w-4 text-[#8055e8]" /><h2 className="text-sm font-bold">Your next best moves</h2></div><p className="mt-1 text-xs text-[#879289]">Three actions with the clearest path to impact.</p></div><span className="rounded-full bg-[#f0f8d7] px-2.5 py-1 text-[10px] font-bold text-[#517344]">{liveDeals.length ? 'Live matched data' : 'Loading your deals'}</span></div><div className="mt-5 grid gap-3 md:grid-cols-3">{displayedDeals.slice(0, 3).map((item, index) => { const c = toneClasses[item.tone]; return <button key={item.name} onClick={() => setActiveDeal(index)} className={`rounded-xl border p-3 text-left transition hover:-translate-y-0.5 ${activeDeal === index ? 'ring-2 ring-[#b6d874]' : ''} ${c.card}`}><div className="flex items-center justify-between"><span className={`flex h-6 w-6 items-center justify-center rounded-lg bg-white/80 text-[10px] font-bold ${c.text}`}>{index + 1}</span><ArrowUpRight className={`h-3.5 w-3.5 ${c.text}`} /></div><p className="mt-3 truncate text-xs font-bold">{item.name}</p><p className={`mt-1 text-[10px] font-semibold ${c.text}`}>{item.action}</p><p className="mt-3 text-[10px] leading-relaxed text-[#738078]">{item.note}</p><a href={salesforceOpportunityUrl(item.crmOpportunityId) || salesforceSearchUrl(item.name)} target="_blank" rel="noreferrer" onClick={(e) => e.stopPropagation()} className={`mt-3 inline-flex items-center gap-1 text-[10px] font-bold ${c.text} hover:underline`}>Open in CRM <ArrowUpRight className="h-3 w-3" /></a></button> })}</div></div>
          </section>

              {period === 'This Q' && <section className="mt-5 rounded-2xl border border-[#e5ebe2] bg-white p-5 shadow-[0_8px_30px_rgba(33,54,37,0.04)] dark:border-[#29352b] dark:bg-[#1a231c]"><div className="flex items-start justify-between gap-4"><div><div className="flex items-center gap-2"><Gauge className="h-4 w-4 text-[#4b7853]" /><h2 className="text-sm font-bold">Cockpit</h2></div><p className="mt-1 text-xs text-[#879289]">A quick check of the signals we can verify from the current Salesforce data. Click any check to see the matching opportunities.</p></div><span className="rounded-full bg-[#fff8e7] px-2.5 py-1 text-[10px] font-bold text-[#9c6500]">3 checks</span></div><div className="mt-5 grid gap-3 sm:grid-cols-2 lg:grid-cols-3">{[['Close-plan watch', 'Early-stage close risk and pull-forward opportunities', 'rose'], ['Deal hygiene', 'Early-stage deals closing within 10 days, late-stage deals without quotes, or past-due close dates', 'amber'], ['Buying group readiness', '$100K+ deals with a blank Zendesk Executive Connect field', 'violet']].map(([title, description, tone]) => { const c = toneClasses[tone as Tone]; const count = liveCockpitRows(title, liveData.pipeline).length; const buyingGroupData = liveData.pipeline.some((row) => Object.prototype.hasOwnProperty.call(row, 'zendesk_executive_connect')); const quoteData = liveData.pipeline.some((row) => row.quote_status !== null && row.quote_status !== undefined); const unavailable = title === 'Buying group readiness' && !buyingGroupData; const partial = title === 'Deal hygiene' && !quoteData; return <button key={title} onClick={() => setActiveCockpit(title)} className={`rounded-xl border p-4 text-left transition hover:-translate-y-0.5 ${c.card} ${activeCockpit === title ? 'ring-2 ring-[#b6d874]' : ''}`}><div className="flex items-center justify-between"><p className={`text-[10px] font-bold uppercase tracking-[0.12em] ${c.text}`}>{title}</p><span className={`rounded-full bg-white/70 px-2 py-1 text-[9px] font-bold ${c.text} dark:bg-white/10`}>{count} {count === 1 ? 'opportunity' : 'opportunities'}</span></div><p className="mt-3 text-xs font-semibold text-[#36473b] dark:text-white">{description}</p><p className={`mt-3 text-[10px] font-bold ${c.text}`}>{unavailable ? 'View data note' : partial ? 'View coverage note' : count ? 'See matching deals' : 'View check'} <ArrowUpRight className="ml-1 inline h-3 w-3" /></p></button>})}</div></section>}{period === 'This Q' && activeCockpit && <CockpitDetail check={activeCockpit} onClose={() => setActiveCockpit(null)} pipeline={liveData.pipeline} />}


          </>}<div className="mt-5 flex flex-wrap items-center justify-between gap-3 rounded-xl border border-dashed border-[#cddbc7] bg-[#fbfdf8] px-4 py-3 text-[10px] text-[#78867b] dark:border-[#344635] dark:bg-[#172018]"><span className="flex items-center gap-2"><Users className="h-3.5 w-3.5 text-[#5c8a64]" /> {liveData.pipeline.length ? 'Matched to your profile and current-quarter data' : 'Reading your profile and current-quarter data'}</span><span className="flex items-center gap-1 font-semibold text-[#5c8a64]"><Calendar className="h-3 w-3" /> Source: Workday · Clari · GTMI · Salesforce</span></div>
        </div> : <CompassSecondaryView view={activeView} activeDeal={activeDeal} setActiveDeal={setActiveDeal} period={period} setPeriod={setPeriod} liveData={period === 'Next Q' ? nextData : liveData} fiscalYearData={fiscalYearData} />}
      </main>
      <FloatingCompass viewerName={viewerName} isAdmin={isAdmin} pipelineCount={liveData.pipeline.length} />
    </div>
  );
}
