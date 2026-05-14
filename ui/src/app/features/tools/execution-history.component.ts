import { ChangeDetectionStrategy, ChangeDetectorRef, Component, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { RouterModule } from '@angular/router';
import { MatCardModule } from '@angular/material/card';
import { MatTableModule } from '@angular/material/table';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatInputModule } from '@angular/material/input';
import { MatExpansionModule } from '@angular/material/expansion';
import { MatSnackBar, MatSnackBarModule } from '@angular/material/snack-bar';
import { MatCheckboxModule } from '@angular/material/checkbox';
import { MatTabsModule } from '@angular/material/tabs';
import { MatChipsModule } from '@angular/material/chips';
import { MatTooltipModule } from '@angular/material/tooltip';
import { LoadHistoryService } from '../../core/services/load-history.service';
import { LoadReport } from '../../core/models';

@Component({
  selector: 'app-execution-history',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    CommonModule,
    FormsModule,
    RouterModule,
    MatCardModule,
    MatTableModule,
    MatButtonModule,
    MatIconModule,
    MatFormFieldModule,
    MatInputModule,
    MatExpansionModule,
    MatSnackBarModule,
    MatCheckboxModule,
    MatTabsModule,
    MatChipsModule,
    MatTooltipModule
  ],
  template: `
    <div class="container">
      <mat-card>
        <mat-card-header>
          <mat-card-title>Test Execution History</mat-card-title>
          <mat-card-subtitle>View and compare test execution results over time</mat-card-subtitle>
        </mat-card-header>
        <mat-card-content>
          <!-- Storage Info -->
          <div class="storage-info">
            <mat-icon>info</mat-icon>
            <span>Execution history is stored in browser local storage.
                  <button mat-button (click)="clearHistory()">Clear All</button>
            </span>
          </div>

          <mat-tab-group>
            <!-- Recent Executions Tab (rendered eagerly — this is the landing tab) -->
            <mat-tab label="Recent Executions">
              <div class="tab-content">
                <!-- Execution List -->
                <div *ngIf="executionHistory.length === 0" class="empty-state">
                  <mat-icon>history</mat-icon>
                  <p>No execution history yet. Run some tests to see results here.</p>
                </div>

                <div *ngFor="let execution of recentHistory; trackBy: trackByTimestamp"
                     class="execution-item">
                  <div class="execution-header"
                       [ngClass]="'status-' + (execution.result.passed > 0 ? 'passed' : 'failed')">
                    <mat-checkbox [(ngModel)]="execution.selected" (ngModelChange)="updateSelection()">
                    </mat-checkbox>

                    <div class="execution-info">
                      <span class="execution-time">{{ execution.timestamp | date:'short' }}</span>
                      <span class="execution-mode">{{ execution.mode }} mode</span>
                      <span class="execution-count">{{ execution.testCount }} test(s)</span>
                    </div>

                    <div class="execution-stats">
                      <span class="stat passed">✓ {{ execution.result.passed }}</span>
                      <span class="stat failed">✗ {{ execution.result.failed }}</span>
                      <span class="stat skipped">⊘ {{ execution.result.skipped }}</span>
                      <span class="stat duration">{{ execution.result.elapsed_ms }}ms</span>
                    </div>

                    <button mat-icon-button (click)="toggleExpanded(execution)" matTooltip="Details">
                      <mat-icon>expand_more</mat-icon>
                    </button>
                  </div>

                  <!-- Execution Details -->
                  <mat-expansion-panel *ngIf="execution.expanded" [expanded]="true" class="details-panel">
                    <div class="execution-details">
                      <h4>Test Results</h4>
                      <div class="results-grid">
                        <div *ngFor="let test of execution.previewResults; trackBy: trackByTestId" class="result-item">
                          <span [ngClass]="'status-badge status-' + (test.status | lowercase)">
                            {{ test.status }}
                          </span>
                          <span class="test-id">{{ test.test_id }}</span>
                          <span class="duration">{{ test.elapsed_ms }}ms</span>
                        </div>
                      </div>

                      <div *ngIf="execution.result.results.length > 10" class="more-results">
                        +{{ execution.result.results.length - 10 }} more results
                      </div>

                      <h4>Summary</h4>
                      <div class="summary-table">
                        <div class="summary-row">
                          <span class="label">Total Tests</span>
                          <span class="value">{{ execution.result.total }}</span>
                        </div>
                        <div class="summary-row">
                          <span class="label">Passed</span>
                          <span class="value passed">{{ execution.result.passed }}</span>
                        </div>
                        <div class="summary-row">
                          <span class="label">Failed</span>
                          <span class="value failed">{{ execution.result.failed }}</span>
                        </div>
                        <div class="summary-row">
                          <span class="label">Skipped</span>
                          <span class="value skipped">{{ execution.result.skipped }}</span>
                        </div>
                        <div class="summary-row">
                          <span class="label">Duration</span>
                          <span class="value">{{ execution.result.elapsed_ms }}ms</span>
                        </div>
                        <div class="summary-row">
                          <span class="label">Repeat Count</span>
                          <span class="value">{{ execution.result.repeat || 1 }}</span>
                        </div>
                      </div>

                      <div class="detail-actions">
                        <button mat-stroked-button (click)="exportExecution(execution)">
                          <mat-icon>download</mat-icon>
                          Export
                        </button>
                      </div>
                    </div>
                  </mat-expansion-panel>
                </div>
              </div>
            </mat-tab>

            <!-- Comparison Tab (lazy: rendered only when first activated) -->
            <mat-tab label="Compare Executions">
              <ng-template matTabContent>
              <div class="tab-content">
                <h3>Select 2-4 Executions to Compare</h3>
                <p class="hint">{{ selectedCount }} execution(s) selected</p>

                <div *ngIf="selectedCount < 2" class="comparison-placeholder">
                  <mat-icon>compare_arrows</mat-icon>
                  <p>Select at least 2 executions from the list below to see comparison</p>
                </div>

                <div *ngIf="selectedCount >= 2" class="comparison-results">
                  <div class="comparison-header">
                    <h4>Pass Rate Trend</h4>
                  </div>
                  <div class="trend-chart">
                    <div *ngFor="let exec of selectedExecutions; trackBy: trackByTimestamp" class="trend-column">
                      <div class="trend-bar">
                        <div class="trend-passed" [style.height.%]="(exec.result.passed / exec.result.total) * 100"></div>
                        <div class="trend-failed" [style.height.%]="(exec.result.failed / exec.result.total) * 100"></div>
                        <div class="trend-skipped" [style.height.%]="(exec.result.skipped / exec.result.total) * 100"></div>
                      </div>
                      <div class="trend-label">{{ exec.timestamp | date:'short' }}</div>
                      <div class="trend-value">
                        {{ ((exec.result.passed / exec.result.total) * 100).toFixed(0) }}%
                      </div>
                    </div>
                  </div>

                  <h4>Statistics Comparison</h4>
                  <div class="comparison-table">
                    <table>
                      <thead>
                        <tr>
                          <th>Metric</th>
                          <th *ngFor="let exec of selectedExecutions; let i = index; trackBy: trackByTimestamp">
                            Run {{ i + 1 }}<br/>
                            <span class="timestamp">{{ exec.timestamp | date:'short' }}</span>
                          </th>
                          <th *ngIf="selectedCount > 1">Change</th>
                        </tr>
                      </thead>
                      <tbody>
                        <tr>
                          <td>Pass Rate</td>
                          <td *ngFor="let exec of selectedExecutions; trackBy: trackByTimestamp">
                            {{ ((exec.result.passed / exec.result.total) * 100).toFixed(1) }}%
                          </td>
                          <td *ngIf="selectedCount > 1">{{ changePassRate }}</td>
                        </tr>
                        <tr>
                          <td>Total Tests</td>
                          <td *ngFor="let exec of selectedExecutions; trackBy: trackByTimestamp">{{ exec.result.total }}</td>
                          <td *ngIf="selectedCount > 1">-</td>
                        </tr>
                        <tr>
                          <td>Duration</td>
                          <td *ngFor="let exec of selectedExecutions; trackBy: trackByTimestamp">{{ exec.result.elapsed_ms }}ms</td>
                          <td *ngIf="selectedCount > 1">{{ changeDuration }}</td>
                        </tr>
                        <tr>
                          <td>Avg per Test</td>
                          <td *ngFor="let exec of selectedExecutions; trackBy: trackByTimestamp">
                            {{ (exec.result.elapsed_ms / exec.result.total).toFixed(0) }}ms
                          </td>
                          <td *ngIf="selectedCount > 1">-</td>
                        </tr>
                      </tbody>
                    </table>
                  </div>

                  <button mat-raised-button (click)="exportComparison()">
                    <mat-icon>download</mat-icon>
                    Export Comparison
                  </button>
                </div>

                <h4>Execution List (Click to select)</h4>
                <div class="selection-list">
                  <div *ngFor="let execution of recentHistory; trackBy: trackByTimestamp"
                       class="selection-item"
                       [class.selected]="execution.selected"
                       (click)="execution.selected = !execution.selected; updateSelection()">
                    <mat-checkbox [checked]="execution.selected"></mat-checkbox>
                    <span class="timestamp">{{ execution.timestamp | date:'short' }}</span>
                    <span class="stats">
                      ✓ {{ execution.result.passed }}
                      ✗ {{ execution.result.failed }}
                      ⊘ {{ execution.result.skipped }}
                    </span>
                  </div>
                </div>
              </div>
              </ng-template>
            </mat-tab>

            <!-- Statistics Tab (lazy) -->
            <mat-tab label="Overall Statistics">
              <ng-template matTabContent>
              <div class="tab-content">
                <h3>Execution Statistics</h3>

                <div *ngIf="executionHistory.length === 0" class="empty-state">
                  <mat-icon>assessment</mat-icon>
                  <p>No data to display</p>
                </div>

                <div *ngIf="executionHistory.length > 0" class="stats-grid">
                  <div class="stat-card">
                    <div class="stat-label">Total Executions</div>
                    <div class="stat-value">{{ executionHistory.length }}</div>
                  </div>
                  <div class="stat-card">
                    <div class="stat-label">Total Tests Run</div>
                    <div class="stat-value">{{ totalTestsRun }}</div>
                  </div>
                  <div class="stat-card">
                    <div class="stat-label">Overall Pass Rate</div>
                    <div class="stat-value" [ngClass]="overallPassRate > 80 ? 'good' : 'warning'">
                      {{ overallPassRate.toFixed(1) }}%
                    </div>
                  </div>
                  <div class="stat-card">
                    <div class="stat-label">Avg Duration</div>
                    <div class="stat-value">{{ averageDuration }}ms</div>
                  </div>
                  <div class="stat-card">
                    <div class="stat-label">Fastest Run</div>
                    <div class="stat-value">{{ fastestRun }}ms</div>
                  </div>
                  <div class="stat-card">
                    <div class="stat-label">Slowest Run</div>
                    <div class="stat-value">{{ slowestRun }}ms</div>
                  </div>
                </div>

                <h4>Execution Timeline</h4>
                <div class="timeline">
                  <div *ngFor="let execution of recentHistoryReversed; trackBy: trackByTimestamp"
                       class="timeline-item"
                       [ngClass]="'status-' + (execution.result.passed > 0 ? 'passed' : 'failed')">
                    <div class="timeline-dot"></div>
                    <div class="timeline-content">
                      <span class="timeline-time">{{ execution.timestamp | date:'short' }}</span>
                      <span class="timeline-stats">
                        {{ execution.result.passed }}/{{ execution.result.total }}
                        ({{ (execution.result.elapsed_ms / execution.result.total).toFixed(0) }}ms/test)
                      </span>
                    </div>
                  </div>
                </div>
              </div>
              </ng-template>
            </mat-tab>

            <!-- Load Test Reports Tab (lazy) -->
            <mat-tab label="Load Test Reports">
              <ng-template matTabContent>
              <div class="tab-content">
                <div class="ltreports-toolbar">
                  <span class="ltreports-count">{{ loadTestReports.length }} saved report(s)</span>
                  <button mat-stroked-button color="warn"
                          *ngIf="loadTestReports.length > 0"
                          (click)="clearLoadReports()">
                    <mat-icon>delete_sweep</mat-icon> Clear All Reports
                  </button>
                </div>

                <div *ngIf="loadTestReports.length === 0" class="empty-state">
                  <mat-icon>speed</mat-icon>
                  <p>No load test reports saved yet. Run a load test to see reports here.</p>
                </div>

                <div *ngFor="let r of loadTestReports; trackBy: trackByJobId" class="ltreport-row">
                  <div class="ltreport-status" [ngClass]="'ltr-status-' + r.status.toLowerCase()">
                    <mat-icon>{{ r.status === 'COMPLETED' ? 'check_circle' : r.status === 'FAILED' ? 'error' : 'cancel' }}</mat-icon>
                  </div>
                  <div class="ltreport-info">
                    <div class="ltreport-name">{{ r.scenario_name }}</div>
                    <div class="ltreport-meta">
                      {{ r.started_at | date:'short' }} &nbsp;·&nbsp;
                      {{ r.total_duration_s }}s &nbsp;·&nbsp;
                      {{ r.total_requests | number }} requests &nbsp;·&nbsp;
                      <span [class.ltreport-err]="r.error_rate_pct > 2">
                        {{ r.error_rate_pct | number:'1.1-1' }}% errors
                      </span>
                    </div>
                    <div class="ltreport-kpis">
                      <span class="ltreport-kpi ok">OK {{ r.total_ok | number }}</span>
                      <span class="ltreport-kpi ko">KO {{ r.total_ko | number }}</span>
                      <span class="ltreport-kpi">p90 {{ r.p90_ms | number:'1.0-0' }}ms</span>
                      <span class="ltreport-kpi">p99 {{ r.p99_ms | number:'1.0-0' }}ms</span>
                    </div>
                  </div>
                  <div class="ltreport-actions">
                    <button mat-icon-button color="primary"
                            [routerLink]="['/tests/load-report', r.job_id]"
                            matTooltip="View full report">
                      <mat-icon>open_in_new</mat-icon>
                    </button>
                    <button mat-icon-button color="warn"
                            (click)="deleteLoadReport(r.job_id)"
                            matTooltip="Delete this report">
                      <mat-icon>delete</mat-icon>
                    </button>
                  </div>
                </div>
              </div>
              </ng-template>
            </mat-tab>
          </mat-tab-group>
        </mat-card-content>
      </mat-card>
    </div>
  `,
  styles: [`
    .container {
      padding: 24px;
      max-width: 1400px;
      margin: 0 auto;
    }

    .tab-content {
      padding: 24px;
    }

    .storage-info {
      display: flex;
      gap: 12px;
      align-items: center;
      padding: 12px;
      background-color: #e3f2fd;
      border-left: 3px solid #1976d2;
      border-radius: 3px;
      margin-bottom: 24px;
      font-size: 14px;
      color: #0d47a1;
    }

    .storage-info mat-icon {
      flex-shrink: 0;
    }

    .empty-state {
      text-align: center;
      padding: 60px 24px;
      color: #999;
    }

    .empty-state mat-icon {
      font-size: 64px;
      width: 64px;
      height: 64px;
      color: #bdbdbd;
      margin-bottom: 16px;
    }

    .execution-item {
      margin-bottom: 12px;
      border: 1px solid #eee;
      border-radius: 4px;
      overflow: hidden;
    }

    .execution-header {
      display: flex;
      gap: 16px;
      padding: 12px;
      background-color: #f9f9f9;
      align-items: center;
      cursor: pointer;
      transition: background-color 0.2s;
    }

    .execution-header:hover {
      background-color: #f5f5f5;
    }

    .execution-header.status-passed {
      border-left: 3px solid #4caf50;
    }

    .execution-header.status-failed {
      border-left: 3px solid #f44336;
    }

    .execution-info {
      flex: 1;
      display: flex;
      gap: 12px;
      align-items: center;
      font-size: 12px;
      flex-wrap: wrap;
    }

    .execution-time {
      font-weight: 500;
      color: #333;
    }

    .execution-mode {
      background-color: #e3f2fd;
      color: #1976d2;
      padding: 2px 6px;
      border-radius: 3px;
      font-size: 11px;
    }

    .execution-count {
      color: #999;
    }

    .execution-stats {
      display: flex;
      gap: 12px;
      font-size: 12px;
      font-weight: 500;
    }

    .stat {
      padding: 2px 6px;
      border-radius: 3px;
    }

    .stat.passed {
      background-color: #c8e6c9;
      color: #1b5e20;
    }

    .stat.failed {
      background-color: #ffcdd2;
      color: #b71c1c;
    }

    .stat.skipped {
      background-color: #ffe0b2;
      color: #e65100;
    }

    .stat.duration {
      background-color: #f5f5f5;
      color: #333;
    }

    .details-panel {
      margin: 0;
      box-shadow: none;
      border-top: 1px solid #eee;
    }

    .execution-details {
      padding: 16px;
    }

    .execution-details h4 {
      margin: 0 0 12px 0;
      color: #333;
      font-size: 14px;
    }

    .results-grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
      gap: 8px;
      margin-bottom: 16px;
    }

    .result-item {
      padding: 8px;
      background-color: #f9f9f9;
      border-radius: 3px;
      display: flex;
      gap: 8px;
      align-items: center;
      font-size: 12px;
    }

    .status-badge {
      padding: 2px 6px;
      border-radius: 3px;
      font-size: 11px;
      font-weight: 500;
    }

    .status-passed {
      background-color: #c8e6c9;
      color: #1b5e20;
    }

    .status-failed {
      background-color: #ffcdd2;
      color: #b71c1c;
    }

    .status-skipped {
      background-color: #ffe0b2;
      color: #e65100;
    }

    .test-id {
      flex: 1;
      font-family: 'Courier New', monospace;
      color: #666;
    }

    .duration {
      color: #999;
    }

    .more-results {
      color: #999;
      font-size: 12px;
      margin-top: 8px;
    }

    .summary-table {
      background-color: #f9f9f9;
      border-radius: 3px;
      margin-bottom: 16px;
    }

    .summary-row {
      display: flex;
      justify-content: space-between;
      padding: 8px 12px;
      border-bottom: 1px solid #eee;
      font-size: 13px;
    }

    .summary-row:last-child {
      border-bottom: none;
    }

    .summary-row .label {
      font-weight: 500;
      color: #666;
    }

    .summary-row .value {
      font-weight: 500;
      color: #333;
    }

    .summary-row .value.passed {
      color: #2e7d32;
    }

    .summary-row .value.failed {
      color: #c62828;
    }

    .summary-row .value.skipped {
      color: #ef6c00;
    }

    .detail-actions {
      display: flex;
      gap: 8px;
      margin-top: 16px;
    }

    .comparison-placeholder {
      text-align: center;
      padding: 60px 24px;
      background-color: #f9f9f9;
      border-radius: 4px;
      color: #999;
      margin-bottom: 24px;
    }

    .comparison-placeholder mat-icon {
      font-size: 48px;
      width: 48px;
      height: 48px;
      color: #bdbdbd;
      margin-bottom: 16px;
    }

    .comparison-results {
      margin-bottom: 24px;
    }

    .comparison-header {
      margin-bottom: 16px;
    }

    .comparison-header h4 {
      margin: 0;
      color: #333;
      font-size: 14px;
    }

    .trend-chart {
      display: flex;
      gap: 16px;
      align-items: flex-end;
      height: 200px;
      margin-bottom: 24px;
      padding: 12px;
      background-color: #f9f9f9;
      border-radius: 4px;
    }

    .trend-column {
      flex: 1;
      display: flex;
      flex-direction: column;
      align-items: center;
      gap: 8px;
      height: 100%;
    }

    .trend-bar {
      width: 40px;
      height: 150px;
      background-color: #eee;
      border-radius: 3px;
      overflow: hidden;
      display: flex;
      flex-direction: column-reverse;
    }

    .trend-passed {
      background-color: #4caf50;
    }

    .trend-failed {
      background-color: #f44336;
    }

    .trend-skipped {
      background-color: #ff9800;
    }

    .trend-label {
      font-size: 11px;
      color: #999;
      text-align: center;
    }

    .trend-value {
      font-size: 14px;
      font-weight: 500;
      color: #333;
    }

    .comparison-table {
      margin-bottom: 24px;
    }

    .comparison-table h4 {
      margin: 0 0 12px 0;
      color: #333;
      font-size: 14px;
    }

    .comparison-table table {
      width: 100%;
      border-collapse: collapse;
      border: 1px solid #eee;
      border-radius: 4px;
      overflow: hidden;
    }

    .comparison-table th,
    .comparison-table td {
      padding: 12px;
      text-align: left;
      border-bottom: 1px solid #eee;
      font-size: 12px;
    }

    .comparison-table th {
      background-color: #f9f9f9;
      font-weight: 500;
      color: #333;
    }

    .comparison-table td {
      font-family: 'Courier New', monospace;
    }

    .timestamp {
      display: block;
      font-size: 10px;
      color: #999;
      margin-top: 2px;
    }

    .selection-list {
      display: flex;
      flex-direction: column;
      gap: 8px;
      margin-top: 16px;
    }

    .selection-item {
      display: flex;
      gap: 12px;
      padding: 12px;
      background-color: #f9f9f9;
      border-radius: 3px;
      cursor: pointer;
      border: 1px solid #eee;
      align-items: center;
    }

    .selection-item:hover {
      background-color: #f5f5f5;
    }

    .selection-item.selected {
      background-color: #e3f2fd;
      border-color: #1976d2;
    }

    .selection-item .timestamp {
      flex: 0 0 auto;
      font-weight: 500;
      color: #333;
      margin: 0;
    }

    .selection-item .stats {
      flex: 1;
      font-size: 12px;
      color: #666;
    }

    .stats-grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
      gap: 16px;
      margin-bottom: 24px;
    }

    .stat-card {
      padding: 16px;
      background-color: #f9f9f9;
      border-radius: 4px;
      text-align: center;
    }

    .stat-label {
      font-size: 12px;
      color: #999;
      margin-bottom: 8px;
      text-transform: uppercase;
      font-weight: 500;
    }

    .stat-value {
      font-size: 28px;
      font-weight: 500;
      color: #333;
    }

    .stat-value.good {
      color: #2e7d32;
    }

    .stat-value.warning {
      color: #f57c00;
    }

    .timeline {
      position: relative;
      padding-left: 24px;
      margin-top: 16px;
    }

    .timeline::before {
      content: '';
      position: absolute;
      left: 8px;
      top: 0;
      bottom: 0;
      width: 2px;
      background-color: #eee;
    }

    .timeline-item {
      display: flex;
      gap: 16px;
      margin-bottom: 12px;
      position: relative;
    }

    .timeline-dot {
      position: absolute;
      left: -16px;
      top: 4px;
      width: 12px;
      height: 12px;
      border-radius: 50%;
      background-color: #eee;
      border: 2px solid white;
    }

    .timeline-item.status-passed .timeline-dot {
      background-color: #4caf50;
    }

    .timeline-item.status-failed .timeline-dot {
      background-color: #f44336;
    }

    .timeline-content {
      display: flex;
      gap: 12px;
      padding: 8px;
      background-color: #f9f9f9;
      border-radius: 3px;
      flex: 1;
      font-size: 12px;
    }

    .timeline-time {
      font-weight: 500;
      color: #333;
      white-space: nowrap;
    }

    .timeline-stats {
      color: #666;
    }

    h3, h4 {
      margin: 0 0 16px 0;
    }

    h3 {
      color: #333;
      font-size: 18px;
    }

    h4 {
      color: #333;
      font-size: 14px;
    }

    .hint {
      color: #999;
      font-size: 12px;
      margin: 0 0 16px 0;
    }

    /* ── Load Test Reports tab ── */
    .ltreports-toolbar {
      display: flex;
      align-items: center;
      justify-content: space-between;
      margin-bottom: 16px;
    }
    .ltreports-count {
      font-size: 13px;
      color: #999;
    }
    .ltreport-row {
      display: flex;
      align-items: center;
      gap: 12px;
      padding: 14px 16px;
      border: 1px solid #e0e0e0;
      border-radius: 6px;
      margin-bottom: 10px;
      background: #fafafa;
      transition: box-shadow .15s;
    }
    .ltreport-row:hover {
      box-shadow: 0 2px 8px rgba(0,0,0,.1);
    }
    .ltreport-status mat-icon {
      font-size: 28px;
      width: 28px;
      height: 28px;
    }
    .ltr-status-completed mat-icon { color: #4caf50; }
    .ltr-status-failed    mat-icon { color: #f44336; }
    .ltr-status-cancelled mat-icon { color: #ff9800; }

    .ltreport-info {
      flex: 1;
      min-width: 0;
    }
    .ltreport-name {
      font-weight: 600;
      font-size: 14px;
      color: #333;
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
    }
    .ltreport-meta {
      font-size: 12px;
      color: #888;
      margin-top: 2px;
    }
    .ltreport-err { color: #f44336; font-weight: 600; }
    .ltreport-kpis {
      display: flex;
      gap: 8px;
      margin-top: 6px;
      flex-wrap: wrap;
    }
    .ltreport-kpi {
      font-size: 11px;
      padding: 2px 8px;
      border-radius: 12px;
      background: #f0f0f0;
      color: #555;
    }
    .ltreport-kpi.ok { background: #e8f5e9; color: #2e7d32; }
    .ltreport-kpi.ko { background: #ffebee; color: #c62828; }
    .ltreport-actions {
      display: flex;
      flex-direction: column;
      gap: 4px;
    }
  `]
})
export class ExecutionHistoryComponent implements OnInit {
  executionHistory: ExecutionRecord[] = [];
  /** Sliced to first 20 entries — used directly in templates instead of piping every cycle */
  recentHistory: ExecutionRecord[] = [];
  /** Last 15 entries in reverse order for the timeline — pre-computed once */
  recentHistoryReversed: ExecutionRecord[] = [];
  selectedExecutions: ExecutionRecord[] = [];
  selectedCount = 0;
  loadTestReports: LoadReport[] = [];

  // Pre-computed aggregate stats (updated once after data changes)
  totalTestsRun = 0;
  overallPassRate = 0;
  averageDuration = 0;
  fastestRun = 0;
  slowestRun = 0;

  // Pre-computed comparison strings
  changePassRate = '-';
  changeDuration = '-';

  constructor(
    private snackBar: MatSnackBar,
    private loadHistorySvc: LoadHistoryService,
    private cdr: ChangeDetectorRef,
  ) {}

  ngOnInit() {
    this.loadHistory();
    this.loadTestReports = this.loadHistorySvc.getAllReports();
  }

  loadHistory() {
    const stored = localStorage.getItem('test_execution_history');
    if (stored) {
      try {
        this.executionHistory = JSON.parse(stored).map((exec: any) => ({
          ...exec,
          timestamp: new Date(exec.timestamp),
          selected: false,
          expanded: false,
          previewResults: Array.isArray(exec.result?.results)
            ? exec.result.results.slice(0, 10)
            : [],
        }));
      } catch (e) {
        console.error('Failed to parse execution history:', e);
      }
    }
    this.computeDerivedData();
  }

  /** Compute all derived arrays and aggregate stats once so templates only read properties. */
  private computeDerivedData() {
    const h = this.executionHistory;
    this.recentHistory = h.slice(0, 20);
    this.recentHistoryReversed = h.slice().reverse().slice(0, 15);

    if (h.length === 0) {
      this.totalTestsRun = 0;
      this.overallPassRate = 0;
      this.averageDuration = 0;
      this.fastestRun = 0;
      this.slowestRun = 0;
    } else {
      const total = h.reduce((s, e) => s + e.result.total, 0);
      const passed = h.reduce((s, e) => s + e.result.passed, 0);
      const totalMs = h.reduce((s, e) => s + e.result.elapsed_ms, 0);
      this.totalTestsRun = total;
      this.overallPassRate = total === 0 ? 0 : (passed / total) * 100;
      this.averageDuration = Math.round(totalMs / h.length);
      this.fastestRun = Math.min(...h.map(e => e.result.elapsed_ms));
      this.slowestRun = Math.max(...h.map(e => e.result.elapsed_ms));
    }
    this.computeChangeStats();
  }

  private computeChangeStats() {
    if (this.selectedExecutions.length < 2) {
      this.changePassRate = '-';
      this.changeDuration = '-';
      return;
    }
    const first = this.selectedExecutions[0];
    const last = this.selectedExecutions[this.selectedExecutions.length - 1];
    const rateChange = ((last.result.passed / last.result.total) - (first.result.passed / first.result.total)) * 100;
    this.changePassRate = rateChange > 0 ? `+${rateChange.toFixed(1)}%` : `${rateChange.toFixed(1)}%`;
    const msChange = last.result.elapsed_ms - first.result.elapsed_ms;
    this.changeDuration = msChange > 0 ? `+${msChange}ms` : `${msChange}ms`;
  }

  updateSelection() {
    this.selectedExecutions = this.executionHistory.filter(e => e.selected);
    this.selectedCount = this.selectedExecutions.length;
    this.computeChangeStats();
    this.cdr.markForCheck();
  }

  toggleExpanded(execution: ExecutionRecord) {
    execution.expanded = !execution.expanded;
    this.cdr.markForCheck();
  }

  exportExecution(execution: ExecutionRecord) {
    const json = JSON.stringify(execution.result, null, 2);
    this.downloadFile(json, `execution-${execution.timestamp.getTime()}.json`);
    this.snackBar.open('Execution exported!', 'Close', { duration: 2000 });
  }

  exportComparison() {
    const comparison = {
      executions: this.selectedExecutions.map(e => ({
        timestamp: e.timestamp,
        passRate: (e.result.passed / e.result.total) * 100,
        ...e.result
      }))
    };
    const json = JSON.stringify(comparison, null, 2);
    this.downloadFile(json, `comparison-${Date.now()}.json`);
    this.snackBar.open('Comparison exported!', 'Close', { duration: 2000 });
  }

  clearHistory() {
    if (confirm('Are you sure? This will delete all execution history.')) {
      localStorage.removeItem('test_execution_history');
      this.executionHistory = [];
      this.computeDerivedData();
      this.snackBar.open('History cleared', 'Close', { duration: 2000 });
      this.cdr.markForCheck();
    }
  }

  clearLoadReports() {
    if (confirm('Are you sure? This will delete all saved load test reports.')) {
      this.loadHistorySvc.clearAll();
      this.loadTestReports = [];
      this.snackBar.open('Load test reports cleared', 'Close', { duration: 2000 });
      this.cdr.markForCheck();
    }
  }

  deleteLoadReport(jobId: string) {
    this.loadHistorySvc.deleteReport(jobId);
    this.loadTestReports = this.loadHistorySvc.getAllReports();
    this.snackBar.open('Report deleted', 'Close', { duration: 2000 });
    this.cdr.markForCheck();
  }

  // ── trackBy helpers ──────────────────────────────────────────────────────
  trackByTimestamp(_: number, exec: ExecutionRecord): number {
    return exec.timestamp.getTime();
  }

  trackByTestId(index: number, test: any): string {
    return test?.test_id ?? index;
  }

  trackByJobId(_: number, r: LoadReport): string {
    return r.job_id;
  }

  private downloadFile(content: string, filename: string) {
    const element = document.createElement('a');
    element.setAttribute('href', 'data:text/plain;charset=utf-8,' + encodeURIComponent(content));
    element.setAttribute('download', filename);
    element.style.display = 'none';
    document.body.appendChild(element);
    element.click();
    document.body.removeChild(element);
  }
}

interface ExecutionRecord {
  timestamp: Date;
  mode: string;
  testCount: number;
  result: any;
  selected: boolean;
  expanded: boolean;
  /** First 10 results, pre-sliced on load to avoid repeated slicing in the template */
  previewResults: any[];
}



