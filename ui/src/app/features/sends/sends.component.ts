import { Component, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule, ReactiveFormsModule, FormBuilder } from '@angular/forms';
import { MatCardModule } from '@angular/material/card';
import { MatTableModule } from '@angular/material/table';
import { MatCheckboxModule } from '@angular/material/checkbox';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatProgressBarModule } from '@angular/material/progress-bar';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatInputModule } from '@angular/material/input';
import { MatSelectModule } from '@angular/material/select';
import { MatChipsModule } from '@angular/material/chips';
import { MatExpansionModule } from '@angular/material/expansion';
import { MatSnackBar, MatSnackBarModule } from '@angular/material/snack-bar';
import { MatDialogModule, MatDialog } from '@angular/material/dialog';
import { ApiService } from '../../core/services/api.service';
import { AppConfigService } from '../../core/services/app-config.service';
import { Send, BulkSendExecutionRequest, BulkSendExecutionResult } from '../../core/models';
import { SelectionModel } from '@angular/cdk/collections';

@Component({
  selector: 'app-sends',
  standalone: true,
  imports: [
    CommonModule,
    FormsModule,
    ReactiveFormsModule,
    MatCardModule,
    MatTableModule,
    MatCheckboxModule,
    MatButtonModule,
    MatIconModule,
    MatProgressBarModule,
    MatFormFieldModule,
    MatInputModule,
    MatSelectModule,
    MatChipsModule,
    MatExpansionModule,
    MatSnackBarModule,
    MatDialogModule
  ],
  template: `
    <div class="container">
      <mat-card>
        <mat-card-header>
          <mat-card-title>Send Messages Manager</mat-card-title>
          <mat-card-subtitle>Execute message sends with multi-select, parallel/sequential modes, and repeat functionality</mat-card-subtitle>
        </mat-card-header>
        <mat-card-content>
          <!-- Controls -->
          <div class="controls-section">
            <!-- Search and Filter -->
            <div class="search-section">
              <mat-form-field appearance="outline" class="search-field">
                <mat-label>Search Sends</mat-label>
                <input matInput placeholder="Search by send ID or tags..." [(ngModel)]="searchText"
                       (ngModelChange)="filterSends()">
                <mat-icon matSuffix>search</mat-icon>
              </mat-form-field>
            </div>

            <div class="control-group">
              <mat-form-field appearance="outline" class="full-width">
                <mat-label>Execution Mode</mat-label>
                <mat-select [formControl]="modeControl">
                  <mat-option value="sequential">Sequential</mat-option>
                  <mat-option value="parallel">Parallel</mat-option>
                </mat-select>
              </mat-form-field>

              <mat-form-field appearance="outline" class="full-width">
                <mat-label>Parallel Workers</mat-label>
                <input matInput type="number" [formControl]="workersControl" min="1" max="16"
                       [disabled]="modeControl.value === 'sequential'">
              </mat-form-field>

              <mat-form-field appearance="outline" class="full-width">
                <mat-label>Repeat Count</mat-label>
                <input matInput type="number" [formControl]="repeatControl" min="1" max="100">
                <mat-hint>Run each selected send this many times</mat-hint>
              </mat-form-field>

              <mat-form-field appearance="outline" class="full-width">
                <mat-label>Repeat Mode</mat-label>
                <mat-select [formControl]="repeatModeControl">
                  <mat-option value="interleaved-repeats">Interleaved (A,B,A,B,...)</mat-option>
                  <mat-option value="sequential-repeats">Sequential (A,A,...,B,B,...)</mat-option>
                </mat-select>
                <mat-hint>How to order repeated send executions</mat-hint>
              </mat-form-field>
            </div>

            <div class="button-group">
              <button mat-raised-button color="primary" (click)="selectAll()" [disabled]="!sends.length">
                <mat-icon>done_all</mat-icon>
                Select All
              </button>
              <button mat-raised-button (click)="clearSelection()" [disabled]="!selection.selected.length">
                <mat-icon>clear</mat-icon>
                Clear
              </button>
              <button mat-raised-button color="accent" (click)="runSelected()"
                      [disabled]="!selection.selected.length || isRunning">
                <mat-icon>send</mat-icon>
                Send Selected ({{ selection.selected.length }})
              </button>
              <button mat-raised-button color="warn" *ngIf="isRunning" (click)="stopExecution()">
                <mat-icon>stop</mat-icon>
                Stop Execution
              </button>
            </div>
          </div>

          <!-- Progress bar -->
          <mat-progress-bar *ngIf="isRunning" mode="indeterminate"></mat-progress-bar>

          <!-- Sends table -->
          <div class="table-container">
            <table mat-table [dataSource]="filteredSends" class="sends-table">
              <!-- Checkbox column -->
              <ng-container matColumnDef="select">
                <th mat-header-cell *matHeaderCellDef>
                  <mat-checkbox
                    [checked]="selection.hasValue() && isAllSelected()"
                    [indeterminate]="selection.hasValue() && !isAllSelected()"
                    (change)="$event ? masterToggle() : null">
                  </mat-checkbox>
                </th>
                <td mat-cell *matCellDef="let element">
                  <mat-checkbox
                    [checked]="selection.isSelected(element)"
                    (change)="$event ? selection.toggle(element) : null">
                  </mat-checkbox>
                </td>
              </ng-container>

              <!-- Send ID column -->
              <ng-container matColumnDef="send_id">
                <th mat-header-cell *matHeaderCellDef>Send ID</th>
                <td mat-cell *matCellDef="let element">{{ element.send_id }}</td>
              </ng-container>

              <!-- Tags column -->
              <ng-container matColumnDef="tags">
                <th mat-header-cell *matHeaderCellDef>Tags</th>
                <td mat-cell *matCellDef="let element">
                  <mat-chip-set>
                    <mat-chip *ngFor="let tag of element.tags" disabled>{{ tag }}</mat-chip>
                  </mat-chip-set>
                </td>
              </ng-container>

              <!-- Priority column -->
              <ng-container matColumnDef="priority">
                <th mat-header-cell *matHeaderCellDef>Priority</th>
                <td mat-cell *matCellDef="let element">{{ element.priority }}</td>
              </ng-container>

              <!-- Injections column -->
              <ng-container matColumnDef="injections">
                <th mat-header-cell *matHeaderCellDef>Injections</th>
                <td mat-cell *matCellDef="let element">{{ element.injections }}</td>
              </ng-container>

              <!-- Scripts column -->
              <ng-container matColumnDef="scripts">
                <th mat-header-cell *matHeaderCellDef>Scripts</th>
                <td mat-cell *matCellDef="let element">{{ element.scripts }}</td>
              </ng-container>

              <!-- Status column -->
              <ng-container matColumnDef="status">
                <th mat-header-cell *matHeaderCellDef>Status</th>
                <td mat-cell *matCellDef="let element">
                  <span *ngIf="element.skip" class="status-badge status-skipped">SKIPPED</span>
                  <span *ngIf="!element.skip" class="status-badge status-active">ACTIVE</span>
                </td>
              </ng-container>

              <tr mat-header-row *matHeaderRowDef="displayedColumns"></tr>
              <tr mat-row *matRowDef="let row; columns: displayedColumns;"></tr>
            </table>
          </div>
        </mat-card-content>
      </mat-card>

       <!-- Result panel -->
      <mat-expansion-panel *ngIf="lastResult" [expanded]="true">
        <mat-expansion-panel-header>
          <mat-panel-title>
            <mat-icon [ngClass]="{
              'result-succeeded': lastResult.failed === 0,
              'result-failed': lastResult.failed > 0
            }">{{ lastResult.failed === 0 ? 'check_circle' : 'error' }}</mat-icon>
            Last Execution Results
          </mat-panel-title>
          <mat-panel-description>
            {{ lastResult.completed }} completed, {{ lastResult.failed }} failed, {{ lastResult.skipped }} skipped
          </mat-panel-description>
        </mat-expansion-panel-header>

        <!-- Execution Settings -->
        <div class="execution-settings" *ngIf="lastResult">
          <h3>Execution Settings</h3>
          <div class="settings-grid">
            <div class="setting-item">
              <span class="setting-label">Mode:</span>
              <span class="setting-value">{{ lastResult.mode }}</span>
            </div>
            <div class="setting-item">
              <span class="setting-label">Workers:</span>
              <span class="setting-value">{{ lastResult.parallel_workers || 1 }}</span>
            </div>
            <div class="setting-item">
              <span class="setting-label">Repeat Count:</span>
              <span class="setting-value">{{ lastResult.repeat }}</span>
            </div>
            <div class="setting-item">
              <span class="setting-label">Repeat Mode:</span>
              <span class="setting-value">{{ lastResult.repeat_mode || 'interleaved-repeats' }}</span>
            </div>
          </div>
        </div>

        <div class="result-stats">
          <div class="stat-item">
            <div class="stat-label">Total</div>
            <div class="stat-value">{{ lastResult.total }}</div>
          </div>
          <div class="stat-item">
            <div class="stat-label">Completed</div>
            <div class="stat-value stat-passed">{{ lastResult.completed }}</div>
          </div>
          <div class="stat-item">
            <div class="stat-label">Failed</div>
            <div class="stat-value stat-failed">{{ lastResult.failed }}</div>
          </div>
          <div class="stat-item">
            <div class="stat-label">Skipped</div>
            <div class="stat-value stat-skipped">{{ lastResult.skipped }}</div>
          </div>
          <div class="stat-item">
            <div class="stat-label">Duration</div>
            <div class="stat-value">{{ lastResult.elapsed_ms }}ms</div>
          </div>
        </div>

        <div class="result-details">
          <h3>Execution Details</h3>
          <table mat-table [dataSource]="lastResult.results" class="results-table">
            <ng-container matColumnDef="send_id">
              <th mat-header-cell *matHeaderCellDef>Send ID</th>
              <td mat-cell *matCellDef="let element">{{ element.send_id }}</td>
            </ng-container>
            <ng-container matColumnDef="status">
              <th mat-header-cell *matHeaderCellDef>Status</th>
              <td mat-cell *matCellDef="let element">
                <span [ngClass]="'status-badge status-' + element.status.toLowerCase()">
                  {{ element.status }}
                </span>
              </td>
            </ng-container>
            <ng-container matColumnDef="elapsed_ms">
              <th mat-header-cell *matHeaderCellDef>Duration</th>
              <td mat-cell *matCellDef="let element">{{ element.elapsed_ms }}ms</td>
            </ng-container>
            <tr mat-header-row *matHeaderRowDef="resultColumns"></tr>
            <tr mat-row *matRowDef="let row; columns: resultColumns;"></tr>
          </table>
        </div>
      </mat-expansion-panel>
    </div>
  `,
  styles: [`
    .container {
      padding: 24px;
      max-width: 1200px;
      margin: 0 auto;
    }

    .controls-section {
      margin-bottom: 24px;
    }

    .control-group {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
      gap: 16px;
      margin-bottom: 16px;
    }

    .full-width {
      width: 100%;
    }

    .button-group {
      display: flex;
      gap: 8px;
      flex-wrap: wrap;
    }

    .table-container {
      overflow-x: auto;
    }

    .sends-table {
      width: 100%;
    }

    .status-badge {
      padding: 4px 8px;
      border-radius: 4px;
      font-size: 12px;
      font-weight: 500;
    }

    .status-active {
      background-color: #e8f5e9;
      color: #2e7d32;
    }

    .status-skipped {
      background-color: #fff3e0;
      color: #ef6c00;
    }

    .status-completed {
      background-color: #e8f5e9;
      color: #2e7d32;
    }

    .status-failed {
      background-color: #ffebee;
      color: #c62828;
    }

    .result-stats {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(100px, 1fr));
      gap: 16px;
      padding: 16px;
      background-color: #f5f5f5;
      border-radius: 4px;
      margin-bottom: 16px;
    }

    .stat-item {
      text-align: center;
    }

    .stat-label {
      font-size: 12px;
      color: #757575;
      margin-bottom: 4px;
    }

    .stat-value {
      font-size: 24px;
      font-weight: 500;
      color: #212121;
    }

    .stat-passed {
      color: #2e7d32;
    }

    .stat-failed {
      color: #c62828;
    }

    .stat-skipped {
      color: #f57c00;
    }

    .result-details {
      margin-top: 16px;
    }

    .results-table {
      width: 100%;
      margin-top: 12px;
    }

    .result-succeeded {
      color: #2e7d32;
    }

    .result-failed {
      color: #c62828;
    }

    mat-chip-set {
       display: flex;
       flex-wrap: wrap;
       gap: 4px;
     }

     .search-section {
       margin-bottom: 16px;
     }

      .search-field {
        width: 300px;
        max-width: 100%;
      }

      .execution-settings {
        padding: 16px;
        background-color: #fafafa;
        border-left: 4px solid #ff9800;
        margin-bottom: 16px;
      }

      .execution-settings h3 {
        margin: 0 0 12px 0;
        font-size: 14px;
        font-weight: 500;
      }

      .settings-grid {
        display: grid;
        grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
        gap: 16px;
      }

      .setting-item {
        display: flex;
        flex-direction: column;
      }

      .setting-label {
        font-size: 12px;
        color: #666;
        margin-bottom: 4px;
        font-weight: 500;
      }

      .setting-value {
        font-size: 14px;
        color: #333;
        font-weight: 500;
      }
    `]
})
export class SendsComponent implements OnInit {
  sends: Send[] = [];
  filteredSends: Send[] = [];
  selection = new SelectionModel<Send>(true, []);
  isRunning = false;
  lastResult: BulkSendExecutionResult | null = null;
  searchText = '';
  private currentExecutionRequest: any = null;

  modeControl = new FormBuilder().control<'sequential' | 'parallel'>('sequential', { nonNullable: true });
  workersControl = new FormBuilder().control<number>(4, { nonNullable: true });
  repeatControl = new FormBuilder().control<number>(1, { nonNullable: true });
  repeatModeControl = new FormBuilder().control<'interleaved-repeats' | 'sequential-repeats'>('interleaved-repeats', { nonNullable: true });

  displayedColumns: string[] = ['select', 'send_id', 'tags', 'priority', 'injections', 'scripts', 'status'];
  resultColumns: string[] = ['send_id', 'status', 'elapsed_ms'];

  constructor(
    private api: ApiService,
    private appConfigService: AppConfigService,
    private snackBar: MatSnackBar,
    private fb: FormBuilder,
    private dialog: MatDialog
  ) {}

  ngOnInit() {
    this.loadSends();
  }

  loadSends() {
    this.api.getSends().subscribe({
      next: (response) => {
        this.sends = response.sends || [];
        this.filteredSends = [...this.sends];
        this.selection = new SelectionModel<Send>(true, []);
      },
      error: (err) => {
        // Gracefully handle API errors - still show the UI
        console.warn('Failed to load sends - backend may be unavailable:', err);
        this.snackBar.open('Failed to load sends - backend connection may be unavailable', 'Close', { duration: 5000 });
        // Initialize with empty array so UI still renders
        this.sends = [];
        this.filteredSends = [];
        this.selection = new SelectionModel<Send>(true, []);
      }
    });
  }

  filterSends() {
    if (!this.searchText.trim()) {
      this.filteredSends = [...this.sends];
      return;
    }

    const searchLower = this.searchText.toLowerCase();
    this.filteredSends = this.sends.filter(send =>
      send.send_id.toLowerCase().includes(searchLower) ||
      send.tags.some(tag => tag.toLowerCase().includes(searchLower))
    );
  }

  masterToggle() {
    if (this.isAllSelected()) {
      this.selection.clear();
    } else {
      this.sends.forEach(row => this.selection.select(row));
    }
  }

  isAllSelected(): boolean {
    const numSelected = this.selection.selected.length;
    const numRows = this.sends.length;
    return numSelected === numRows && numRows > 0;
  }

  selectAll() {
    this.sends.forEach(row => this.selection.select(row));
  }

  clearSelection() {
    this.selection.clear();
  }

  runSelected() {
    if (!this.selection.selected.length) {
      this.snackBar.open('Please select at least one send', 'Close', { duration: 3000 });
      return;
    }

    const totalExecutions = this.selection.selected.length * this.repeatControl.value;
    const threshold = this.appConfigService.getTestRecapThreshold();

    // Only show recap popup if total executions exceed threshold
    if (totalExecutions > threshold) {
      const summaryMessage = `You are about to run ${totalExecutions} send execution(s):
- Selected Sends: ${this.selection.selected.length}
- Repeat Count: ${this.repeatControl.value}
- Mode: ${this.modeControl.value}
- Workers: ${this.modeControl.value === 'parallel' ? this.workersControl.value : 1}
- Repeat Mode: ${this.repeatModeControl.value}

This may take some time depending on your send configuration.`;

      const dialogRef = this.dialog.open(SendExecutionSummaryDialog, {
        width: '500px',
        data: { message: summaryMessage }
      });

      dialogRef.afterClosed().subscribe(result => {
        if (result) {
          this.executeSends();
        }
      });
    } else {
      // If below threshold, execute without confirmation
      this.executeSends();
    }
  }

  private executeSends() {
    const request: BulkSendExecutionRequest = {
      send_ids: this.selection.selected.map(s => s.send_id),
      mode: this.modeControl.value,
      repeat: this.repeatControl.value,
      parallel_workers: this.workersControl.value,
      repeat_mode: this.repeatModeControl.value
    };

    this.currentExecutionRequest = request;
    this.isRunning = true;
    this.api.runSendsBulk(request).subscribe({
      next: (result) => {
        this.lastResult = result;
        this.isRunning = false;
        this.currentExecutionRequest = null;

        // Save execution history to localStorage
        this.saveExecutionHistory(request, result);

        const message = `Sends completed: ${result.completed} completed, ${result.failed} failed`;
        this.snackBar.open(message, 'Close', { duration: 5000 });
      },
      error: (err) => {
        this.isRunning = false;
        this.currentExecutionRequest = null;
        this.snackBar.open('Send execution failed', 'Close', { duration: 5000 });
        console.error('Error running sends:', err);
      }
    });
  }

  stopExecution() {
    this.isRunning = false;
    this.currentExecutionRequest = null;
    this.snackBar.open('Attempting to stop execution...', 'Close', { duration: 3000 });
    // Note: Full cancellation support requires backend job tracking
    // For now, this stops the UI from waiting for results
  }

  private saveExecutionHistory(request: BulkSendExecutionRequest, result: BulkSendExecutionResult) {
    const history = JSON.parse(localStorage.getItem('send_execution_history') || '[]');
    const record = {
      timestamp: new Date().toISOString(),
      mode: request.mode,
      sendCount: request.send_ids.length,
      result: result
    };
    history.unshift(record);
    // Keep only last 100 executions
    if (history.length > 100) {
      history.pop();
    }
    localStorage.setItem('send_execution_history', JSON.stringify(history));
  }
}

// Execution Summary Dialog Component
import { MatDialogRef, MAT_DIALOG_DATA } from '@angular/material/dialog';
import { Inject } from '@angular/core';

@Component({
  selector: 'app-send-execution-summary-dialog',
  template: `
    <h2 mat-dialog-title>Confirm Execution</h2>
    <mat-dialog-content>
      <p style="white-space: pre-line; line-height: 1.6;">{{ data.message }}</p>
    </mat-dialog-content>
    <mat-dialog-actions align="end">
      <button mat-button (click)="onCancel()">Cancel</button>
      <button mat-raised-button color="accent" (click)="onConfirm()">Start Execution</button>
    </mat-dialog-actions>
  `,
  standalone: true,
  imports: [MatDialogModule, MatButtonModule, CommonModule]
})
export class SendExecutionSummaryDialog {
  constructor(
    public dialogRef: MatDialogRef<SendExecutionSummaryDialog>,
    @Inject(MAT_DIALOG_DATA) public data: { message: string }
  ) {}

  onConfirm() {
    this.dialogRef.close(true);
  }

  onCancel() {
    this.dialogRef.close(false);
  }
}
