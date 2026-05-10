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
import { ApiService } from '../../core/services/api.service';

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
    MatProgressBarModule
  ],
  template: `
    <div class="container">
      <mat-card>
        <mat-card-header>
          <mat-card-title>Test Execution Logs</mat-card-title>
          <mat-card-subtitle>View and search test execution logs with detailed results</mat-card-subtitle>
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
          </div>

          <mat-progress-bar *ngIf="isLoading" mode="indeterminate"></mat-progress-bar>

          <!-- Logs List -->
          <div *ngIf="filteredLogs.length === 0" class="empty-state">
            <mat-icon>description</mat-icon>
            <p>{{ isLoading ? 'Loading logs...' : 'No logs found' }}</p>
          </div>

          <div *ngFor="let log of filteredLogs; let i = index" class="log-item">
            <mat-expansion-panel [expanded]="expandedLogIndex === i"
                                 (opened)="onLogOpened(log)"
                                 (click)="expandedLogIndex = i">
              <mat-expansion-panel-header>
                <mat-panel-title class="log-title">
                  <span class="log-id">{{ log.testId || 'test-' + i }}</span>
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

              <!-- Log Content -->
              <div class="log-content" *ngIf="log.content">
                <!-- Summary Stats -->
                <div *ngIf="log.summary" class="log-summary">
                  <div class="summary-stat">
                    <span class="label">Test ID</span>
                    <span class="value">{{ log.testId || log.summary.test_id || 'N/A' }}</span>
                  </div>
                  <div class="summary-stat">
                    <span class="label">Status</span>
                    <span [ngClass]="'status-' + (log.summary.status || 'unknown')">
                      {{ log.summary.status || 'UNKNOWN' }}
                    </span>
                  </div>
                  <div class="summary-stat">
                    <span class="label">Duration</span>
                    <span class="value">{{ log.summary.elapsed_ms || 0 }}ms</span>
                  </div>
                  <div class="summary-stat" *ngIf="log.summary.when_result">
                    <span class="label">Injections</span>
                    <span class="value">{{ log.summary.when_result.injected ? '✓' : '✗' }}</span>
                  </div>
                </div>

                <!-- Full Log Output -->
                <div class="log-raw">
                  <h4>Full Log Output</h4>
                  <pre class="log-text">{{ log.content }}</pre>
                </div>

                <!-- Actions -->
                <div class="log-actions">
                  <button mat-stroked-button color="primary" (click)="copyLog(log)">
                    <mat-icon>content_copy</mat-icon>
                    Copy
                  </button>
                  <button mat-stroked-button (click)="downloadLog(log)">
                    <mat-icon>download</mat-icon>
                    Download
                  </button>
                </div>
              </div>

              <!-- Loading State -->
              <div *ngIf="!log.content" class="log-loading">
                <mat-progress-bar mode="indeterminate"></mat-progress-bar>
                <p>Loading log content...</p>
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

    .refresh-btn {
      margin-bottom: 24px;
    }

    .search-field {
      flex: 1;
      min-width: 250px;
      max-width: 400px;
    }

    .empty-state {
      text-align: center;
      padding: 60px 24px;
      color: #757575;
    }

    .empty-state mat-icon {
      font-size: 64px;
      width: 64px;
      height: 64px;
      color: #bdbdbd;
      margin-bottom: 16px;
    }

    .log-item {
      margin-bottom: 12px;
    }

    .log-title {
      display: flex;
      gap: 16px;
      align-items: center;
      flex: 1;
    }

    .log-id {
      font-weight: 500;
      color: #1976d2;
      min-width: 150px;
    }

    .log-timestamp {
      font-size: 12px;
      color: #999;
    }

    .log-preview {
      display: flex;
      gap: 12px;
      align-items: center;
    }

    .status-passed {
      background-color: #c8e6c9;
      color: #1b5e20;
      padding: 4px 8px;
      border-radius: 3px;
      font-size: 12px;
      font-weight: 500;
    }

    .status-failed {
      background-color: #ffcdd2;
      color: #b71c1c;
      padding: 4px 8px;
      border-radius: 3px;
      font-size: 12px;
      font-weight: 500;
    }

    .status-skipped {
      background-color: #ffe0b2;
      color: #e65100;
      padding: 4px 8px;
      border-radius: 3px;
      font-size: 12px;
      font-weight: 500;
    }

    .log-duration {
      font-size: 12px;
      color: #666;
      background-color: #f5f5f5;
      padding: 4px 8px;
      border-radius: 3px;
    }

    .log-content {
      padding: 16px 0;
    }

    .log-summary {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
      gap: 16px;
      padding: 16px;
      background-color: #f9f9f9;
      border-radius: 4px;
      margin-bottom: 16px;
    }

    .summary-stat {
      display: flex;
      flex-direction: column;
      gap: 4px;
    }

    .summary-stat .label {
      font-size: 12px;
      color: #999;
      font-weight: 500;
      text-transform: uppercase;
    }

    .summary-stat .value {
      font-size: 14px;
      font-weight: 500;
      color: #333;
      font-family: 'Courier New', monospace;
    }

    .log-raw {
      margin-bottom: 16px;
    }

    .log-raw h4 {
      margin: 0 0 8px 0;
      color: #333;
      font-size: 14px;
      font-weight: 500;
    }

    .log-text {
      background-color: #1e1e1e;
      color: #d4d4d4;
      padding: 12px;
      border-radius: 4px;
      overflow-x: auto;
      font-family: 'Courier New', monospace;
      font-size: 11px;
      line-height: 1.5;
      margin: 0;
      max-height: 400px;
      overflow-y: auto;
    }

    .log-actions {
      display: flex;
      gap: 8px;
      margin-top: 12px;
    }

    .log-loading {
      padding: 16px;
      text-align: center;
      color: #999;
    }

    .log-loading p {
      margin: 8px 0 0 0;
    }

    .log-stats {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(120px, 1fr));
      gap: 16px;
      margin-top: 24px;
      padding-top: 24px;
      border-top: 1px solid #eee;
    }

    .stat {
      text-align: center;
      padding: 12px;
      background-color: #f5f5f5;
      border-radius: 4px;
    }

    .stat-label {
      display: block;
      font-size: 12px;
      color: #999;
      font-weight: 500;
      margin-bottom: 4px;
      text-transform: uppercase;
    }

    .stat-value {
      display: block;
      font-size: 24px;
      font-weight: 500;
      color: #333;
    }

    .stat-value.passed {
      color: #2e7d32;
    }

    .stat-value.failed {
      color: #c62828;
    }

    .stat-value.skipped {
      color: #ef6c00;
    }
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
    private snackBar: MatSnackBar
  ) {}

  ngOnInit() {
    this.loadLogs();
  }

   loadLogs() {
     this.isLoading = true;
     this.api.getTestLogs().subscribe({
       next: (response) => {
         // Handle API response - logs are in response.logs array
         const logData = response?.logs || (Array.isArray(response) ? response : []);

         this.allLogs = logData.map((file: any, index: number) => ({
           testId: file.relative_path?.split('/').pop()?.replace('.test.log', '') || `log-${index}`,
           fullPath: file.path,
           relativePath: file.relative_path,
           timestamp: new Date(file.modified ? file.modified * 1000 : Date.now()),
           status: file.status || 'UNKNOWN',
           duration: file.elapsed_ms || 0,
           size: file.size_bytes,
           content: null,
           preview: file.content_preview,
           summary: null
         }));

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

   onLogOpened(log: LogEntry) {
     // Load log content only when expanded
     if (!log.content) {
       this.api.getTestLog(log.testId).subscribe({
         next: (response: any) => {
           // Handle both plain text and JSON responses
           const content = typeof response === 'string' ? response : (response?.content || JSON.stringify(response, null, 2));
           log.content = content;

           // Try to parse JSON summary from log - more robust parsing
           try {
             const lines = content.split('\n');

             // Try to find a line with JSON containing status
             let jsonLine: string | undefined;
             for (const line of lines) {
               try {
                 // Try to parse each line as JSON
                 if (line.trim().startsWith('{') && line.includes('status')) {
                   const parsed = JSON.parse(line);
                   if (parsed.status) {
                     jsonLine = line;
                     break;
                   }
                 }
               } catch (e) {
                 // Not JSON, continue
               }
             }

             // If we found a JSON line with status, use it
             if (jsonLine) {
               log.summary = JSON.parse(jsonLine);
               log.status = log.summary.status || 'UNKNOWN';
               log.duration = log.summary.elapsed_ms || 0;
             } else {
               // Try to extract status from log content using regex patterns
               const statusMatch = content.match(/status['":\s]+([A-Z_]+)/i);
               if (statusMatch && statusMatch[1]) {
                 log.status = statusMatch[1];
               }

               // Try to extract elapsed time
               const durationMatch = content.match(/elapsed[_\s]*ms['":\s]+(\d+)/i);
               if (durationMatch && durationMatch[1]) {
                 log.duration = parseInt(durationMatch[1], 10);
               }
             }
           } catch (e) {
             // Log is plain text without JSON status - keep defaults
             console.debug('Could not parse JSON status from log:', e);
           }
         },
         error: (err) => {
           log.content = 'Error loading log: ' + (err.message || 'Unknown error');
         }
       });
     }
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

  copyLog(log: LogEntry) {
    if (log.content) {
      navigator.clipboard.writeText(log.content).then(() => {
        this.snackBar.open('Log copied to clipboard!', 'Close', { duration: 2000 });
      });
    }
  }

  downloadLog(log: LogEntry) {
    if (log.content) {
      const element = document.createElement('a');
      element.setAttribute('href', 'data:text/plain;charset=utf-8,' + encodeURIComponent(log.content));
      element.setAttribute('download', `${log.testId}.log`);
      element.style.display = 'none';
      document.body.appendChild(element);
      element.click();
      document.body.removeChild(element);
      this.snackBar.open('Log downloaded!', 'Close', { duration: 2000 });
    }
  }
}

interface LogEntry {
  testId: string;
  fullPath?: string;
  relativePath?: string;
  timestamp: Date;
  status: string;
  duration: number;
  size?: number;
  content: string | null;
  preview?: string;
  summary: any;
}

