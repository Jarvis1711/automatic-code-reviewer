const form = document.getElementById('review-form');
const statusBox = document.getElementById('status');
const submitBtn = document.getElementById('submit-btn');
const resultsRoot = document.getElementById('results-root');

function renderLiveProgress(job) {
  const statuses = job.model_statuses || [];
  const stage = job.stage || 'queued';
  const progress = job.progress ?? 0;

  const statusMeta = {
    queued: {
      dot: 'bg-slate-500',
      badge: 'border-slate-600 text-slate-300',
      icon: '⏳',
      pulse: ''
    },
    running: {
      dot: 'bg-violet-400',
      badge: 'border-violet-500/50 text-violet-200',
      icon: '⟳',
      pulse: 'animate-pulse'
    },
    completed: {
      dot: 'bg-emerald-400',
      badge: 'border-emerald-500/50 text-emerald-200',
      icon: '✓',
      pulse: ''
    },
    failed: {
      dot: 'bg-rose-400',
      badge: 'border-rose-500/50 text-rose-200',
      icon: '⚠',
      pulse: ''
    },
    unavailable: {
      dot: 'bg-amber-400',
      badge: 'border-amber-500/50 text-amber-200',
      icon: '—',
      pulse: ''
    }
  };

  const items = statuses.map(item => {
    const meta = statusMeta[item.status] || statusMeta.queued;
    const spin = item.status === 'running' ? 'animate-spin' : '';
    return `
      <div class="rounded-lg border ${meta.badge} bg-slate-950/70 px-3 py-2 text-xs">
        <div class="flex items-center justify-between gap-2">
          <span class="font-medium text-slate-100">${item.name}</span>
          <span class="inline-flex items-center gap-1 rounded-full border border-current/40 px-2 py-0.5 uppercase ${meta.pulse}">
            <span class="inline-block ${spin}">${meta.icon}</span>
            ${item.status}
          </span>
        </div>
        <div class="mt-2 h-1.5 rounded-full bg-slate-800">
          <div class="h-1.5 rounded-full ${meta.dot} ${meta.pulse}" style="width:${item.status === 'completed' ? '100' : item.status === 'running' ? '70' : item.status === 'failed' ? '100' : '20'}%"></div>
        </div>
      </div>
    `;
  }).join('');

  const panel = `
    <section id="live-progress" class="rounded-2xl border border-violet-500/30 bg-violet-500/5 p-5">
      <div class="flex items-center justify-between gap-4">
        <div>
          <h3 class="text-lg font-semibold text-violet-100">Live Model Execution</h3>
          <p class="text-xs text-violet-200/80">Stage: ${stage.replaceAll('_', ' ')}</p>
        </div>
        <div class="min-w-28 rounded-lg border border-violet-500/40 bg-slate-900 px-3 py-2 text-right">
          <p class="text-[10px] uppercase tracking-wide text-slate-400">Progress</p>
          <p class="text-lg font-bold text-violet-100">${progress}%</p>
        </div>
      </div>
      <div class="mt-4 grid gap-2 md:grid-cols-2">${items || '<p class="text-sm text-slate-300">Preparing model queue...</p>'}</div>
    </section>
  `;

  const current = document.getElementById('live-progress');
  if (current) {
    current.outerHTML = panel;
  } else {
    resultsRoot.insertAdjacentHTML('afterbegin', panel);
  }
}

function setStatus(message, kind = 'info') {
  statusBox.classList.remove('hidden');
  statusBox.textContent = message;
  statusBox.className = 'mt-5 rounded-xl border px-4 py-3 text-sm';
  if (kind === 'error') {
    statusBox.classList.add('border-rose-500/40', 'bg-rose-500/10', 'text-rose-200');
  } else if (kind === 'success') {
    statusBox.classList.add('border-emerald-500/40', 'bg-emerald-500/10', 'text-emerald-200');
  } else {
    statusBox.classList.add('border-slate-700', 'bg-slate-800/70', 'text-slate-200');
  }
}

function renderReport(data) {
  const findings = data.key_findings || [];
  const modelReviews = data.model_reviews || [];
  const topFindings = findings.map(issue => {
    const severityColor = {
      critical: 'text-rose-300 border-rose-500/40 bg-rose-500/10',
      high: 'text-orange-300 border-orange-500/40 bg-orange-500/10',
      medium: 'text-amber-300 border-amber-500/40 bg-amber-500/10',
      low: 'text-sky-300 border-sky-500/40 bg-sky-500/10'
    }[issue.severity] || 'text-slate-300 border-slate-700 bg-slate-800';

    return `
      <article class="rounded-xl border ${severityColor} p-4">
        <div class="flex items-start justify-between gap-4">
          <h4 class="font-semibold">${issue.title}</h4>
          <span class="rounded-full border border-current/40 px-2 py-0.5 text-xs uppercase">${issue.severity}</span>
        </div>
        <p class="mt-2 text-sm opacity-90">${issue.rationale}</p>
        <p class="mt-2 text-xs opacity-80">${issue.file}${issue.line ? `:${issue.line}` : ''} • ${issue.category}</p>
        <p class="mt-2 text-sm"><strong>Action:</strong> ${issue.suggestion}</p>
      </article>
    `;
  }).join('');

  const modelCards = modelReviews.map(model => `
    <article class="rounded-xl border border-slate-800 bg-slate-900/80 p-4">
      <div class="flex items-center justify-between">
        <h4 class="font-semibold">${model.model_name}</h4>
        <span class="text-xs ${model.enabled ? 'text-emerald-300' : 'text-slate-400'}">${model.enabled ? 'Active' : 'Unavailable'}</span>
      </div>
      <p class="mt-1 text-xs text-slate-400">Family: ${model.family}</p>
      <p class="mt-3 text-sm text-slate-300">${model.summary || model.error || 'No details'}</p>
      <p class="mt-3 text-xs text-slate-400">Risk score: ${model.risk_score ?? 'n/a'}</p>
    </article>
  `).join('');

  const quickWins = (data.quick_wins || []).map(item => `<li>• ${item}</li>`).join('');

  resultsRoot.innerHTML = `
    <section class="rounded-2xl border border-slate-800 bg-slate-900/80 p-6">
      <div class="flex flex-wrap items-center justify-between gap-4">
        <div>
          <h2 class="text-2xl font-bold">${data.repository}</h2>
          <p class="mt-1 text-sm text-slate-400">Branch: ${data.branch} • Commit: ${data.commit.slice(0, 10)}</p>
        </div>
        <div class="rounded-xl border border-violet-500/40 bg-violet-500/10 px-4 py-2 text-right">
          <p class="text-xs text-violet-200">Overall Risk</p>
          <p class="text-2xl font-bold text-violet-100">${data.overall_risk_score}/100</p>
        </div>
      </div>
      <p class="mt-5 text-slate-200">${data.executive_summary}</p>
      <div class="mt-5 grid gap-4 md:grid-cols-2">
        <div class="rounded-xl border border-slate-800 bg-slate-950 p-4">
          <p class="text-sm font-semibold">Coverage</p>
          <p class="mt-2 text-xs text-slate-400">Models responded: ${data.coverage.models_responded}/${data.coverage.models_attempted}</p>
          <p class="mt-1 text-xs text-slate-400">Files analyzed: ${data.coverage.files_analyzed}</p>
          <p class="mt-1 text-xs text-slate-400">Languages: ${Object.keys(data.coverage.languages || {}).join(', ') || 'n/a'}</p>
        </div>
        <div class="rounded-xl border border-slate-800 bg-slate-950 p-4">
          <p class="text-sm font-semibold">Quick Wins</p>
          <ul class="mt-2 space-y-1 text-xs text-slate-300">${quickWins || '<li>• No quick wins generated</li>'}</ul>
        </div>
      </div>
      <div class="mt-6 flex flex-wrap gap-3">
        <button id="download-md" class="rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-sm hover:bg-slate-800">Download Markdown Report</button>
      </div>
    </section>

    <section class="rounded-2xl border border-slate-800 bg-slate-900/70 p-6">
      <h3 class="text-xl font-semibold">Consensus Findings</h3>
      <div class="mt-4 grid gap-4">${topFindings || '<p class="text-slate-400">No findings reported.</p>'}</div>
    </section>

    <section class="rounded-2xl border border-slate-800 bg-slate-900/70 p-6">
      <h3 class="text-xl font-semibold">Model Perspectives</h3>
      <div class="mt-4 grid gap-4 md:grid-cols-2">${modelCards}</div>
    </section>
  `;

  const downloadBtn = document.getElementById('download-md');
  downloadBtn?.addEventListener('click', () => {
    const blob = new Blob([data.markdown_report || 'No markdown report'], { type: 'text/markdown;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement('a');
    anchor.href = url;
    anchor.download = `${data.repository || 'review-report'}.md`;
    document.body.appendChild(anchor);
    anchor.click();
    anchor.remove();
    URL.revokeObjectURL(url);
  });
}

form.addEventListener('submit', async (event) => {
  event.preventDefault();
  submitBtn.disabled = true;
  setStatus('Queued review job...');

  const payload = {
    repo_url: document.getElementById('repo-url').value.trim(),
    branch: document.getElementById('branch').value.trim() || null
  };

  try {
    const response = await fetch('/api/review/start', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });

    if (!response.ok) {
      const errorPayload = await response.json();
      throw new Error(errorPayload.detail || 'Failed to generate report');
    }

    const { job_id: jobId } = await response.json();
    if (!jobId) {
      throw new Error('Failed to start review job');
    }

    resultsRoot.innerHTML = `
      <section class="rounded-2xl border border-slate-800 bg-slate-900/80 p-6">
        <h3 class="text-xl font-semibold">Review in progress</h3>
        <p class="mt-2 text-sm text-slate-300">Models are running in the background. This panel updates live as each model completes.</p>
      </section>
    `;

    let attempts = 0;
    while (attempts < 300) {
      attempts += 1;
      const statusResponse = await fetch(`/api/review/${jobId}`);
      if (!statusResponse.ok) {
        throw new Error('Failed to fetch review progress');
      }
      const job = await statusResponse.json();

      renderLiveProgress(job);

      if (job.partial_report) {
        renderReport(job.partial_report);
        renderLiveProgress(job);
      }

      if (job.status === 'completed' && job.report) {
        renderReport(job.report);
        renderLiveProgress(job);
        setStatus('Review completed successfully.', 'success');
        break;
      }

      if (job.status === 'failed') {
        throw new Error(job.error || 'Review job failed');
      }

      const done = job.completed_models ?? 0;
      const total = job.total_models ?? 0;
      const progress = job.progress ?? 0;
      setStatus(`Running models... ${done}/${total} completed (${progress}%). Stage: ${job.stage}`);
      await new Promise(resolve => setTimeout(resolve, 1400));
    }

    if (attempts >= 300) {
      throw new Error('Review timed out while waiting for model results.');
    }
  } catch (error) {
    setStatus(error.message || 'Unexpected error while generating review.', 'error');
  } finally {
    submitBtn.disabled = false;
  }
});
