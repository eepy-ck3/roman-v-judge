/**
 * app.js — Dashboard frontend logic
 *
 * Pure vanilla JS + Chart.js. No framework, no build step, no nonsense.
 * Fetches data from the FastAPI backend and renders everything dynamically.
 *
 * Data flow:
 *   /api/comparison  → main panel (stats, bet score, game logs)
 *   /api/schedule/*  → schedule panels (fetched separately to allow lazy loading)
 *   /api/trends/*    → chart data (fetched when chart tab is active)
 *   /api/odds        → MVP odds panel (included in comparison but also manual-updatable)
 */

// ─── Config ───────────────────────────────────────────────────────────────────

const REFRESH_INTERVAL_MS = 5 * 60 * 1000; // Refresh data every 5 minutes

// Stats to display in the head-to-head table, in order
const STAT_ROWS = [
  { key: 'avg',      label: 'AVG',    type: 'rate',    higher_is_better: true  },
  { key: 'obp',      label: 'OBP',    type: 'rate',    higher_is_better: true  },
  { key: 'slg',      label: 'SLG',    type: 'rate',    higher_is_better: true  },
  { key: 'ops',      label: 'OPS',    type: 'rate',    higher_is_better: true  },
  { key: 'wrc_plus', label: 'wRC+',   type: 'int',     higher_is_better: true  },
  { key: 'fwar',     label: 'fWAR',   type: 'decimal', higher_is_better: true  },
  { key: 'hr',       label: 'HR',     type: 'int',     higher_is_better: true  },
  { key: 'rbi',      label: 'RBI',    type: 'int',     higher_is_better: true  },
  { key: 'runs',     label: 'R',      type: 'int',     higher_is_better: true  },
  { key: 'hits',     label: 'H',      type: 'int',     higher_is_better: true  },
  { key: 'doubles',  label: '2B',     type: 'int',     higher_is_better: true  },
  { key: 'triples',  label: '3B',     type: 'int',     higher_is_better: true  },
  { key: 'sb',       label: 'SB',     type: 'int',     higher_is_better: true  },
  { key: 'bb',       label: 'BB',     type: 'int',     higher_is_better: true  },
  { key: 'k',        label: 'K',      type: 'int',     higher_is_better: false },
  { key: 'woba',     label: 'wOBA',   type: 'rate',    higher_is_better: true  },
  { key: 'games',    label: 'G',      type: 'int',     higher_is_better: true  },
];

// Chart metric options
const CHART_METRICS = [
  { key: 'ops',  label: 'OPS',  format: v => v.toFixed(3) },
  { key: 'hr',   label: 'HR',   format: v => v },
  { key: 'avg',  label: 'AVG',  format: v => v.toFixed(3) },
  { key: 'rbi',  label: 'RBI',  format: v => v },
];

// ─── State ────────────────────────────────────────────────────────────────────

let _data = null;           // Latest /api/comparison response
let _trendData = {};        // Cache for trend data by player+metric
let _activeChart = null;    // Current Chart.js instance
let _activeMetric = 'ops';  // Currently displayed chart metric

// ─── Init ─────────────────────────────────────────────────────────────────────

document.addEventListener('DOMContentLoaded', () => {
  loadAll();
  setInterval(loadAll, REFRESH_INTERVAL_MS);
});

async function loadAll() {
  try {
    _data = await fetchJSON('/api/comparison');
    if (_data) {
      renderBetBanner(_data);
      renderStatTable(_data);
      renderGameLogs(_data);
      renderOddsPanel(_data.odds);
      updateTimestamp();
    }
  } catch (e) {
    console.error('loadAll failed:', e);
    showError('stats-error', 'Failed to load stats. The server might be waking up — try again in 30 seconds.');
  }

  // Load schedules independently
  loadSchedule('roman');
  loadSchedule('judge');

  // Load initial chart
  loadTrends(_activeMetric);
}

// ─── Data Fetching ────────────────────────────────────────────────────────────

async function fetchJSON(url) {
  const resp = await fetch(url);
  if (!resp.ok) throw new Error(`HTTP ${resp.status} from ${url}`);
  return resp.json();
}

async function loadSchedule(player) {
  const el = document.getElementById(`schedule-${player}`);
  if (!el) return;
  el.innerHTML = loadingHTML('Loading schedule...');
  try {
    const data = await fetchJSON(`/api/schedule/${player}`);
    renderSchedulePanel(el, data, player);
  } catch (e) {
    el.innerHTML = `<div class="no-data">Schedule unavailable</div>`;
  }
}

async function loadTrends(metric) {
  _activeMetric = metric;

  // Update tab UI
  document.querySelectorAll('.chart-tab').forEach(t => {
    t.classList.toggle('active', t.dataset.metric === metric);
  });

  // Check cache first
  const cacheKey = `${metric}`;
  if (_trendData[cacheKey]) {
    renderChart(_trendData[cacheKey], metric);
    return;
  }

  // Fetch both players' trend data
  const container = document.getElementById('chart-container');
  if (container) container.innerHTML = loadingHTML('Loading chart...');

  try {
    const [romanTrend, judgeTrend] = await Promise.all([
      fetchJSON('/api/trends/roman'),
      fetchJSON('/api/trends/judge'),
    ]);
    _trendData[cacheKey] = { roman: romanTrend.data, judge: judgeTrend.data };
    renderChart(_trendData[cacheKey], metric);
  } catch (e) {
    if (container) container.innerHTML = `<div class="no-data">Chart data unavailable</div>`;
  }
}

// ─── Renderers ────────────────────────────────────────────────────────────────

function renderBetBanner(data) {
  const { roman, judge, bet_score, team_colors } = data;
  const romanName = roman.info?.name || 'Roman Anthony';
  const judgeName = judge.info?.name || 'Aaron Judge';
  const romanColor = team_colors?.roman || '#BD3039';
  const judgeColor = team_colors?.judge || '#003087';

  const romanScore = bet_score.roman || 0;
  const judgeScore = bet_score.judge || 0;
  const leader = bet_score.leader || 'tied';

  // Score bar: roman fills left side
  const romanPct = romanScore;

  const leaderBadge = leader === 'roman'
    ? `<span class="bet-leader-badge roman">🔴 Roman Leads</span>`
    : leader === 'judge'
    ? `<span class="bet-leader-badge judge">⚫ Judge Leads</span>`
    : `<span class="bet-leader-badge tied">🤝 Too Close to Call</span>`;

  const banner = document.getElementById('bet-banner');
  if (!banner) return;

  banner.innerHTML = `
    <div class="bet-banner-inner">
      <!-- Roman side -->
      <div class="bet-player roman">
        <div class="bet-player-header">
          <img class="headshot roman" src="${roman.info?.headshot_url || ''}"
               onerror="this.src='/static/placeholder.png'" alt="${romanName}">
          <div>
            <div class="bet-player-name text-roman">${romanName}</div>
            <div class="bet-player-team">${roman.info?.team || 'Boston Red Sox'} · ${roman.info?.position || 'OF'}</div>
          </div>
        </div>
        <div class="bet-score-value roman">${romanScore}</div>
        <div class="text-xs text-muted">bet score</div>
      </div>

      <!-- Center bar -->
      <div class="score-bar-container">
        <div class="score-bar-label">Who's Winning?</div>
        <div class="score-bar">
          <!-- The fill width represents Roman's share -->
          <div class="score-bar-fill" style="width: ${romanPct}%; background: linear-gradient(90deg, ${romanColor}, ${judgeColor})"></div>
        </div>
        <div class="score-bar-labels">
          <span class="text-roman">Roman</span>
          <span style="color: #4b74cc">Judge</span>
        </div>
        ${leaderBadge}
        <div class="text-xs text-muted mt-4">
          Based on fWAR, wRC+, HR, OPS, RBI, Runs, SB
        </div>
      </div>

      <!-- Judge side -->
      <div class="bet-player judge">
        <div class="bet-player-header">
          <div style="text-align: right">
            <div class="bet-player-name" style="color: #4b74cc">${judgeName}</div>
            <div class="bet-player-team">${judge.info?.team || 'New York Yankees'} · ${judge.info?.position || 'RF'}</div>
          </div>
          <img class="headshot judge" src="${judge.info?.headshot_url || ''}"
               onerror="this.src='/static/placeholder.png'" alt="${judgeName}">
        </div>
        <div class="bet-score-value judge">${judgeScore}</div>
        <div class="text-xs text-muted">bet score</div>
      </div>
    </div>
  `;
}

function renderStatTable(data) {
  const { roman, judge, bet_score } = data;
  const romanStats = { ...roman.season_stats };
  const judgeStats = { ...judge.season_stats };
  const categories = bet_score.categories || {};

  const tbody = document.getElementById('stat-table-body');
  if (!tbody) return;

  const rows = STAT_ROWS
    .filter(row => {
      // Skip rows where both values are null/undefined
      const rv = romanStats[row.key];
      const jv = judgeStats[row.key];
      return rv !== null && rv !== undefined && jv !== null && jv !== undefined;
    })
    .map(row => {
      const rv = romanStats[row.key];
      const jv = judgeStats[row.key];
      const romanVal = formatStatVal(rv, row.type);
      const judgeVal = formatStatVal(jv, row.type);

      // Determine who leads
      const rNum = parseFloat(String(rv).replace(/[^0-9.-]/g, '')) || 0;
      const jNum = parseFloat(String(jv).replace(/[^0-9.-]/g, '')) || 0;
      const romanWins = row.higher_is_better ? rNum > jNum : rNum < jNum;
      const judgeWins = row.higher_is_better ? jNum > rNum : jNum < rNum;

      const rClass = romanWins ? 'val-leading roman' : '';
      const jClass = judgeWins ? 'val-leading judge' : '';
      const rArrow = romanWins ? '<span class="arrow up">▲</span>' : '';
      const jArrow = judgeWins ? '<span class="arrow up">▲</span>' : '';

      return `
        <tr>
          <td class="roman-val ${rClass}">${romanVal}${rArrow}</td>
          <td class="stat-name">${row.label}</td>
          <td class="judge-val ${jClass}">${jArrow}${judgeVal}</td>
        </tr>
      `;
    })
    .join('');

  tbody.innerHTML = rows || '<tr><td colspan="3" class="no-data">Stats loading...</td></tr>';
}

function renderGameLogs(data) {
  renderPlayerGameLog('roman', data.roman.recent_games || []);
  renderPlayerGameLog('judge', data.judge.recent_games || []);
}

function renderPlayerGameLog(player, games) {
  const el = document.getElementById(`gamelog-${player}`);
  if (!el) return;

  if (!games.length) {
    el.innerHTML = '<div class="no-data">No recent game data</div>';
    return;
  }

  el.innerHTML = games.map(g => `
    <div class="game-row">
      <div class="game-date">${formatDate(g.date)}</div>
      <div class="game-matchup">
        <span class="game-ha">${g.home_away}</span>
        <span class="game-opponent"> ${g.opponent || 'TBD'}</span>
        <div class="game-stats">
          ${g.hits ?? '–'}/${g.ab ?? '–'} · ${g.hr ?? 0} HR · ${g.rbi ?? 0} RBI · ${formatStatVal(g.avg, 'rate')} AVG
        </div>
      </div>
      <div>
        <div class="game-result ${g.result?.startsWith('W') ? 'win' : g.result?.startsWith('L') ? 'loss' : ''}">
          ${g.result || '—'}
        </div>
      </div>
    </div>
  `).join('');
}

function renderSchedulePanel(el, data, player) {
  const upcoming = data.upcoming || [];
  const recent = data.recent || [];
  const isRoman = player === 'roman';
  const color = isRoman ? 'roman' : 'judge';

  el.innerHTML = `
    <div class="schedule-section">
      <div class="schedule-section-title">Upcoming Games</div>
      ${upcoming.length ? upcoming.map(g => upcomingGameHTML(g)).join('') : '<div class="no-data">No upcoming games</div>'}
    </div>
    <div class="schedule-section">
      <div class="schedule-section-title">Recent Results</div>
      ${recent.length ? recent.map(g => recentGameHTML(g)).join('') : '<div class="no-data">No recent games</div>'}
    </div>
  `;
}

function upcomingGameHTML(g) {
  return `
    <div class="game-row">
      <div class="game-date">${formatDate(g.date)}</div>
      <div class="game-matchup">
        <span class="game-ha">${g.home_away}</span>
        <span class="game-opponent"> ${g.opponent}</span>
        ${g.opposing_pitcher && g.opposing_pitcher !== 'TBD'
          ? `<div class="game-pitcher">vs SP: ${g.opposing_pitcher}</div>`
          : ''}
      </div>
      <div class="game-time">${g.time}</div>
    </div>
  `;
}

function recentGameHTML(g) {
  const isWin = g.result?.startsWith('W');
  const isLoss = g.result?.startsWith('L');
  return `
    <div class="game-row">
      <div class="game-date">${formatDate(g.date)}</div>
      <div class="game-matchup">
        <span class="game-ha">${g.home_away}</span>
        <span class="game-opponent"> ${g.opponent}</span>
      </div>
      <div class="game-result ${isWin ? 'win' : isLoss ? 'loss' : ''}">${g.result || '—'}</div>
    </div>
  `;
}

function renderOddsPanel(odds) {
  if (!odds) return;

  const judgeOdds = odds.judge || {};
  const romanOdds = odds.roman || {};

  // Odds cards
  const judgeEl = document.getElementById('odds-judge');
  const romanEl = document.getElementById('odds-roman');

  if (judgeEl) {
    judgeEl.querySelector('.odds-value').textContent = judgeOdds.odds || 'N/A';
    judgeEl.querySelector('.odds-prob').textContent =
      judgeOdds.implied_prob ? `${judgeOdds.implied_prob}% implied` : '';
    const srcEl = judgeEl.querySelector('.odds-source');
    if (srcEl) srcEl.textContent = judgeOdds.source === 'manual' ? '(manual entry)' : '(live odds)';
  }

  if (romanEl) {
    romanEl.querySelector('.odds-value').textContent = romanOdds.odds || 'N/A';
    romanEl.querySelector('.odds-prob').textContent =
      romanOdds.implied_prob ? `${romanOdds.implied_prob}% implied` : '';
    const srcEl = romanEl.querySelector('.odds-source');
    if (srcEl) srcEl.textContent = romanOdds.source === 'manual' ? '(manual entry)' : '(live odds)';
  }

  // Leaderboard
  const lbEl = document.getElementById('mvp-leaderboard');
  if (lbEl && odds.leaderboard?.length) {
    lbEl.innerHTML = odds.leaderboard.map((p, i) => {
      const isOurPlayer = p.name?.toLowerCase().includes('judge') ||
                          p.name?.toLowerCase().includes('anthony');
      return `
        <div class="leaderboard-row ${isOurPlayer ? 'lb-highlight' : ''}">
          <span class="lb-rank">${i + 1}</span>
          <span class="lb-name">${p.name}</span>
          <div class="lb-bar">
            <div class="lb-bar-fill" style="width: ${Math.min(100, p.implied_prob * 4)}%"></div>
          </div>
          <span class="lb-odds">${p.odds}</span>
          <span class="lb-prob">${p.implied_prob}%</span>
        </div>
      `;
    }).join('');
  } else if (lbEl) {
    lbEl.innerHTML = '<div class="no-data text-xs">Leaderboard unavailable — odds API returned manual fallback only</div>';
  }
}

function renderChart(trendData, metric) {
  const container = document.getElementById('chart-container');
  if (!container) return;

  // Destroy existing chart
  if (_activeChart) {
    _activeChart.destroy();
    _activeChart = null;
  }

  const romanData = trendData.roman || [];
  const judgeData = trendData.judge || [];

  if (!romanData.length && !judgeData.length) {
    container.innerHTML = '<div class="no-data">No trend data available yet — check back once the season is underway</div>';
    return;
  }

  container.innerHTML = '<canvas id="trend-chart"></canvas>';
  const ctx = document.getElementById('trend-chart').getContext('2d');

  const metricConfig = CHART_METRICS.find(m => m.key === metric) || CHART_METRICS[0];

  _activeChart = new Chart(ctx, {
    type: 'line',
    data: {
      datasets: [
        {
          label: 'Roman Anthony',
          data: romanData.map(d => ({ x: d.date, y: d[metric] })),
          borderColor: '#BD3039',
          backgroundColor: 'rgba(189, 48, 57, 0.08)',
          borderWidth: 2.5,
          pointRadius: 0,
          pointHoverRadius: 5,
          pointHoverBackgroundColor: '#BD3039',
          tension: 0.3,
          fill: false,
        },
        {
          label: 'Aaron Judge',
          data: judgeData.map(d => ({ x: d.date, y: d[metric] })),
          borderColor: '#4b74cc',
          backgroundColor: 'rgba(75, 116, 204, 0.08)',
          borderWidth: 2.5,
          pointRadius: 0,
          pointHoverRadius: 5,
          pointHoverBackgroundColor: '#4b74cc',
          tension: 0.3,
          fill: false,
        },
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      interaction: { mode: 'index', intersect: false },
      plugins: {
        legend: {
          labels: {
            color: '#a0a0a0',
            font: { size: 12 },
            boxWidth: 16,
          },
        },
        tooltip: {
          backgroundColor: '#1e1e1e',
          borderColor: '#3a3a3a',
          borderWidth: 1,
          titleColor: '#f0f0f0',
          bodyColor: '#a0a0a0',
          callbacks: {
            label: ctx => `${ctx.dataset.label}: ${metricConfig.format(ctx.parsed.y)}`,
          },
        },
      },
      scales: {
        x: {
          type: 'time',
          time: { unit: 'week', displayFormats: { week: 'MMM d' } },
          grid: { color: '#1e1e1e' },
          ticks: { color: '#666', maxTicksLimit: 8 },
        },
        y: {
          grid: { color: '#1e1e1e' },
          ticks: {
            color: '#666',
            callback: v => metricConfig.format(v),
          },
        },
      },
    },
  });
}

// ─── Manual Odds Update ───────────────────────────────────────────────────────

async function refreshOdds(btn) {
  const original = btn.textContent;
  btn.textContent = '...';
  btn.disabled = true;
  try {
    const odds = await fetchJSON('/api/odds/refresh');
    renderOddsPanel(odds);
    const src = odds.judge?.source === 'odds_api' ? 'Live odds loaded!' : 'Refreshed — using manual fallback (API had no futures market)';
    showToast(src, odds.judge?.source === 'odds_api' ? 'success' : 'error');
  } catch (e) {
    showToast('Failed to refresh odds', 'error');
  } finally {
    btn.textContent = original;
    btn.disabled = false;
  }
}

async function updateOddsManually() {
  const judgeOdds = document.getElementById('manual-judge-odds')?.value?.trim();
  const romanOdds = document.getElementById('manual-roman-odds')?.value?.trim();

  if (!judgeOdds || !romanOdds) {
    showToast('Enter odds for both players (e.g. +200 or -150)', 'error');
    return;
  }

  try {
    await fetch('/api/odds/manual', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ judge_odds: judgeOdds, roman_odds: romanOdds }),
    });

    // Refresh the odds display
    const odds = await fetchJSON('/api/odds');
    renderOddsPanel(odds);
    showToast('Odds updated!', 'success');
  } catch (e) {
    showToast('Failed to update odds', 'error');
  }
}

async function triggerReport() {
  try {
    await fetch('/api/trigger-report', { method: 'POST' });
    showToast('Weekly report triggered! Check your email + phone.', 'success');
  } catch (e) {
    showToast('Failed to trigger report', 'error');
  }
}

// ─── Utility ──────────────────────────────────────────────────────────────────

function formatStatVal(val, type) {
  if (val === null || val === undefined) return 'N/A';
  switch (type) {
    case 'rate':
      // Already formatted as ".285" string from the API
      return String(val);
    case 'decimal':
      return typeof val === 'number' ? val.toFixed(1) : String(val);
    case 'int':
      return String(Math.round(Number(val) || 0));
    default:
      return String(val);
  }
}

function formatDate(dateStr) {
  if (!dateStr) return '—';
  try {
    const d = new Date(dateStr + 'T12:00:00');  // Noon to avoid timezone shift
    return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
  } catch {
    return dateStr;
  }
}

function updateTimestamp() {
  const el = document.getElementById('last-updated');
  if (el) {
    el.textContent = `Last updated: ${new Date().toLocaleTimeString()}`;
  }
}

function loadingHTML(msg = 'Loading...') {
  return `<div class="loading"><div class="spinner"></div>${msg}</div>`;
}

function showError(id, msg) {
  const el = document.getElementById(id);
  if (el) el.innerHTML = `<div class="error-msg">${msg}</div>`;
}

function showToast(msg, type = 'success') {
  const container = document.getElementById('toast-container');
  if (!container) return;

  const toast = document.createElement('div');
  toast.className = `toast ${type}`;
  toast.textContent = msg;
  container.appendChild(toast);

  setTimeout(() => toast.remove(), 4000);
}
