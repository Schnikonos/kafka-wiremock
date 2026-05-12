import { Injectable } from '@angular/core';

@Injectable({ providedIn: 'root' })
export class ExportService {

  // ─── Core download helpers ────────────────────────────────────────────────────

  private triggerDownload(filename: string, content: string, mimeType: string): void {
    const blob = new Blob([content], { type: mimeType });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = filename;
    a.style.display = 'none';
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  }

  downloadJson(filename: string, data: any): void {
    this.triggerDownload(filename, JSON.stringify(data, null, 2), 'application/json');
  }

  downloadCsv(filename: string, headers: string[], rows: (string | number | null | undefined)[][]): void {
    const escapeCell = (v: any): string => {
      const s = v === null || v === undefined ? '' : String(v);
      if (s.includes(',') || s.includes('"') || s.includes('\n') || s.includes('\r')) {
        return '"' + s.replace(/"/g, '""') + '"';
      }
      return s;
    };
    const lines = [
      headers.map(escapeCell).join(','),
      ...rows.map(row => row.map(escapeCell).join(','))
    ];
    this.triggerDownload(filename, lines.join('\r\n'), 'text/csv;charset=utf-8;');
  }

  downloadHtml(filename: string, html: string): void {
    this.triggerDownload(filename, html, 'text/html;charset=utf-8;');
  }

  // ─── HTML escape ──────────────────────────────────────────────────────────────

  private esc(s: any): string {
    if (s === null || s === undefined) return '';
    return String(s)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
  }

  // ─── Shared CSS ───────────────────────────────────────────────────────────────

  private commonCss(): string {
    return `
  body { font-family: Arial, sans-serif; margin: 0; padding: 24px; background: #f5f5f5; color: #333; }
  h1 { margin: 0 0 4px 0; }
  h2 { font-size: 16px; margin: 24px 0 12px 0; }
  .subtitle { color: #666; font-size: 14px; margin-bottom: 20px; }
  .stats { display: flex; gap: 16px; margin-bottom: 24px; flex-wrap: wrap; }
  .stat { background: #fff; border-radius: 8px; padding: 12px 20px; box-shadow: 0 1px 4px rgba(0,0,0,.1); text-align: center; min-width: 80px; }
  .stat-label { font-size: 11px; color: #999; text-transform: uppercase; font-weight: 600; display: block; }
  .stat-value { font-size: 24px; font-weight: 700; display: block; }
  .badge { padding: 2px 8px; border-radius: 4px; font-size: 12px; font-weight: 600; }
  pre { background: #1e1e1e; color: #d4d4d4; padding: 10px; border-radius: 4px; font-size: 11px;
        margin: 4px 0; overflow-x: auto; white-space: pre-wrap; word-break: break-all;
        max-height: 200px; overflow-y: auto; }`;
  }

  /** CSS for collapsible <details> entries and shared run-detail sections. */
  private collapsibleCss(): string {
    return `
    details.log-entry { background: #fff; border-radius: 8px; margin-bottom: 10px; box-shadow: 0 1px 4px rgba(0,0,0,.08); overflow: hidden; }
    details.log-entry > summary { cursor: pointer; padding: 12px 16px; list-style: none; display: flex; align-items: center; gap: 12px; user-select: none; font-weight: 600; }
    details.log-entry > summary::-webkit-details-marker { display: none; }
    details.log-entry > summary::before { content: '▶'; font-size: 10px; color: #999; flex-shrink: 0; transition: transform 0.15s; }
    details.log-entry[open] > summary::before { transform: rotate(90deg); }
    .test-id { font-size: 15px; color: #1976d2; flex: 1; }
    .timing { font-size: 12px; color: #888; background: #f5f5f5; padding: 2px 8px; border-radius: 3px; }
    .run-count { font-size: 11px; color: #aaa; }
    .log-body { padding: 16px; border-top: 1px solid #f0f0f0; }
    .section { margin-bottom: 16px; }
    .section h4 { margin: 0 0 8px 0; font-size: 12px; color: #666; font-weight: 600; text-transform: uppercase; letter-spacing: 0.5px; }
    .errors-section { background: #fff8f8; padding: 12px; border-radius: 4px; border-left: 3px solid #ef9a9a; }
    .errors-section ul { margin: 0; padding-left: 16px; }
    .errors-section li { color: #b71c1c; font-size: 13px; margin-bottom: 4px; }
    .exp-row { display: flex; align-items: center; gap: 10px; padding: 4px 0; font-size: 13px; }
    .exp-topic { color: #1976d2; font-weight: 500; flex: 1; }
    .exp-counts { color: #666; font-size: 12px; }
    .msg { border: 1px solid #eee; border-radius: 4px; padding: 10px; margin-bottom: 8px; }
    .msg.sent     { border-left: 3px solid #42a5f5; }
    .msg.received { border-left: 3px solid #66bb6a; }
    .msg-topic { font-size: 12px; font-weight: 600; color: #555; margin-bottom: 6px; display: flex; align-items: center; gap: 8px; }
    .failed-cond { font-size: 12px; color: #c62828; margin-top: 4px; }
    .failed-cond code { background: #f5f5f5; padding: 1px 4px; border-radius: 3px; }
    .closest-section { background: #fffde7; padding: 12px; border-radius: 4px; border-left: 3px solid #ffd54f; }
    .no-data { color: #aaa; font-style: italic; font-size: 13px; }`;
  }

  private statusColor(s: string): string {
    switch ((s || '').toUpperCase()) {
      case 'PASSED':   return '#2e7d32';
      case 'FAILED':   return '#c62828';
      case 'SKIPPED':  return '#e65100';
      case 'TIMEOUT':  return '#6a1b9a';
      default:         return '#555';
    }
  }

  private statusBg(s: string): string {
    switch ((s || '').toUpperCase()) {
      case 'PASSED':   return '#c8e6c9';
      case 'FAILED':   return '#ffcdd2';
      case 'SKIPPED':  return '#ffe0b2';
      case 'TIMEOUT':  return '#e1bee7';
      default:         return '#eeeeee';
    }
  }

  private badgeHtml(status: string): string {
    return `<span class="badge" style="background:${this.statusBg(status)};color:${this.statusColor(status)}">${this.esc(status)}</span>`;
  }

  // ─── Shared run-detail renderer ───────────────────────────────────────────────

  /** Render the body sections (errors, expectations, messages…) for a single run object. */
  private buildRunDetailSections(run: any): string {
    if (!run) return '';

    const errorsHtml = (run.errors?.length)
      ? `<div class="section errors-section">
           <h4>Errors</h4>
           <ul>${run.errors.map((e: string) => `<li>${this.esc(e)}</li>`).join('')}</ul>
         </div>`
      : '';

    const expHtml = (run.expectations?.length)
      ? `<div class="section">
           <h4>Expectations</h4>
           ${run.expectations.map((exp: any) => `
             <div class="exp-row">
               <span class="exp-topic">${this.esc(exp.topic || '')}</span>
               ${this.badgeHtml(exp.status || '')}
               <span class="exp-counts">received ${exp.received}/${exp.expected}</span>
               <span class="timing">${exp.elapsed_ms}ms</span>
             </div>`).join('')}
         </div>`
      : '';

    const sentHtml = (run.sent_messages?.length)
      ? `<div class="section">
           <h4>Sent Messages (${run.sent_messages.length})</h4>
           ${run.sent_messages.map((msg: any) => `
             <div class="msg sent">
               <div class="msg-topic">→ ${this.esc(msg.topic || '')}</div>
               <pre>${this.esc(JSON.stringify(msg.payload, null, 2))}</pre>
               ${msg.headers ? `<div style="font-size:11px;color:#888;margin-top:4px">Headers: ${this.esc(JSON.stringify(msg.headers))}</div>` : ''}
             </div>`).join('')}
         </div>`
      : '';

    const recvHtml = (run.received_messages?.length)
      ? `<div class="section">
           <h4>Received Messages (${run.received_messages.length})</h4>
           ${run.received_messages.map((msg: any) => {
             const condOk = msg.conditions_matched === msg.total_conditions;
             const condBadge = msg.conditions_matched !== undefined
               ? `<span style="background:${condOk ? '#c8e6c9' : '#ffcdd2'};color:${condOk ? '#1b5e20' : '#b71c1c'};padding:1px 5px;border-radius:3px;font-size:11px;">${msg.conditions_matched}/${msg.total_conditions} cond</span>`
               : '';
             const failedConds = (msg.failed_conditions?.length)
               ? `<div class="failed-cond"><strong>Failed:</strong> ${msg.failed_conditions.map((fc: any) =>
                   `<code>${this.esc(fc.type)}${fc.expression ? ' ' + this.esc(fc.expression) : ''}</code>`).join(', ')}</div>`
               : '';
             return `
               <div class="msg received">
                 <div class="msg-topic">← ${this.esc(msg.topic || '')} ${condBadge}</div>
                 <pre>${this.esc(JSON.stringify(msg.payload, null, 2))}</pre>
                 ${failedConds}
               </div>`;
           }).join('')}
         </div>`
      : '';

    const closestHtml = run.closest_match
      ? `<div class="section closest-section">
           <h4>Closest Match (${this.esc(run.closest_match.tier_name || '')})</h4>
           <pre>${this.esc(JSON.stringify(run.closest_match.message?.payload, null, 2))}</pre>
         </div>`
      : '';

    const rawHtml = run.raw
      ? `<div class="section"><pre>${this.esc(run.raw)}</pre></div>`
      : '';

    return errorsHtml + expHtml + sentHtml + recvHtml + closestHtml + rawHtml;
  }

  // ─── Test Suite Results ───────────────────────────────────────────────────────

  /** Build a self-contained HTML report for test suite execution results.
   *  @param testLogs  Optional map of test_id → last-run object for rich detail. */
  buildResultsHtml(result: any, testLogs?: { [testId: string]: any }): string {
    const ts = new Date().toISOString();
    const overallStatus = result.failed === 0 ? 'PASSED' : 'FAILED';

    const entries = (result.results || []).map((r: any) => {
      const run = testLogs?.[r.test_id] ?? null;
      const details = this.buildRunDetailSections(run);
      const errNote = (!details && r.errors?.length)
        ? `<div class="section errors-section"><h4>Errors</h4><ul>${(r.errors as string[]).map(e => `<li>${this.esc(e)}</li>`).join('')}</ul></div>`
        : '';
      const body = details || errNote || `<p class="no-data">No log detail available.</p>`;
      return `
      <details class="log-entry">
        <summary>
          <span class="test-id">${this.esc(r.test_id)}</span>
          ${this.badgeHtml(r.status)}
          <span class="timing">${r.elapsed_ms}ms</span>
        </summary>
        <div class="log-body">${body}</div>
      </details>`;
    }).join('');

    return `<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Test Suite Results — ${this.esc(ts)}</title>
  <style>
    ${this.commonCss()}
    .summary-card { background: #fff; border-radius: 8px; padding: 20px; margin-bottom: 24px; box-shadow: 0 1px 4px rgba(0,0,0,.12); }
    .overall { font-size: 16px; font-weight: 600; padding: 8px 16px; border-radius: 6px; display: inline-block; margin-bottom: 12px; }
    .meta { font-size: 13px; color: #888; margin-bottom: 16px; }
    .summary-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(120px, 1fr)); gap: 16px; }
    .stat-value.large { font-size: 28px; }
    ${this.collapsibleCss()}
  </style>
</head>
<body>
  <h1>Test Suite Results</h1>
  <p class="subtitle">Exported on ${new Date(ts).toLocaleString()}</p>
  <div class="summary-card">
    <div class="overall" style="background:${this.statusBg(overallStatus)};color:${this.statusColor(overallStatus)}">${overallStatus}</div>
    <div class="meta">
      Mode: <strong>${this.esc(result.mode || '—')}</strong> &nbsp;|&nbsp;
      Workers: <strong>${result.parallel_workers || 1}</strong> &nbsp;|&nbsp;
      Repeat: <strong>${result.repeat || 1}</strong> (${this.esc(result.repeat_mode || 'interleaved-repeats')})
    </div>
    <div class="summary-grid">
      <div class="stat"><span class="stat-label">Total</span><span class="stat-value large">${result.total}</span></div>
      <div class="stat"><span class="stat-label">Passed</span><span class="stat-value large" style="color:#2e7d32">${result.passed}</span></div>
      <div class="stat"><span class="stat-label">Failed</span><span class="stat-value large" style="color:#c62828">${result.failed}</span></div>
      <div class="stat"><span class="stat-label">Skipped</span><span class="stat-value large" style="color:#e65100">${result.skipped}</span></div>
      <div class="stat"><span class="stat-label">Duration</span><span class="stat-value" style="font-size:18px">${result.elapsed_ms}ms</span></div>
    </div>
  </div>
  <h2>Individual Test Results</h2>
  ${entries}
</body>
</html>`;
  }

  /** Build a JSON export object for test suite execution results.
   *  @param testLogs  Optional map of test_id → last-run object for rich detail. */
  buildResultsJson(result: any, testLogs?: { [testId: string]: any }): any {
    return {
      exported_at: new Date().toISOString(),
      summary: {
        status: result.failed === 0 ? 'PASSED' : 'FAILED',
        total: result.total,
        passed: result.passed,
        failed: result.failed,
        skipped: result.skipped,
        elapsed_ms: result.elapsed_ms,
        mode: result.mode,
        parallel_workers: result.parallel_workers,
        repeat: result.repeat,
        repeat_mode: result.repeat_mode,
      },
      results: (result.results || []).map((r: any) => ({
        ...r,
        log: testLogs?.[r.test_id] ?? null,
      })),
    };
  }

  /** Build CSV rows for test suite execution results (condensed). */
  buildResultsCsv(result: any): { headers: string[]; rows: any[][] } {
    const headers = ['test_id', 'status', 'elapsed_ms', 'errors'];
    const rows = (result.results || []).map((r: any) => [
      r.test_id,
      r.status,
      r.elapsed_ms,
      (r.errors || []).join('; '),
    ]);
    return { headers, rows };
  }

  // ─── Test Logs ────────────────────────────────────────────────────────────────

  /** Build a self-contained HTML report for test logs (last run per test). */
  buildLogsHtml(logs: any[], filtered: boolean): string {
    const ts = new Date().toISOString();
    const total   = logs.length;
    const passed  = logs.filter(l => (l.runs?.[0]?.status || l.status) === 'PASSED').length;
    const failed  = logs.filter(l => (l.runs?.[0]?.status || l.status) === 'FAILED').length;
    const skipped = logs.filter(l => (l.runs?.[0]?.status || l.status) === 'SKIPPED').length;
    const logSections = logs.map(log => this.buildLogEntryHtml(log)).join('\n');

    return `<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Test Execution Logs — ${this.esc(ts)}</title>
  <style>
    ${this.commonCss()}
    ${this.collapsibleCss()}
  </style>
</head>
<body>
  <h1>Test Execution Logs</h1>
  <p class="subtitle">
    Last run per test — Exported on ${new Date(ts).toLocaleString()}
    (${total} test${total !== 1 ? 's' : ''}${filtered ? ' — filtered view' : ''})
  </p>
  <div class="stats">
    <div class="stat"><span class="stat-label">Total</span><span class="stat-value">${total}</span></div>
    <div class="stat"><span class="stat-label">Passed</span><span class="stat-value" style="color:#2e7d32">${passed}</span></div>
    <div class="stat"><span class="stat-label">Failed</span><span class="stat-value" style="color:#c62828">${failed}</span></div>
    <div class="stat"><span class="stat-label">Skipped</span><span class="stat-value" style="color:#e65100">${skipped}</span></div>
  </div>
  ${logSections}
</body>
</html>`;
  }

  private buildLogEntryHtml(log: any): string {
    const run: any = (log.runs && log.runs.length > 0) ? log.runs[0] : null;
    const status  = run?.status  || log.status  || 'UNKNOWN';
    const elapsed = run?.elapsed_ms ?? log.duration ?? 0;
    const details = this.buildRunDetailSections(run);
    const bodyHtml = details
      ? `<div class="log-body">${details}</div>`
      : `<div class="log-body"><p class="no-data">No detailed data available (log was not loaded before export).</p></div>`;

    return `<details class="log-entry">
  <summary>
    <span class="test-id">${this.esc(log.testId)}</span>
    ${this.badgeHtml(status)}
    <span class="timing">${elapsed}ms</span>
    ${log.runCount ? `<span class="run-count">${log.runCount} run(s)</span>` : ''}
  </summary>
  ${bodyHtml}
</details>`;
  }

  /** Build a JSON export object for test logs (last run per test). */
  buildLogsJson(logs: any[], filtered: boolean): any {
    return {
      exported_at: new Date().toISOString(),
      filtered,
      total: logs.length,
      logs: logs.map(log => {
        const run = (log.runs && log.runs.length > 0) ? log.runs[0] : null;
        return {
          test_id: log.testId,
          status: run?.status || log.status,
          elapsed_ms: run?.elapsed_ms ?? log.duration,
          run_count: log.runCount,
          last_run: run,
        };
      }),
    };
  }

  /** Build CSV rows for test logs (condensed, last run per test). */
  buildLogsCsv(logs: any[]): { headers: string[]; rows: any[][] } {
    const headers = ['test_id', 'status', 'elapsed_ms', 'run_count', 'errors', 'expectations_count', 'sent_count', 'received_count'];
    const rows = logs.map(log => {
      const run = (log.runs && log.runs.length > 0) ? log.runs[0] : null;
      return [
        log.testId,
        run?.status || log.status,
        run?.elapsed_ms ?? log.duration,
        log.runCount,
        (run?.errors || []).join('; '),
        run?.expectations?.length ?? '',
        run?.sent_messages?.length ?? '',
        run?.received_messages?.length ?? '',
      ];
    });
    return { headers, rows };
  }
}

