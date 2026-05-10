import { Component, OnInit, OnDestroy } from '@angular/core';
import { CommonModule } from '@angular/common';
import { MatTableModule, MatTableDataSource } from '@angular/material/table';
import { MatToolbarModule } from '@angular/material/toolbar';
import { MatIconModule } from '@angular/material/icon';
import {MatButton, MatButtonModule} from '@angular/material/button';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatInputModule } from '@angular/material/input';
import { MatChipsModule } from '@angular/material/chips';
import { MatProgressSpinnerModule } from '@angular/material/progress-spinner';
import { MatDialogModule, MatDialog, MatDialogRef, MAT_DIALOG_DATA } from '@angular/material/dialog';
import { MatTooltipModule } from '@angular/material/tooltip';
import { MatCardModule } from '@angular/material/card';
import { MatSlideToggleModule } from '@angular/material/slide-toggle';
import { MatDividerModule } from '@angular/material/divider';
import { Inject } from '@angular/core';
import { Subscription, interval } from 'rxjs';
import { switchMap } from 'rxjs/operators';
import { ConfigService } from '../../core/services/config.service';
import { SnackBarService } from '../../core/services/snack-bar.service';

@Component({
  selector: 'app-jms-config',
  standalone: true,
  templateUrl: './jms-config.component.html',
  styleUrls: ['./jms-config.component.scss'],
  imports: [
    CommonModule,
    MatTableModule,
    MatToolbarModule,
    MatIconModule,
    MatButtonModule,
    MatFormFieldModule,
    MatInputModule,
    MatChipsModule,
    MatProgressSpinnerModule,
    MatDialogModule,
    MatTooltipModule,
    MatCardModule,
    MatSlideToggleModule,
    MatDividerModule,
  ]
})
export class JmsConfigComponent implements OnInit, OnDestroy {
  displayedColumns: string[] = ['name', 'provider', 'connected', 'pool_status', 'actions'];
  dataSource = new MatTableDataSource<any>();
  filterText = '';
  loading = true;

  // Listener state
  listenerStatus: any = null;
  listenerLoading = false;
  queueStatuses: any[] = [];
  togglingQueue: Set<string> = new Set();
  togglingListener = false;

  private refreshSub?: Subscription;

  constructor(
    private configService: ConfigService,
    private dialog: MatDialog,
    private snackBar: SnackBarService
  ) {}

  ngOnInit(): void {
    this.loadQueueManagers();
    this.loadListenerStatus();

    // Auto-refresh listener status every 5 s
    this.refreshSub = interval(5000).pipe(
      switchMap(() => this.configService.getListenerStatus())
    ).subscribe({
      next: (status) => { this.listenerStatus = status; },
      error: () => {}
    });
  }

  ngOnDestroy(): void {
    this.refreshSub?.unsubscribe();
  }

  loadQueueManagers(): void {
    this.loading = true;
    this.configService.getQueueManagers().subscribe(
      (response: any) => {
        const qms = response.queue_managers || [];
        this.dataSource.data = qms;
        this.loading = false;
      },
      (error) => {
        this.snackBar.error('Failed to load queue managers: ' + error.message);
        this.loading = false;
      }
    );
  }

  loadListenerStatus(): void {
    this.listenerLoading = true;
    this.configService.getListenerStatus().subscribe({
      next: (status) => {
        this.listenerStatus = status;
        this.listenerLoading = false;
        this.loadQueueStatuses();
      },
      error: () => { this.listenerLoading = false; }
    });
  }

  loadQueueStatuses(): void {
    this.configService.getQueueStatuses().subscribe({
      next: (resp: any) => {
        this.queueStatuses = resp.queues || [];
      },
      error: () => {}
    });
  }

  applyFilter(event: any): void {
    const filterValue = event.target.value?.toLowerCase() || '';
    this.dataSource.filter = filterValue;
  }

  getStatusIcon(connected: boolean): string {
    return connected ? 'check_circle' : 'error';
  }

  getStatusClass(connected: boolean): string {
    return connected ? 'status-connected' : 'status-disconnected';
  }

  viewDetails(qmName: string): void {
    this.configService.getQueueManager(qmName).subscribe(
      (config: any) => {
        this.dialog.open(JmsDetailDialog, {
          width: '700px',
          data: config
        });
      },
      (error) => {
        this.snackBar.error('Failed to load queue manager details');
      }
    );
  }

  testConnection(qmName: string): void {
    this.configService.getQueueManager(qmName).subscribe(
      (config: any) => {
        if (config.connected) {
          this.snackBar.success(`Connected to ${qmName}`);
        } else {
          this.snackBar.warning(`Not connected to ${qmName}`);
        }
      }
    );
  }

  refresh(): void {
    this.loadQueueManagers();
    this.loadListenerStatus();
  }

  // ---------------------------------------------------------------------------
  // Listener engine controls
  // ---------------------------------------------------------------------------

  toggleListener(): void {
    if (!this.listenerStatus || this.togglingListener) return;
    this.togglingListener = true;
    const action$ = this.listenerStatus.running
      ? this.configService.stopListener()
      : this.configService.startListener();

    action$.subscribe({
      next: (resp: any) => {
        this.snackBar.success(resp.message || 'Done');
        this.loadListenerStatus();
        this.togglingListener = false;
      },
      error: (err: any) => {
        this.snackBar.error('Action failed: ' + (err.error?.detail || err.message));
        this.togglingListener = false;
      }
    });
  }

  // ---------------------------------------------------------------------------
  // Per-queue pause / resume
  // ---------------------------------------------------------------------------

  isQueuePaused(queueName: string): boolean {
    const q = this.queueStatuses.find(s => s.queue === queueName);
    return q ? q.paused : false;
  }

  toggleQueue(queueName: string): void {
    if (this.togglingQueue.has(queueName)) return;
    this.togglingQueue.add(queueName);
    const paused = this.isQueuePaused(queueName);
    const action$ = paused
      ? this.configService.resumeQueue(queueName)
      : this.configService.pauseQueue(queueName);

    action$.subscribe({
      next: (resp: any) => {
        this.snackBar.success(resp.message || 'Done');
        this.loadQueueStatuses();
        this.togglingQueue.delete(queueName);
      },
      error: (err: any) => {
        this.snackBar.error('Action failed: ' + (err.error?.detail || err.message));
        this.togglingQueue.delete(queueName);
      }
    });
  }
}

@Component({
  selector: 'app-jms-detail-dialog',
  standalone: true,
  template: `
    <h2 mat-dialog-title>Queue Manager: {{ data.name }}</h2>
    <mat-dialog-content>
      <div class="detail-section">
        <h3>Connection Information</h3>
        <div class="config-item">
          <span class="label">Provider:</span>
          <span class="value provider-badge">{{ data.provider }}</span>
        </div>
        <div class="config-item">
          <span class="label">Connected:</span>
          <span class="value" [ngClass]="data.connected ? 'connected' : 'disconnected'">
            {{ data.connected ? 'Yes' : 'No' }}
          </span>
        </div>
      </div>

      <div class="detail-section">
        <h3>Configuration</h3>
        <div class="config-list">
          <div class="config-item" *ngFor="let field of configFields">
            <span class="label">{{ field.label }}:</span>
            <span class="value">{{ field.value || '(not set)' }}</span>
          </div>
        </div>
      </div>

      <div class="detail-section" *ngIf="data.pool_stats">
        <h3>Connection Pool Statistics</h3>
        <div class="pool-stats">
          <div class="stat-item">
            <span class="stat-label">Available:</span>
            <span class="stat-value">{{ data.pool_stats.available }}</span>
          </div>
          <div class="stat-item">
            <span class="stat-label">In Use:</span>
            <span class="stat-value">{{ data.pool_stats.in_use }}</span>
          </div>
          <div class="stat-item">
            <span class="stat-label">Total:</span>
            <span class="stat-value">{{ data.pool_stats.total }}</span>
          </div>
          <div class="stat-item">
            <span class="stat-label">Max Size:</span>
            <span class="stat-value">{{ data.pool_stats.max_size }}</span>
          </div>
        </div>
      </div>

      <div class="detail-section" *ngIf="!data.pool_stats">
        <p class="text-muted">No pool statistics available</p>
      </div>
    </mat-dialog-content>
    <mat-dialog-actions align="end">
      <button mat-button mat-dialog-close>Close</button>
    </mat-dialog-actions>
  `,
  styles: [`
    .detail-section {
      margin-bottom: 24px;
    }
    .detail-section h3 {
      margin: 16px 0 8px;
      font-size: 14px;
      font-weight: 500;
    }
    .config-item {
      display: flex;
      justify-content: space-between;
      padding: 8px 0;
      border-bottom: 1px solid #e0e0e0;
    }
    .config-item .label {
      font-weight: 500;
      min-width: 150px;
    }
    .config-item .value {
      flex: 1;
      word-break: break-word;
    }
    .provider-badge {
      display: inline-block;
      padding: 4px 12px;
      background: #e3f2fd;
      border-radius: 4px;
      font-size: 12px;
      font-weight: 500;
      color: #1976d2;
    }
    .value.connected {
      color: #4caf50;
      font-weight: 500;
    }
    .value.disconnected {
      color: #f44336;
      font-weight: 500;
    }
    .pool-stats {
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 16px;
    }
    .stat-item {
      background: #f5f5f5;
      padding: 12px;
      border-radius: 4px;
      text-align: center;
    }
    .stat-label {
      display: block;
      font-size: 12px;
      color: #666;
      margin-bottom: 4px;
    }
    .stat-value {
      display: block;
      font-size: 20px;
      font-weight: 500;
      color: #333;
    }
    .text-muted {
      color: #999;
      font-style: italic;
    }
  `],
  imports: [
    CommonModule,
    MatDialogModule,
    MatButton
  ]
})
export class JmsDetailDialog {
  configFields: any[] = [];

  constructor(
    public dialogRef: MatDialogRef<JmsDetailDialog>,
    @Inject(MAT_DIALOG_DATA) public data: any
  ) {
    this.processConfigFields();
  }

  private processConfigFields(): void {
    const config = this.data.config || {};
    this.configFields = Object.entries(config).map(([key, value]) => ({
      label: this.humanizeLabel(key),
      value: value
    }));
  }

  private humanizeLabel(label: string): string {
    return label
      .replace(/_/g, ' ')
      .split(' ')
      .map(word => word.charAt(0).toUpperCase() + word.slice(1))
      .join(' ');
  }
}

