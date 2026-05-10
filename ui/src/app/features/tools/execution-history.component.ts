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
import { MatCheckboxModule } from '@angular/material/checkbox';
import { MatTabsModule } from '@angular/material/tabs';
import { MatChipsModule } from '@angular/material/chips';
import { MatTooltipModule } from '@angular/material/tooltip';
import { SelectionModel } from '@angular/cdk/collections';

@Component({
  selector: 'app-execution-history',
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
            <!-- Recent Executions Tab -->
            <mat-tab label="Recent Executions">
              <div class="tab-content">
                <!-- Execution List -->
                <div *ngIf="executionHistory.length === 0" class="empty-state">
                  <mat-icon>history</mat-icon>
                  <p>No execution history yet. Run some tests to see results here.</p>
                </div>

                <div *ngFor="let execution of executionHistory | slice:0:20; let i = index"
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
                        <div *ngFor="let test of getTestResults(execution)" class="result-item">
                          <span [ngClass]="'status-badge status-' + getStatusClass(test)">
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

            <!-- Comparison Tab -->
            <mat-tab label="Compare Executions">
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
                    <div *ngFor="let exec of selectedExecutions" class="trend-column">
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
                          <th *ngFor="let exec of selectedExecutions; let i = index">
                            Run {{ i + 1 }}<br/>
                            <span class="timestamp">{{ exec.timestamp | date:'short' }}</span>
                          </th>
                          <th *ngIf="selectedCount > 1">Change</th>
                        </tr>
                      </thead>
                      <tbody>
                        <tr>
                          <td>Pass Rate</td>
                          <td *ngFor="let exec of selectedExecutions">
                            {{ ((exec.result.passed / exec.result.total) * 100).toFixed(1) }}%
                          </td>
                          <td *ngIf="selectedCount > 1">
                            {{ calculateChange('pass_rate') }}
                          </td>
                        </tr>
                        <tr>
                          <td>Total Tests</td>
                          <td *ngFor="let exec of selectedExecutions">{{ exec.result.total }}</td>
                          <td *ngIf="selectedCount > 1">-</td>
                        </tr>
                        <tr>
                          <td>Duration</td>
                          <td *ngFor="let exec of selectedExecutions">{{ exec.result.elapsed_ms }}ms</td>
                          <td *ngIf="selectedCount > 1">
                            {{ calculateChange('duration') }}
                          </td>
                        </tr>
                        <tr>
                          <td>Avg per Test</td>
                          <td *ngFor="let exec of selectedExecutions">
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
                  <div *ngFor="let execution of executionHistory | slice:0:20"
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
            </mat-tab>

            <!-- Statistics Tab -->
            <mat-tab label="Overall Statistics">
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
                    <div class="stat-value">{{ getTotalTestsRun() }}</div>
                  </div>
                  <div class="stat-card">
                    <div class="stat-label">Overall Pass Rate</div>
                    <div class="stat-value" [ngClass]="getOverallPassRate() > 80 ? 'good' : 'warning'">
                      {{ getOverallPassRate().toFixed(1) }}%
                    </div>
                  </div>
                  <div class="stat-card">
                    <div class="stat-label">Avg Duration</div>
                    <div class="stat-value">{{ getAverageDuration() }}ms</div>
                  </div>
                  <div class="stat-card">
                    <div class="stat-label">Fastest Run</div>
                    <div class="stat-value">{{ getFastestRun() }}ms</div>
                  </div>
                  <div class="stat-card">
                    <div class="stat-label">Slowest Run</div>
                    <div class="stat-value">{{ getSlowestRun() }}ms</div>
                  </div>
                </div>

                <h4>Execution Timeline</h4>
                <div class="timeline">
                  <div *ngFor="let execution of executionHistory.slice().reverse() | slice:0:15"
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
  `]
})
export class ExecutionHistoryComponent implements OnInit {
  executionHistory: ExecutionRecord[] = [];
  selectedExecutions: ExecutionRecord[] = [];
  selectedCount = 0;

  constructor(private snackBar: MatSnackBar) {}

  ngOnInit() {
    this.loadHistory();
  }

  loadHistory() {
    const stored = localStorage.getItem('test_execution_history');
    if (stored) {
      try {
        this.executionHistory = JSON.parse(stored).map((exec: any) => ({
          ...exec,
          timestamp: new Date(exec.timestamp),
          selected: false,
          expanded: false
        }));
      } catch (e) {
        console.error('Failed to parse execution history:', e);
      }
    }
  }

  updateSelection() {
    this.selectedExecutions = this.executionHistory.filter(e => e.selected);
    this.selectedCount = this.selectedExecutions.length;
  }

  toggleExpanded(execution: ExecutionRecord) {
    execution.expanded = !execution.expanded;
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
      this.snackBar.open('History cleared', 'Close', { duration: 2000 });
    }
  }

  calculateChange(metric: string): string {
    if (this.selectedExecutions.length < 2) return '-';
    const first = this.selectedExecutions[0];
    const last = this.selectedExecutions[this.selectedExecutions.length - 1];

    if (metric === 'pass_rate') {
      const firstRate = (first.result.passed / first.result.total) * 100;
      const lastRate = (last.result.passed / last.result.total) * 100;
      const change = lastRate - firstRate;
      return change > 0 ? `+${change.toFixed(1)}%` : `${change.toFixed(1)}%`;
    } else if (metric === 'duration') {
      const change = last.result.elapsed_ms - first.result.elapsed_ms;
      return change > 0 ? `+${change}ms` : `${change}ms`;
    }
    return '-';
  }

  getTotalTestsRun(): number {
    return this.executionHistory.reduce((sum, e) => sum + e.result.total, 0);
  }

  getOverallPassRate(): number {
    const total = this.executionHistory.reduce((sum, e) => sum + e.result.total, 0);
    const passed = this.executionHistory.reduce((sum, e) => sum + e.result.passed, 0);
    return total === 0 ? 0 : (passed / total) * 100;
  }

  getAverageDuration(): number {
    if (this.executionHistory.length === 0) return 0;
    const total = this.executionHistory.reduce((sum, e) => sum + e.result.elapsed_ms, 0);
    return Math.round(total / this.executionHistory.length);
  }

  getFastestRun(): number {
    if (this.executionHistory.length === 0) return 0;
    return Math.min(...this.executionHistory.map(e => e.result.elapsed_ms));
  }

  getSlowestRun(): number {
    if (this.executionHistory.length === 0) return 0;
    return Math.max(...this.executionHistory.map(e => e.result.elapsed_ms));
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

  getTestResults(execution: any): any[] {
    if (!execution.result || !Array.isArray(execution.result.results)) {
      return [];
    }
    return execution.result.results.slice(0, 10);
  }

  getStatusClass(test: any): string {
    if (!test || !test.status) {
      return '';
    }
    return String(test.status).toLowerCase();
  }
}

interface ExecutionRecord {
  timestamp: Date;
  mode: string;
  testCount: number;
  result: any;
  selected: boolean;
  expanded: boolean;
}



