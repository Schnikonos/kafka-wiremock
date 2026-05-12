import { Component, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { MatCardModule } from '@angular/material/card';
import { MatTableModule } from '@angular/material/table';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatInputModule } from '@angular/material/input';
import { MatExpansionModule } from '@angular/material/expansion';
import { MatSnackBar, MatSnackBarModule } from '@angular/material/snack-bar';
import { MatProgressBarModule } from '@angular/material/progress-bar';
import { MatChipsModule } from '@angular/material/chips';
import { MatTooltipModule } from '@angular/material/tooltip';
import { forkJoin, of } from 'rxjs';
import { catchError, map } from 'rxjs/operators';
import { ApiService } from '../../core/services/api.service';
import { AppConfigService } from '../../core/services/app-config.service';
import { ExportService } from '../../core/services/export.service';

interface RunEntry {
  test_name?: string;
  status: string;
  timestamp?: string;
  elapsed_ms: number;
  errors?: string[];
  sent_messages?: any[];
  received_messages?: any[];
  skipped_messages?: any[];
  closest_match?: any;
  perfect_match?: any;
  expectations?: any[];
  raw?: string;  // Legacy fallback
}

interface LogEntry {
  testId: string;
  fullPath?: string;
  relativePath?: string;
  timestamp: Date;
  status: string;
  duration: number;
  size?: number;
  runCount: number;
  runs: RunEntry[] | null;   // null = not yet loaded
  preview?: string;
  summary: any;
}

@Component({
  selector: 'app-logs',
  standalone: true,
  imports: [
    CommonModule,
    FormsModule,
    MatCardModule,
    MatTableModule,
    MatButtonModule,
    MatIconModule,
    MatFormFieldModule,
    MatInputModule,
    MatExpansionModule,
    MatSnackBarModule,
    MatProgressBarModule,
    MatChipsModule,
    MatTooltipModule,
  ],
  template: `
    <div class="container">
      <mat-card>
        <mat-card-header>
          <mat-card-title>Test Execution Logs</mat-card-title>
          <mat-card-subtitle>View and search test execution logs — up to 10 previous runs per test</mat-card-subtitle>
        </mat-card-header>
        <mat-card-content>
          <!-- Search and Refresh -->
          <div class="controls-section">
            <mat-form-field appearance="outline" class="search-field">
              <mat-label>Search Logs</mat-label>
              <input matInput placeholder="Filter by test ID..." [(ngModel)]="searchText"
                     (ngModelChange)="filterLogs()">
              <mat-icon matSuffix>search</mat-icon>
            </mat-form-field>

            <button mat-raised-button class="refresh-btn" color="primary" (click)="loadLogs()" [disabled]="isLoading">
              <mat-icon>refresh</mat-icon>
              Refresh
            </button>

            <button mat-stroked-button color="accent" (click)="exportLogs()"
                    [disabled]="filteredLogs.length === 0"
                    [matTooltip]="'Export ' + filteredLogs.length + ' log(s) as ' + (appConfigService.getExportFormat() | uppercase) + (searchText ? ' (filtered)' : '')">
              <mat-icon>download</mat-icon>
              Export ({{ appConfigService.getExportFormat() | uppercase }})
            </button>
          </div>

          <mat-progress-bar *ngIf="isLoading" mode="indeterminate"></mat-progress-bar>

          <!-- Logs List -->
          <div *ngIf="filteredLogs.length === 0" class="empty-state">
            <mat-icon>description</mat-icon>
            <p>{{ isLoading ? 'Loading logs...' : 'No logs found' }}</p>
          </div>

          <!-- One accordion panel per test file -->
          <div *ngFor="let log of filteredLogs; let i = index" class="log-item">
            <mat-expansion-panel
              [expanded]="expandedLogIndex === i"
              (opened)="onLogOpened(log, i)"
              (click)="expandedLogIndex = i">
              <mat-expansion-panel-header>
                <mat-panel-title class="log-title">
                  <span class="log-id">{{ log.testId }}</span>
                  <span class="run-count-badge" *ngIf="log.runCount > 0">{{ log.runCount }} run{{ log.runCount !== 1 ? 's' : '' }}</span>
                  <span class="log-timestamp" *ngIf="log.timestamp">
                    {{ log.timestamp | date:'short' }}
                  </span>
                </mat-panel-title>
                <mat-panel-description class="log-preview">
                  <span *ngIf="log.status" [ngClass]="'status-' + log.status.toLowerCase()">
                    {{ log.status }}
                  </span>
                  <span *ngIf="log.duration" class="log-duration">
                    {{ log.duration }}ms
                  </span>
                </mat-panel-description>
              </mat-expansion-panel-header>

              <!-- Loading indicator -->
              <div *ngIf="log.runs === null" class="log-loading">
                <mat-progress-bar mode="indeterminate"></mat-progress-bar>
                <p>Loading run history...</p>
              </div>

              <!-- No runs yet -->
              <div *ngIf="log.runs !== null && log.runs!.length === 0" class="empty-state small">
                <p>No run history found.</p>
              </div>

              <!-- Per-run accordion (newest first) -->
              <div *ngIf="log.runs !== null && log.runs!.length > 0">
                <div *ngFor="let run of log.runs; let ri = index" class="run-item">
                  <mat-expansion-panel class="run-panel" [expanded]="ri === 0">
                    <mat-expansion-panel-header class="run-header">
                      <mat-panel-title class="run-title">
                        <span class="run-label">Run #{{ log.runs!.length - ri }}</span>
                        <span *ngIf="run.timestamp" class="run-ts">{{ run.timestamp | date:'medium' }}</span>
                      </mat-panel-title>
                      <mat-panel-description>
                        <span [ngClass]="'status-' + run.status.toLowerCase()">{{ run.status }}</span>
                        <span class="log-duration">{{ run.elapsed_ms }}ms</span>
                      </mat-panel-description>
                    </mat-expansion-panel-header>

                    <!-- Run details -->
                    <div class="run-content">

                      <!-- Errors -->
                      <div *ngIf="run.errors && run.errors.length > 0" class="run-section errors-section">
                        <h5 class="section-title">Errors</h5>
                        <ul class="error-list">
                          <li *ngFor="let err of run.errors" class="error-item">{{ err }}</li>
                        </ul>
                      </div>

                      <!-- Expectations -->
                      <div *ngIf="run.expectations && run.expectations.length > 0" class="run-section">
                        <h5 class="section-title">Expectations</h5>
                        <div *ngFor="let exp of run.expectations" class="expectation-item">
                          <span class="exp-topic">{{ exp.topic }}</span>
                          <span [ngClass]="'status-' + (exp.status || 'unknown').toLowerCase()">{{ exp.status }}</span>
                          <span class="exp-counts">received {{ exp.received }}/{{ exp.expected }}</span>
                          <span class="exp-time">{{ exp.elapsed_ms }}ms</span>
                        </div>
                      </div>

                      <!-- Sent messages -->
                      <div *ngIf="run.sent_messages && run.sent_messages.length > 0" class="run-section">
                        <h5 class="section-title">Sent Messages ({{ run.sent_messages.length }})</h5>
                        <div *ngFor="let msg of run.sent_messages" class="message-item sent-message">
                          <div class="msg-topic">→ {{ msg.topic }}</div>
                          <pre class="msg-payload">{{ msg.payload | json }}</pre>
                          <div *ngIf="msg.headers" class="msg-headers">Headers: {{ msg.headers | json }}</div>
                        </div>
                      </div>

                      <!-- Received messages (verbose mode) -->
                      <div *ngIf="run.received_messages && run.received_messages.length > 0" class="run-section">
                        <h5 class="section-title">Received Messages ({{ run.received_messages.length }})</h5>
                        <div *ngFor="let msg of run.received_messages" class="message-item received-message">
                          <div class="msg-topic">← {{ msg.topic }}
                            <span *ngIf="msg.conditions_matched !== undefined" class="conditions-badge"
                              [ngClass]="msg.conditions_matched === msg.total_conditions ? 'cond-ok' : 'cond-fail'">
                              {{ msg.conditions_matched }}/{{ msg.total_conditions }} conditions
                            </span>
                          </div>
                          <pre class="msg-payload">{{ msg.payload | json }}</pre>
                          <div *ngIf="msg.failed_conditions && msg.failed_conditions.length > 0" class="failed-conditions">
                            <span class="failed-title">Failed conditions:</span>
                            <div *ngFor="let fc of msg.failed_conditions" class="failed-condition">
                              <code>{{ fc.type }}{{ fc.expression ? ' ' + fc.expression : '' }}</code>
                              expected <code>{{ fc.expected?.value ?? fc.expected?.regex ?? '—' }}</code>
                            </div>
                          </div>
                        </div>
                      </div>

                      <!-- Closest / perfect match -->
                      <div *ngIf="run.closest_match" class="run-section match-section">
                        <h5 class="section-title">Closest Match ({{ run.closest_match.tier_name }})</h5>
                        <pre class="msg-payload">{{ run.closest_match.message?.payload | json }}</pre>
                      </div>

                      <!-- Raw fallback for legacy format -->
                      <div *ngIf="run.raw" class="run-section">
                        <pre class="log-text">{{ run.raw }}</pre>
                      </div>

                    </div>

                    <!-- Actions -->
                    <div class="log-actions">
                      <button mat-stroked-button color="primary" (click)="copyRun(run)">
                        <mat-icon>content_copy</mat-icon> Copy
                      </button>
                      <button mat-stroked-button (click)="downloadRun(log.testId, run, ri)">
                        <mat-icon>download</mat-icon> Download
                      </button>
                    </div>
                  </mat-expansion-panel>
                </div>
              </div>

            </mat-expansion-panel>
          </div>

          <!-- Stats -->
          <div *ngIf="filteredLogs.length > 0" class="log-stats">
            <div class="stat">
              <span class="stat-label">Total Logs</span>
              <span class="stat-value">{{ filteredLogs.length }}</span>
            </div>
            <div class="stat">
              <span class="stat-label">Passed</span>
              <span class="stat-value passed">{{ getStatusCount('PASSED') }}</span>
            </div>
            <div class="stat">
              <span class="stat-label">Failed</span>
              <span class="stat-value failed">{{ getStatusCount('FAILED') }}</span>
            </div>
            <div class="stat">
              <span class="stat-label">Skipped</span>
              <span class="stat-value skipped">{{ getStatusCount('SKIPPED') }}</span>
            </div>
          </div>
        </mat-card-content>
      </mat-card>
    </div>
  `,
  styles: [`
    .container {
      padding: 24px;
      max-width: 1200px;
      margin: 0 auto;
    }

    .controls-section {
      display: flex;
      gap: 16px;
      align-items: center;
      margin-bottom: 24px;
      flex-wrap: wrap;
    }

    .refresh-btn { }  /* alignment handled by parent flex */
    .search-field { flex: 1; min-width: 250px; max-width: 400px; }

    .empty-state {
      text-align: center;
      padding: 60px 24px;
      color: #757575;
    }
    .empty-state.small { padding: 20px; }
    .empty-state mat-icon {
      font-size: 64px; width: 64px; height: 64px;
      color: #bdbdbd; margin-bottom: 16px;
    }

    .log-item { margin-bottom: 12px; }

    .log-title {
      display: flex; gap: 10px; align-items: center; flex: 1;
    }
    .log-id { font-weight: 600; color: #1976d2; min-width: 120px; }
    .run-count-badge {
      font-size: 11px; background: #e3f2fd; color: #1565c0;
      padding: 2px 7px; border-radius: 10px; font-weight: 500;
    }
    .log-timestamp { font-size: 12px; color: #999; }

    .log-preview { display: flex; gap: 12px; align-items: center; }
    .log-duration {
      font-size: 12px; color: #666;
      background-color: #f5f5f5; padding: 4px 8px; border-radius: 3px;
    }

    /* Status badges */
    .status-passed  { background:#c8e6c9; color:#1b5e20; padding:3px 8px; border-radius:3px; font-size:12px; font-weight:500; }
    .status-failed  { background:#ffcdd2; color:#b71c1c; padding:3px 8px; border-radius:3px; font-size:12px; font-weight:500; }
    .status-skipped { background:#ffe0b2; color:#e65100; padding:3px 8px; border-radius:3px; font-size:12px; font-weight:500; }
    .status-unknown { background:#eeeeee; color:#555;    padding:3px 8px; border-radius:3px; font-size:12px; font-weight:500; }
    .status-timeout { background:#e1bee7; color:#6a1b9a; padding:3px 8px; border-radius:3px; font-size:12px; font-weight:500; }
    .status-matched  { background:#c8e6c9; color:#1b5e20; padding:2px 6px; border-radius:3px; font-size:11px; }
    .status-no_match, .status-timeout { background:#ffcdd2; color:#b71c1c; padding:2px 6px; border-radius:3px; font-size:11px; }

    /* Per-run panel */
    .run-item { margin: 6px 0; }
    .run-panel { box-shadow: none !important; border: 1px solid #e0e0e0 !important; border-radius: 4px !important; }
    .run-header { min-height: 48px !important; }
    .run-title { display: flex; gap: 12px; align-items: center; flex: 1; }
    .run-label { font-weight: 600; font-size: 13px; }
    .run-ts { font-size: 12px; color: #888; }

    .run-content { padding: 8px 0 4px 0; }

    .run-section { margin-bottom: 14px; }
    .section-title { font-size: 13px; font-weight: 600; color: #555; margin: 0 0 6px 0; }

    .error-list { margin: 0; padding-left: 18px; }
    .error-item { color: #b71c1c; font-size: 13px; margin-bottom: 4px; }
    .errors-section { background: #fff8f8; padding: 10px; border-radius: 4px; border-left: 3px solid #ef9a9a; }

    .expectation-item {
      display: flex; gap: 10px; align-items: center;
      padding: 4px 6px; font-size: 13px;
    }
    .exp-topic { font-weight: 500; color: #1976d2; flex: 1; }
    .exp-counts { color: #666; font-size: 12px; }
    .exp-time   { color: #999; font-size: 11px; }

    .message-item {
      border: 1px solid #eee; border-radius: 4px;
      padding: 8px 10px; margin-bottom: 8px;
    }
    .sent-message     { border-left: 3px solid #42a5f5; }
    .received-message { border-left: 3px solid #66bb6a; }

    .msg-topic { font-size: 12px; font-weight: 600; color: #555; margin-bottom: 4px; }
    .msg-headers { font-size: 11px; color: #888; margin-top: 4px; }

    .msg-payload {
      background: #1e1e1e; color: #d4d4d4;
      padding: 8px 10px; border-radius: 4px;
      font-size: 11px; line-height: 1.4;
      overflow-x: auto; max-height: 200px; overflow-y: auto;
      margin: 4px 0; white-space: pre-wrap; word-break: break-all;
    }

    .conditions-badge { font-size: 11px; padding: 2px 6px; border-radius: 3px; margin-left: 8px; }
    .cond-ok   { background: #c8e6c9; color: #1b5e20; }
    .cond-fail { background: #ffcdd2; color: #b71c1c; }

    .failed-conditions { margin-top: 6px; font-size: 12px; }
    .failed-title { font-weight: 600; color: #c62828; }
    .failed-condition { color: #666; margin-left: 8px; line-height: 1.6; }
    .failed-condition code { background: #f5f5f5; padding: 1px 4px; border-radius: 3px; }

    .match-section { background: #fffde7; padding: 8px; border-radius: 4px; border-left: 3px solid #ffd54f; }

    .log-actions { display: flex; gap: 8px; margin-top: 10px; }

    .log-loading { padding: 16px; text-align: center; color: #999; }
    .log-loading p { margin: 8px 0 0 0; }

    .log-text {
      background:#1e1e1e; color:#d4d4d4; padding:12px; border-radius:4px;
      font-size:11px; line-height:1.5; margin:0; max-height:300px; overflow-y:auto;
      white-space: pre-wrap; word-break: break-all;
    }

    .log-stats {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(120px, 1fr));
      gap: 16px; margin-top: 24px; padding-top: 24px; border-top: 1px solid #eee;
    }
    .stat { text-align:center; padding:12px; background:#f5f5f5; border-radius:4px; }
    .stat-label { display:block; font-size:12px; color:#999; font-weight:500; margin-bottom:4px; text-transform:uppercase; }
    .stat-value { display:block; font-size:24px; font-weight:500; color:#333; }
    .stat-value.passed  { color:#2e7d32; }
    .stat-value.failed  { color:#c62828; }
    .stat-value.skipped { color:#ef6c00; }
  `]
})
export class LogsComponent implements OnInit {
  filteredLogs: LogEntry[] = [];
  allLogs: LogEntry[] = [];
  searchText = '';
  isLoading = false;
  expandedLogIndex = -1;

  constructor(
    private api: ApiService,
    private snackBar: MatSnackBar,
    public appConfigService: AppConfigService,
    private exportService: ExportService,
  ) {}

  ngOnInit() {
    this.loadLogs();
  }

  loadLogs() {
    this.isLoading = true;
    this.api.getTestLogs().subscribe({
      next: (response) => {
        const logData = response?.logs || (Array.isArray(response) ? response : []);

        this.allLogs = logData.map((file: any, index: number) => ({
          testId: file.relative_path?.split('/').pop()?.replace('.test.log', '') || `log-${index}`,
          fullPath: file.path,
          relativePath: file.relative_path,
          timestamp: new Date(file.modified ? file.modified * 1000 : Date.now()),
          status: file.status || 'UNKNOWN',
          duration: file.elapsed_ms || 0,
          size: file.size_bytes,
          runCount: file.run_count || 0,
          runs: null,   // loaded lazily
          preview: file.content_preview,
          summary: null,
        } as LogEntry));

        this.filteredLogs = [...this.allLogs];
        this.isLoading = false;

        if (this.allLogs.length === 0) {
          this.snackBar.open('No test logs found', 'Close', { duration: 3000 });
        }
      },
      error: (err) => {
        this.isLoading = false;
        this.snackBar.open('Failed to load logs', 'Close', { duration: 5000 });
        console.error('Error loading logs:', err);
      }
    });
  }

  onLogOpened(log: LogEntry, idx: number) {
    this.expandedLogIndex = idx;
    if (log.runs !== null) return;  // already loaded

    // Mark as loading
    log.runs = null;

    this.api.getTestLog(log.testId).subscribe({
      next: (response: any) => {
        if (response?.runs && Array.isArray(response.runs)) {
          log.runs = response.runs as RunEntry[];
          // Update status/duration from newest run
          if (log.runs.length > 0) {
            log.status = log.runs[0].status || log.status;
            log.duration = log.runs[0].elapsed_ms || log.duration;
            log.runCount = log.runs.length;
          }
        } else {
          // Legacy: wrap single content string as a raw run
          const content = typeof response === 'string' ? response : (response?.content || JSON.stringify(response, null, 2));
          log.runs = [{ status: log.status, elapsed_ms: log.duration, raw: content }];
        }
      },
      error: (err) => {
        log.runs = [{ status: 'ERROR', elapsed_ms: 0, raw: 'Error loading log: ' + (err.message || 'Unknown error') }];
      }
    });
  }

  filterLogs() {
    if (!this.searchText.trim()) {
      this.filteredLogs = [...this.allLogs];
    } else {
      const searchLower = this.searchText.toLowerCase();
      this.filteredLogs = this.allLogs.filter(log =>
        log.testId.toLowerCase().includes(searchLower)
      );
    }
    this.expandedLogIndex = -1;
  }

  getStatusCount(status: string): number {
    return this.filteredLogs.filter(log => log.status === status).length;
  }

  copyRun(run: RunEntry) {
    const text = run.raw ?? JSON.stringify(run, null, 2);
    navigator.clipboard.writeText(text).then(() => {
      this.snackBar.open('Run copied to clipboard!', 'Close', { duration: 2000 });
    });
  }

  downloadRun(testId: string, run: RunEntry, index: number) {
    const text = run.raw ?? JSON.stringify(run, null, 2);
    const element = document.createElement('a');
    element.setAttribute('href', 'data:text/plain;charset=utf-8,' + encodeURIComponent(text));
    element.setAttribute('download', `${testId}-run-${index + 1}.log`);
    element.style.display = 'none';
    document.body.appendChild(element);
    element.click();
    document.body.removeChild(element);
    this.snackBar.open('Run downloaded!', 'Close', { duration: 2000 });
  }

  exportLogs() {
    const logs = this.filteredLogs;
    const isFiltered = !!this.searchText.trim();
    if (logs.length === 0) return;

    const fmt = this.appConfigService.getExportFormat();
    const ts = new Date().toISOString().replace(/[:.]/g, '-').slice(0, 19);
    const label = isFiltered ? 'filtered-' : '';

    const doExport = () => {
      switch (fmt) {
        case 'html':
          this.exportService.downloadHtml(
            `test-logs-${label}${ts}.html`,
            this.exportService.buildLogsHtml(logs, isFiltered)
          );
          break;
        case 'csv': {
          const { headers, rows } = this.exportService.buildLogsCsv(logs);
          this.exportService.downloadCsv(`test-logs-${label}${ts}.csv`, headers, rows);
          break;
        }
        default:
          this.exportService.downloadJson(
            `test-logs-${label}${ts}.json`,
            this.exportService.buildLogsJson(logs, isFiltered)
          );
      }
      this.snackBar.open(
        `${logs.length} log(s) exported as ${fmt.toUpperCase()}${isFiltered ? ' (filtered view)' : ''}`,
        'Close',
        { duration: 3000 }
      );
    };

    // CSV only needs list-level summary — no need to pre-load run details
    if (fmt === 'csv') { doExport(); return; }

    // For JSON / HTML: fetch any runs not yet loaded so the export is complete
    const logsToLoad = logs.filter(l => l.runs === null);
    if (logsToLoad.length === 0) { doExport(); return; }

    this.snackBar.open(`Loading ${logsToLoad.length} log(s)…`, undefined, { duration: 2000 });
    const requests = logsToLoad.map(log =>
      this.api.getTestLog(log.testId).pipe(
        map((resp: any) => ({ log, resp })),
        catchError(() => of({ log, resp: null as any }))
      )
    );

    forkJoin(requests).subscribe((results: any[]) => {
      results.forEach(({ log: l, resp }) => {
        if (resp?.runs && Array.isArray(resp.runs)) {
          l.runs = resp.runs;
          if (l.runs.length > 0) {
            l.status   = l.runs[0].status    || l.status;
            l.duration = l.runs[0].elapsed_ms || l.duration;
            l.runCount = l.runs.length;
          }
        } else {
          l.runs = [];
        }
      });
      doExport();
    });
  }
}
