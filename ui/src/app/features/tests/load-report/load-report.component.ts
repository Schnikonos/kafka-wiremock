import {
  Component, OnInit, AfterViewInit, OnDestroy,
  ViewChild, ElementRef, ChangeDetectorRef, ChangeDetectionStrategy,
} from '@angular/core';
import { CommonModule, DecimalPipe } from '@angular/common';
import { ActivatedRoute, Router, RouterModule } from '@angular/router';
import { MatCardModule } from '@angular/material/card';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatProgressSpinnerModule } from '@angular/material/progress-spinner';
import { MatTableModule } from '@angular/material/table';
import { MatChipsModule } from '@angular/material/chips';
import { MatTooltipModule } from '@angular/material/tooltip';
import { MatDividerModule } from '@angular/material/divider';
import { MatMenuModule } from '@angular/material/menu';
import { Chart, registerables } from 'chart.js';
import { ApiService } from '../../../core/services/api.service';
import { LoadHistoryService } from '../../../core/services/load-history.service';
import { LoadReport, LoadMetricBucket } from '../../../core/models';

Chart.register(...registerables);

@Component({
  selector: 'app-load-report',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.Default,
  imports: [
    CommonModule, RouterModule, DecimalPipe,
    MatCardModule, MatButtonModule, MatIconModule,
    MatProgressSpinnerModule, MatTableModule,
    MatChipsModule, MatTooltipModule, MatDividerModule, MatMenuModule,
  ],
  template: `
<div class="container">

  <!-- ── Loading / Error ── -->
  <div class="center-state" *ngIf="loading">
    <mat-spinner diameter="48"></mat-spinner>
    <p>Loading report…</p>
  </div>

  <mat-card class="error-card" *ngIf="!loading && error">
    <mat-card-content>
      <mat-icon color="warn">error</mat-icon>
      <span>{{error}}</span>
    </mat-card-content>
  </mat-card>

  <ng-container *ngIf="!loading && report">

    <!-- ── Header ── -->
    <mat-card class="header-card">
      <mat-card-header>
        <mat-card-title>
          <mat-icon class="title-icon">bar_chart</mat-icon>
          Load Test Report — {{report.scenario_name}}
        </mat-card-title>
        <mat-card-subtitle>
          {{report.started_at | date:'medium'}} · {{report.total_duration_s}}s · {{statusLabel}}
        </mat-card-subtitle>
      </mat-card-header>
      <mat-card-content>
        <div class="kpi-row">
          <div class="kpi-box">
            <div class="kpi-label">Total Requests</div>
            <div class="kpi-val">{{report.total_requests | number}}</div>
          </div>
          <div class="kpi-box ok">
            <div class="kpi-label">Passed (OK)</div>
            <div class="kpi-val">{{report.total_ok | number}}</div>
          </div>
          <div class="kpi-box ko">
            <div class="kpi-label">Failed (KO)</div>
            <div class="kpi-val">{{report.total_ko | number}}</div>
          </div>
          <div class="kpi-box" [class.ko]="report.error_rate_pct > 2">
            <div class="kpi-label">Error Rate</div>
            <div class="kpi-val">{{report.error_rate_pct | number:'1.1-1'}}%</div>
          </div>
          <div class="kpi-box">
            <div class="kpi-label">Mean</div>
            <div class="kpi-val">{{report.mean_ms | number:'1.0-0'}} ms</div>
          </div>
          <div class="kpi-box">
            <div class="kpi-label">p50</div>
            <div class="kpi-val">{{report.p50_ms | number:'1.0-0'}} ms</div>
          </div>
          <div class="kpi-box">
            <div class="kpi-label">p90</div>
            <div class="kpi-val">{{report.p90_ms | number:'1.0-0'}} ms</div>
          </div>
          <div class="kpi-box">
            <div class="kpi-label">p99</div>
            <div class="kpi-val">{{report.p99_ms | number:'1.0-0'}} ms</div>
          </div>
          <div class="kpi-box">
            <div class="kpi-label">Max</div>
            <div class="kpi-val">{{report.max_ms | number:'1.0-0'}} ms</div>
          </div>
        </div>

        <!-- Load shape replay (SVG) -->
        <div *ngIf="report.scenario?.phases?.length" class="shape-section">
          <div class="shape-label">Configured Load Shape</div>
          <svg [attr.viewBox]="shapeData.viewBox" preserveAspectRatio="none" class="shape-svg">
            <path [attr.d]="shapeData.path" fill="rgba(63,81,181,0.15)" stroke="#3f51b5" stroke-width="1.5"/>
          </svg>
        </div>
      </mat-card-content>
      <mat-card-actions>
        <button mat-button routerLink="/tests/load-test">
          <mat-icon>add</mat-icon> New Load Test
        </button>
        <button mat-button [matMenuTriggerFor]="exportMenu">
          <mat-icon>download</mat-icon> Export
          <mat-icon>arrow_drop_down</mat-icon>
        </button>
        <mat-menu #exportMenu="matMenu">
          <button mat-menu-item (click)="exportHtml()">
            <mat-icon>web</mat-icon> Export as HTML
          </button>
          <button mat-menu-item (click)="exportJson()">
            <mat-icon>code</mat-icon> Export as JSON
          </button>
        </mat-menu>
      </mat-card-actions>
    </mat-card>


    <!-- ── Per-test summary table ── -->
    <mat-card>
      <mat-card-header>
        <mat-card-title>Per-Test Summary</mat-card-title>
        <mat-card-subtitle>Aggregated statistics across the full scenario duration</mat-card-subtitle>
      </mat-card-header>
      <mat-card-content>
        <table class="summary-table">
          <thead>
            <tr>
              <th>Test ID</th>
              <th class="num">Total</th>
              <th class="num ok-col">OK</th>
              <th class="num ko-col">KO</th>
              <th class="num">Error %</th>
              <th class="num">Mean (ms)</th>
              <th class="num">p50 (ms)</th>
              <th class="num">p90 (ms)</th>
              <th class="num">p99 (ms)</th>
              <th class="num">Max (ms)</th>
            </tr>
          </thead>
          <tbody>
            <tr *ngFor="let s of report.summaries" [class.row-fail]="s.error_rate_pct > 2">
              <td class="test-id-cell">{{s.test_id}}</td>
              <td class="num">{{s.total | number}}</td>
              <td class="num ok-col">{{s.ok | number}}</td>
              <td class="num ko-col">{{s.ko | number}}</td>
              <td class="num" [class.bad-pct]="s.error_rate_pct > 2">{{s.error_rate_pct | number:'1.1-1'}}%</td>
              <td class="num">{{s.mean_ms | number:'1.0-0'}}</td>
              <td class="num">{{s.p50_ms | number:'1.0-0'}}</td>
              <td class="num">{{s.p90_ms | number:'1.0-0'}}</td>
              <td class="num">{{s.p99_ms | number:'1.0-0'}}</td>
              <td class="num">{{s.max_ms | number:'1.0-0'}}</td>
            </tr>
          </tbody>
        </table>
      </mat-card-content>
    </mat-card>

  </ng-container>

  <!-- ── Charts ── -->
  <!-- Canvases are OUTSIDE *ngIf so @ViewChild always resolves immediately. -->
  <div class="charts-grid" [hidden]="loading || !report">

    <mat-card class="chart-card">
      <mat-card-header>
        <mat-card-title>Active Users Over Time</mat-card-title>
        <mat-card-subtitle>Concurrent virtual users executing tests</mat-card-subtitle>
      </mat-card-header>
      <mat-card-content>
        <div class="chart-wrap"><canvas #usersCanvas></canvas></div>
      </mat-card-content>
    </mat-card>

    <mat-card class="chart-card">
      <mat-card-header>
        <mat-card-title>Requests per Bucket (OK / KO)</mat-card-title>
        <mat-card-subtitle>Test completions per {{report?.scenario?.bucket_s || 5}}-second window</mat-card-subtitle>
      </mat-card-header>
      <mat-card-content>
        <div class="chart-wrap"><canvas #requestsCanvas></canvas></div>
      </mat-card-content>
    </mat-card>

    <mat-card class="chart-card chart-card-full">
      <mat-card-header>
        <mat-card-title>Response Time Distribution</mat-card-title>
        <mat-card-subtitle>Mean, p50, p90, p99 per bucket (ms)</mat-card-subtitle>
      </mat-card-header>
      <mat-card-content>
        <div class="chart-wrap chart-wrap-tall"><canvas #rtCanvas></canvas></div>
      </mat-card-content>
    </mat-card>

  </div>

</div>
  `,
  styles: [`
    .container { padding: 16px; max-width: 1400px; margin: 0 auto; display: flex; flex-direction: column; gap: 16px; }
    .center-state { display: flex; flex-direction: column; align-items: center; padding: 64px; gap: 16px; color: #9e9e9e; }
    .error-card { color: #f44336; }
    .error-card mat-card-content { display: flex; align-items: center; gap: 8px; }
    .header-card { }
    .title-icon { vertical-align: middle; margin-right: 8px; }

    .kpi-row { display: flex; flex-wrap: wrap; gap: 12px; margin-top: 8px; }
    .kpi-box { background: #f5f5f5; border-radius: 8px; padding: 12px 18px; min-width: 100px; text-align: center; }
    .kpi-box.ok { background: #e8f5e9; }
    .kpi-box.ko { background: #ffebee; }
    .kpi-label { font-size: 11px; color: #9e9e9e; text-transform: uppercase; letter-spacing: .5px; }
    .kpi-val { font-size: 22px; font-weight: 700; color: #333; margin-top: 2px; }
    .kpi-box.ko .kpi-val { color: #f44336; }
    .kpi-box.ok .kpi-val { color: #4caf50; }

    .shape-section { margin-top: 16px; }
    .shape-label { font-size: 12px; color: #9e9e9e; margin-bottom: 4px; }
    .shape-svg { display: block; width: 100%; max-width: 600px; height: 80px; border: 1px solid #e0e0e0; border-radius: 4px; background: #fafafa; }

    .charts-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }
    .chart-card-full { grid-column: 1 / -1; }
    @media (max-width: 900px) { .charts-grid { grid-template-columns: 1fr; } .chart-card-full { grid-column: auto; } }
    .chart-card mat-card-content { padding-top: 12px; }
    .chart-wrap { height: 220px; position: relative; }
    .chart-wrap-tall { height: 260px; }
    canvas { width: 100% !important; }

    .summary-table { width: 100%; border-collapse: collapse; font-size: 13px; }
    .summary-table th { text-align: left; padding: 8px 10px; border-bottom: 2px solid #e0e0e0; color: rgba(0,0,0,.54); font-weight: 600; font-size: 12px; }
    .summary-table th.num { text-align: right; }
    .summary-table td { padding: 7px 10px; border-bottom: 1px solid #f0f0f0; }
    .summary-table td.num { text-align: right; font-variant-numeric: tabular-nums; }
    .summary-table .ok-col { color: #4caf50; }
    .summary-table .ko-col { color: #f44336; }
    .summary-table .bad-pct { color: #f44336; font-weight: 600; }
    .summary-table .row-fail { background: #fff8f8; }
    .test-id-cell { font-family: monospace; font-size: 12px; }
  `],
})
export class LoadReportComponent implements OnInit, AfterViewInit, OnDestroy {
  @ViewChild('usersCanvas')    usersCanvasRef!: ElementRef<HTMLCanvasElement>;
  @ViewChild('requestsCanvas') requestsCanvasRef!: ElementRef<HTMLCanvasElement>;
  @ViewChild('rtCanvas')       rtCanvasRef!: ElementRef<HTMLCanvasElement>;

  report: LoadReport | null = null;
  loading = true;
  error = '';
  jobId = '';

  private usersChart: Chart | null = null;
  private requestsChart: Chart | null = null;
  private rtChart: Chart | null = null;

  constructor(
    private api: ApiService,
    private route: ActivatedRoute,
    private router: Router,
    private cd: ChangeDetectorRef,
    private loadHistory: LoadHistoryService,
  ) {}

  ngOnInit(): void {
    this.jobId = this.route.snapshot.paramMap.get('jobId') ?? '';
    if (!this.jobId) {
      this.error = 'No job ID in URL';
      this.loading = false;
      return;
    }
    this.api.getLoadReport(this.jobId).subscribe({
      next: (r) => {
        this.report = r;
        this.loading = false;
        // Persist report for history tab
        this.loadHistory.saveReport(r);
        // Canvases are always in DOM (outside *ngIf); build charts immediately.
        this.buildCharts(r);
        this.cd.detectChanges();
      },
      error: (err) => {
        // Try localStorage fallback (server may have restarted)
        const cached = this.loadHistory.getReport(this.jobId);
        if (cached) {
          this.report = cached;
          this.loading = false;
          this.buildCharts(cached);
          this.cd.detectChanges();
        } else {
          this.loading = false;
          this.error = err.message || 'Failed to load report';
          this.cd.detectChanges();
        }
      },
    });
  }

  ngAfterViewInit(): void {
    // Canvases are always in the DOM — build if report already loaded synchronously.
    if (this.report) {
      this.buildCharts(this.report);
    }
  }

  ngOnDestroy(): void {
    this.usersChart?.destroy();
    this.requestsChart?.destroy();
    this.rtChart?.destroy();
  }

  // ─── Computed ─────────────────────────────────────────────────────────────
  get statusLabel(): string {
    if (!this.report) return '';
    const map: Record<string, string> = { COMPLETED: '✅ Completed', CANCELLED: '⚠️ Cancelled', FAILED: '❌ Failed' };
    return map[this.report.status] ?? this.report.status;
  }

  get shapeData(): { path: string; viewBox: string } {
    const phases = this.report?.scenario?.phases ?? [];
    const W = 600, H = 80, PAD = 6;
    const total = phases.reduce((s: number, p: any) => s + (p.duration_s || 0), 0);
    const maxU = Math.max(...phases.map((p: any) => Math.max(p.from_users || 0, p.to_users || 0)), 1);
    if (total === 0) return { path: '', viewBox: `0 0 ${W} ${H}` };
    const toX = (t: number) => (t / total) * W;
    const toY = (u: number) => H - PAD - ((u / maxU) * (H - PAD * 2));
    const pts: string[] = [`M0,${H}`];
    let t = 0;
    for (const ph of phases) {
      if (ph.type === 'ramp') {
        pts.push(`L${toX(t)},${toY(ph.from_users || 0)}`);
        pts.push(`L${toX(t + ph.duration_s)},${toY(ph.to_users || 0)}`);
      } else {
        pts.push(`L${toX(t)},${toY(ph.to_users || 0)}`);
        pts.push(`L${toX(t + ph.duration_s)},${toY(ph.to_users || 0)}`);
      }
      t += ph.duration_s;
    }
    pts.push(`L${W},${H}`, 'Z');
    return { path: pts.join(' '), viewBox: `0 0 ${W} ${H}` };
  }

  // ─── Chart building ───────────────────────────────────────────────────────
  private buildCharts(report: LoadReport): void {
    const buckets = report.buckets;
    if (!buckets?.length) return;
    const labels = buckets.map(b => `${b.t_s}s`);

    // 1. Active users
    this.usersChart?.destroy();
    if (this.usersCanvasRef?.nativeElement) {
      this.usersChart = new Chart(this.usersCanvasRef.nativeElement, {
        type: 'line',
        data: {
          labels,
          datasets: [{
            label: 'Active Users',
            data: buckets.map(b => b.active_users),
            fill: true,
            borderColor: '#3f51b5',
            backgroundColor: 'rgba(63,81,181,0.12)',
            tension: 0.3,
            pointRadius: 2,
          }],
        },
        options: {
          responsive: true, maintainAspectRatio: false,
          scales: { y: { beginAtZero: true, title: { display: true, text: 'Users' } }, x: { title: { display: true, text: 'Time' } } },
          plugins: { legend: { display: false } },
        },
      });
    }

    // 2. OK / KO stacked bar
    this.requestsChart?.destroy();
    if (this.requestsCanvasRef?.nativeElement) {
      this.requestsChart = new Chart(this.requestsCanvasRef.nativeElement, {
        type: 'bar',
        data: {
          labels,
          datasets: [
            { label: 'OK', data: buckets.map(b => b.ok), backgroundColor: 'rgba(76,175,80,0.75)', stack: 'req' },
            { label: 'KO', data: buckets.map(b => b.ko), backgroundColor: 'rgba(244,67,54,0.75)', stack: 'req' },
          ],
        },
        options: {
          responsive: true, maintainAspectRatio: false,
          scales: { x: { stacked: true, title: { display: true, text: 'Time' } }, y: { stacked: true, beginAtZero: true, title: { display: true, text: 'Requests' } } },
          plugins: { legend: { position: 'top' } },
        },
      });
    }

    // 3. Response time lines
    this.rtChart?.destroy();
    if (this.rtCanvasRef?.nativeElement) {
      const ds = (label: string, key: keyof LoadMetricBucket, color: string, dash?: number[]) => ({
        label, data: buckets.map(b => b[key] as number),
        borderColor: color, backgroundColor: 'transparent',
        tension: 0.3, pointRadius: 2, borderDash: dash,
      });
      this.rtChart = new Chart(this.rtCanvasRef.nativeElement, {
        type: 'line',
        data: {
          labels,
          datasets: [
            ds('Mean', 'mean_ms', '#9e9e9e', [4, 2]),
            ds('p50',  'p50_ms',  '#2196f3'),
            ds('p90',  'p90_ms',  '#ff9800'),
            ds('p99',  'p99_ms',  '#f44336'),
          ],
        },
        options: {
          responsive: true, maintainAspectRatio: false,
          scales: { y: { beginAtZero: true, title: { display: true, text: 'Response Time (ms)' } }, x: { title: { display: true, text: 'Time' } } },
          plugins: { legend: { position: 'top' } },
        },
      });
    }
  }

  // ─── Exports ──────────────────────────────────────────────────────────────
  exportJson(): void {
    const blob = new Blob([JSON.stringify(this.report, null, 2)], { type: 'application/json' });
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = `load-report-${this.jobId.substring(0, 8)}.json`;
    a.click();
    URL.revokeObjectURL(a.href);
  }

  exportHtml(): void {
    const r = this.report!;
    const buckets = r.buckets ?? [];
    const bucketS = r.scenario?.bucket_s ?? 5;

    const labels = JSON.stringify(buckets.map(b => `${b.t_s}s`));
    const usersData   = JSON.stringify(buckets.map(b => b.active_users));
    const okData      = JSON.stringify(buckets.map(b => b.ok));
    const koData      = JSON.stringify(buckets.map(b => b.ko));
    const meanData    = JSON.stringify(buckets.map(b => b.mean_ms));
    const p50Data     = JSON.stringify(buckets.map(b => b.p50_ms));
    const p90Data     = JSON.stringify(buckets.map(b => b.p90_ms));
    const p99Data     = JSON.stringify(buckets.map(b => b.p99_ms));

    // Load shape SVG
    const phases = r.scenario?.phases ?? [];
    const shapeSvg = this.buildShapeSvgString(phases, 700, 90);

    // Summary rows
    const summaryRows = (r.summaries ?? []).map(s => `
      <tr${s.error_rate_pct > 2 ? ' class="row-fail"' : ''}>
        <td class="mono">${s.test_id}</td>
        <td class="num">${s.total.toLocaleString()}</td>
        <td class="num ok">${s.ok.toLocaleString()}</td>
        <td class="num ko">${s.ko.toLocaleString()}</td>
        <td class="num${s.error_rate_pct > 2 ? ' bad' : ''}">${s.error_rate_pct.toFixed(1)}%</td>
        <td class="num">${s.mean_ms.toFixed(0)}</td>
        <td class="num">${s.p50_ms.toFixed(0)}</td>
        <td class="num">${s.p90_ms.toFixed(0)}</td>
        <td class="num">${s.p99_ms.toFixed(0)}</td>
        <td class="num">${s.max_ms.toFixed(0)}</td>
      </tr>`).join('');

    const statusEmoji = { COMPLETED: '✅', CANCELLED: '⚠️', FAILED: '❌' }[r.status] ?? '';

    const html = `<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Load Test Report — ${r.scenario_name}</title>
<style>
  *{box-sizing:border-box;margin:0;padding:0}
  body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;background:#f0f2f5;color:#333}
  .header{background:linear-gradient(135deg,#1a237e,#283593);color:#fff;padding:28px 40px}
  .header h1{font-size:22px;font-weight:600;display:flex;align-items:center;gap:10px}
  .header .meta{margin-top:6px;opacity:.75;font-size:13px}
  .content{max-width:1400px;margin:0 auto;padding:24px;display:flex;flex-direction:column;gap:20px}
  .card{background:#fff;border-radius:10px;padding:20px 24px;box-shadow:0 1px 6px rgba(0,0,0,.1)}
  h2{font-size:15px;font-weight:600;margin-bottom:4px;color:#1a237e}
  .sub{font-size:12px;color:#9e9e9e;margin-bottom:14px}
  .kpi-row{display:flex;flex-wrap:wrap;gap:12px}
  .kpi{background:#f5f5f5;border-radius:8px;padding:12px 18px;min-width:110px;text-align:center}
  .kpi.ok{background:#e8f5e9}.kpi.ko{background:#ffebee}
  .kpi-l{font-size:10px;text-transform:uppercase;letter-spacing:.5px;color:#9e9e9e}
  .kpi-v{font-size:22px;font-weight:700;margin-top:2px}
  .kpi.ok .kpi-v{color:#2e7d32}.kpi.ko .kpi-v{color:#c62828}
  .shape-wrap{margin-top:14px}
  .shape-lbl{font-size:11px;color:#9e9e9e;margin-bottom:4px}
  .shape-svg{display:block;width:100%;max-width:700px;height:90px;border:1px solid #e0e0e0;border-radius:4px;background:#fafafa}
  .charts-grid{display:grid;grid-template-columns:1fr 1fr;gap:20px}
  .chart-card-full{grid-column:1/-1}
  @media(max-width:800px){.charts-grid{grid-template-columns:1fr}.chart-card-full{grid-column:auto}}
  .chart-wrap{position:relative;height:220px}
  .chart-wrap-tall{height:260px}
  table{width:100%;border-collapse:collapse;font-size:13px}
  th{text-align:left;padding:8px 10px;border-bottom:2px solid #e0e0e0;font-size:11px;text-transform:uppercase;color:#666;font-weight:600}
  th.num{text-align:right}
  td{padding:7px 10px;border-bottom:1px solid #f0f0f0}
  td.num{text-align:right;font-variant-numeric:tabular-nums}
  td.ok{color:#2e7d32;font-weight:600}
  td.ko{color:#c62828;font-weight:600}
  td.bad{color:#c62828;font-weight:600}
  td.mono{font-family:monospace;font-size:12px}
  tr.row-fail{background:#fff8f8}
  .footer{text-align:center;font-size:12px;color:#bdbdbd;padding:8px}
</style>
</head>
<body>
<div class="header">
  <h1><span>⚡</span> Load Test Report — ${r.scenario_name}</h1>
  <div class="meta">
    ${statusEmoji} ${r.status} &nbsp;·&nbsp;
    ${new Date(r.started_at).toLocaleString()} &nbsp;·&nbsp;
    Duration: ${r.total_duration_s}s &nbsp;·&nbsp;
    Generated by Kafka Wiremock
  </div>
</div>

<div class="content">

  <div class="card">
    <h2>Overall Statistics</h2>
    <div class="kpi-row">
      <div class="kpi"><div class="kpi-l">Total</div><div class="kpi-v">${r.total_requests.toLocaleString()}</div></div>
      <div class="kpi ok"><div class="kpi-l">OK</div><div class="kpi-v">${r.total_ok.toLocaleString()}</div></div>
      <div class="kpi ko"><div class="kpi-l">KO</div><div class="kpi-v">${r.total_ko.toLocaleString()}</div></div>
      <div class="kpi${r.error_rate_pct > 2 ? ' ko' : ''}"><div class="kpi-l">Error %</div><div class="kpi-v">${r.error_rate_pct.toFixed(1)}%</div></div>
      <div class="kpi"><div class="kpi-l">Mean</div><div class="kpi-v">${r.mean_ms.toFixed(0)} ms</div></div>
      <div class="kpi"><div class="kpi-l">p50</div><div class="kpi-v">${r.p50_ms.toFixed(0)} ms</div></div>
      <div class="kpi"><div class="kpi-l">p90</div><div class="kpi-v">${r.p90_ms.toFixed(0)} ms</div></div>
      <div class="kpi"><div class="kpi-l">p99</div><div class="kpi-v">${r.p99_ms.toFixed(0)} ms</div></div>
      <div class="kpi"><div class="kpi-l">Max</div><div class="kpi-v">${r.max_ms.toFixed(0)} ms</div></div>
    </div>
    ${phases.length ? `<div class="shape-wrap"><div class="shape-lbl">Configured Load Shape</div>${shapeSvg}</div>` : ''}
  </div>

  <div class="charts-grid">
    <div class="card"><h2>Active Users Over Time</h2><div class="chart-wrap"><canvas id="c1"></canvas></div></div>
    <div class="card"><h2>Requests per Bucket (OK / KO)</h2><div class="sub">Per ${bucketS}-second window</div><div class="chart-wrap"><canvas id="c2"></canvas></div></div>
    <div class="card chart-card-full"><h2>Response Time Distribution</h2><div class="sub">Mean, p50, p90, p99 per bucket (ms)</div><div class="chart-wrap chart-wrap-tall"><canvas id="c3"></canvas></div></div>
  </div>

  <div class="card">
    <h2>Per-Test Summary</h2>
    <div class="sub">Aggregated statistics across the full scenario duration</div>
    <table>
      <thead><tr>
        <th>Test ID</th><th class="num">Total</th><th class="num">OK</th><th class="num">KO</th>
        <th class="num">Error%</th><th class="num">Mean</th><th class="num">p50</th>
        <th class="num">p90</th><th class="num">p99</th><th class="num">Max (ms)</th>
      </tr></thead>
      <tbody>${summaryRows}</tbody>
    </table>
  </div>

  <div class="footer">Generated by Kafka Wiremock Load Testing · ${new Date().toLocaleString()}</div>
</div>

<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.7/dist/chart.umd.min.js"></script>
<script>
const labels = ${labels};
new Chart(document.getElementById('c1'),{type:'line',data:{labels,datasets:[{label:'Active Users',data:${usersData},fill:true,borderColor:'#3f51b5',backgroundColor:'rgba(63,81,181,0.12)',tension:0.3,pointRadius:2}]},options:{responsive:true,maintainAspectRatio:false,scales:{y:{beginAtZero:true,title:{display:true,text:'Users'}},x:{title:{display:true,text:'Time'}}},plugins:{legend:{display:false}}}});
new Chart(document.getElementById('c2'),{type:'bar',data:{labels,datasets:[{label:'OK',data:${okData},backgroundColor:'rgba(76,175,80,0.75)',stack:'r'},{label:'KO',data:${koData},backgroundColor:'rgba(244,67,54,0.75)',stack:'r'}]},options:{responsive:true,maintainAspectRatio:false,scales:{x:{stacked:true},y:{stacked:true,beginAtZero:true,title:{display:true,text:'Requests'}}},plugins:{legend:{position:'top'}}}});
new Chart(document.getElementById('c3'),{type:'line',data:{labels,datasets:[{label:'Mean',data:${meanData},borderColor:'#9e9e9e',backgroundColor:'transparent',tension:0.3,pointRadius:2,borderDash:[4,2]},{label:'p50',data:${p50Data},borderColor:'#2196f3',backgroundColor:'transparent',tension:0.3,pointRadius:2},{label:'p90',data:${p90Data},borderColor:'#ff9800',backgroundColor:'transparent',tension:0.3,pointRadius:2},{label:'p99',data:${p99Data},borderColor:'#f44336',backgroundColor:'transparent',tension:0.3,pointRadius:2}]},options:{responsive:true,maintainAspectRatio:false,scales:{y:{beginAtZero:true,title:{display:true,text:'Response Time (ms)'}},x:{title:{display:true,text:'Time'}}},plugins:{legend:{position:'top'}}}});
</script>
</body>
</html>`;

    const blob = new Blob([html], { type: 'text/html;charset=utf-8' });
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = `load-report-${this.jobId.substring(0, 8)}.html`;
    a.click();
    URL.revokeObjectURL(a.href);
  }

  /** Build an inline SVG string for the load shape (used in HTML export). */
  private buildShapeSvgString(phases: any[], W = 600, H = 80): string {
    const PAD = 6;
    const total = phases.reduce((s: number, p: any) => s + (p.duration_s || 0), 0);
    const maxU = Math.max(...phases.map((p: any) => Math.max(p.from_users || 0, p.to_users || 0)), 1);
    if (total === 0) return '';
    const toX = (t: number) => (t / total) * W;
    const toY = (u: number) => H - PAD - ((u / maxU) * (H - PAD * 2));
    const pts: string[] = [`M0,${H}`];
    let t = 0;
    for (const ph of phases) {
      if (ph.type === 'ramp') {
        pts.push(`L${toX(t).toFixed(1)},${toY(ph.from_users || 0).toFixed(1)}`);
        pts.push(`L${toX(t + ph.duration_s).toFixed(1)},${toY(ph.to_users || 0).toFixed(1)}`);
      } else {
        pts.push(`L${toX(t).toFixed(1)},${toY(ph.to_users || 0).toFixed(1)}`);
        pts.push(`L${toX(t + ph.duration_s).toFixed(1)},${toY(ph.to_users || 0).toFixed(1)}`);
      }
      t += ph.duration_s;
    }
    pts.push(`L${W},${H}`, 'Z');
    return `<svg class="shape-svg" viewBox="0 0 ${W} ${H}" preserveAspectRatio="none"><path d="${pts.join(' ')}" fill="rgba(63,81,181,0.15)" stroke="#3f51b5" stroke-width="1.5"/></svg>`;
  }
}

