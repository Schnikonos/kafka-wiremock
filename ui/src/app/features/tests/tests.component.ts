import { Component, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule, ReactiveFormsModule, FormBuilder, FormGroup, Validators } from '@angular/forms';
import { MatCardModule } from '@angular/material/card';
import { MatTableModule } from '@angular/material/table';
import { MatCheckboxModule } from '@angular/material/checkbox';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatProgressBarModule } from '@angular/material/progress-bar';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatInputModule } from '@angular/material/input';
import { MatSelectModule } from '@angular/material/select';
import { MatSlideToggleModule } from '@angular/material/slide-toggle';
import { MatChipsModule } from '@angular/material/chips';
import { MatExpansionModule } from '@angular/material/expansion';
import { MatSnackBar, MatSnackBarModule } from '@angular/material/snack-bar';
import { MatDialogModule, MatDialog } from '@angular/material/dialog';
import { ApiService } from '../../core/services/api.service';
import { AppConfigService } from '../../core/services/app-config.service';
import { Test, BulkTestExecutionRequest, BulkTestExecutionResult } from '../../core/models';
import { SelectionModel } from '@angular/cdk/collections';

@Component({
  selector: 'app-tests',
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
    MatSlideToggleModule,
    MatChipsModule,
    MatExpansionModule,
    MatSnackBarModule,
    MatDialogModule
  ],
  template: `
    <div class="container">
      <mat-card>
        <mat-card-header>
          <mat-card-title>Test Suite Manager</mat-card-title>
          <mat-card-subtitle>Run tests with multi-select, parallel/sequential modes, and repeat functionality</mat-card-subtitle>
        </mat-card-header>
        <mat-card-content>
          <!-- Controls -->
          <div class="controls-section">
            <!-- Search and Filter -->
            <div class="search-section">
              <mat-form-field appearance="outline" class="search-field">
                <mat-label>Search Tests</mat-label>
                <input matInput placeholder="Search by test ID or tags..." [(ngModel)]="searchText"
                       (ngModelChange)="filterTests()">
                <mat-icon matSuffix>search</mat-icon>
              </mat-form-field>
            </div>

            <!-- Advanced Filters -->
            <div class="filter-section">
              <mat-form-field appearance="outline" class="filter-field">
                <mat-label>Filter by Tag</mat-label>
                <mat-select [(ngModel)]="selectedTag" (ngModelChange)="filterTests()">
                  <mat-option value="">All Tags</mat-option>
                  <mat-option *ngFor="let tag of allTags" [value]="tag">{{ tag }}</mat-option>
                </mat-select>
              </mat-form-field>

              <mat-form-field appearance="outline" class="filter-field">
                <mat-label>Filter by Status</mat-label>
                <mat-select [(ngModel)]="selectedStatus" (ngModelChange)="filterTests()">
                  <mat-option value="">All Status</mat-option>
                  <mat-option value="active">Active</mat-option>
                  <mat-option value="skipped">Skipped</mat-option>
                </mat-select>
              </mat-form-field>

              <button mat-stroked-button (click)="resetFilters()" [disabled]="!searchText && !selectedTag && !selectedStatus">
                <mat-icon>restart_alt</mat-icon>
                Reset
              </button>
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
                <input matInput type="number" [formControl]="workersControl" min="1" max="32"
                       [disabled]="modeControl.value === 'sequential'">
              </mat-form-field>

              <mat-form-field appearance="outline" class="full-width">
                <mat-label>Repeat Count</mat-label>
                <input matInput type="number" [formControl]="repeatControl" min="1" max="1000">
                <mat-hint>Run each selected test this many times</mat-hint>
              </mat-form-field>

              <mat-form-field appearance="outline" class="full-width">
                <mat-label>Repeat Mode</mat-label>
                <mat-select [formControl]="repeatModeControl">
                  <mat-option value="interleaved-repeats">Interleaved (A,B,A,B,...)</mat-option>
                  <mat-option value="sequential-repeats">Sequential (A,A,...,B,B,...)</mat-option>
                </mat-select>
                <mat-hint>How to order repeated test executions</mat-hint>
              </mat-form-field>
            </div>

            <div class="button-group">
              <button mat-raised-button color="primary" (click)="selectAll()" [disabled]="!tests.length">
                <mat-icon>done_all</mat-icon>
                Select All
              </button>
              <button mat-raised-button (click)="clearSelection()" [disabled]="!selection.selected.length">
                <mat-icon>clear</mat-icon>
                Clear
              </button>
              <button mat-raised-button color="accent" (click)="runSelected()"
                      [disabled]="!selection.selected.length || isRunning">
                <mat-icon>play_arrow</mat-icon>
                Run Selected ({{ selection.selected.length }})
              </button>
              <button mat-raised-button color="warn" *ngIf="isRunning" (click)="stopExecution()">
                <mat-icon>stop</mat-icon>
                Stop Execution
              </button>
            </div>
          </div>

          <!-- Progress bar -->
          <mat-progress-bar *ngIf="isRunning" mode="indeterminate"></mat-progress-bar>

          <!-- Tests table -->
          <div class="table-container">
            <table mat-table [dataSource]="filteredTests" class="tests-table">
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

              <!-- Test ID column -->
              <ng-container matColumnDef="test_id">
                <th mat-header-cell *matHeaderCellDef>Test ID</th>
                <td mat-cell *matCellDef="let element">{{ element.test_id }}</td>
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
                <td mat-cell *matCellDef="let element">{{ element.when_injections }}</td>
              </ng-container>

              <!-- Expectations column -->
              <ng-container matColumnDef="expectations">
                <th mat-header-cell *matHeaderCellDef>Expectations</th>
                <td mat-cell *matCellDef="let element">{{ element.then_expectations }}</td>
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
              'result-passed': lastResult.passed > 0,
              'result-failed': lastResult.failed > 0
            }">{{ lastResult.failed === 0 ? 'check_circle' : 'error' }}</mat-icon>
            Last Execution Results
          </mat-panel-title>
          <mat-panel-description>
            {{ lastResult.passed }} passed, {{ lastResult.failed }} failed, {{ lastResult.skipped }} skipped
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
            <div class="stat-label">Passed</div>
            <div class="stat-value stat-passed">{{ lastResult.passed }}</div>
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
            <ng-container matColumnDef="test_id">
              <th mat-header-cell *matHeaderCellDef>Test ID</th>
              <td mat-cell *matCellDef="let element">{{ element.test_id }}</td>
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

    .tests-table {
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

    .status-passed {
      color: #2e7d32;
    }

    .status-failed {
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

    .result-passed {
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

     .filter-section {
       display: flex;
       gap: 12px;
       margin-bottom: 16px;
       align-items: flex-end;
       flex-wrap: wrap;
     }

      .filter-field {
        width: 150px;
        flex: 0 0 auto;
      }

      .execution-settings {
        padding: 16px;
        background-color: #fafafa;
        border-left: 4px solid #2196f3;
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
export class TestsComponent implements OnInit {
  tests: Test[] = [];
  filteredTests: Test[] = [];
  selection = new SelectionModel<Test>(true, []);
  isRunning = false;
  lastResult: BulkTestExecutionResult | null = null;
  searchText = '';
  selectedTag = '';
  selectedStatus = '';
  allTags: string[] = [];
  private currentExecutionRequest: any = null;

  modeControl = new FormBuilder().control<'sequential' | 'parallel'>('sequential', { nonNullable: true });
  workersControl = new FormBuilder().control<number>(4, { nonNullable: true });
  repeatControl = new FormBuilder().control<number>(1, { nonNullable: true });
  repeatModeControl = new FormBuilder().control<'interleaved-repeats' | 'sequential-repeats'>('interleaved-repeats', { nonNullable: true });

  displayedColumns: string[] = ['select', 'test_id', 'tags', 'priority', 'injections', 'expectations', 'status'];
  resultColumns: string[] = ['test_id', 'status', 'elapsed_ms'];

  constructor(
    private api: ApiService,
    private snackBar: MatSnackBar,
    private fb: FormBuilder,
    private dialog: MatDialog,
    private appConfigService: AppConfigService
  ) {}

  ngOnInit() {
    this.loadTests();
  }

  loadTests() {
    this.api.getTests().subscribe({
      next: (response) => {
        this.tests = response.tests || [];
        this.filteredTests = [...this.tests];
        this.selection = new SelectionModel<Test>(true, []);
        this.extractAllTags();
      },
      error: (err) => {
        // Gracefully handle API errors - still show the UI
        console.warn('Failed to load tests - backend may be unavailable:', err);
        this.snackBar.open('Failed to load tests - backend connection may be unavailable', 'Close', { duration: 5000 });
        // Initialize with empty array so UI still renders
        this.tests = [];
        this.filteredTests = [];
        this.selection = new SelectionModel<Test>(true, []);
      }
    });
  }

  extractAllTags() {
    const tagsSet = new Set<string>();
    this.tests.forEach(test => {
      test.tags.forEach(tag => tagsSet.add(tag));
    });
    this.allTags = Array.from(tagsSet).sort();
  }

  filterTests() {
    let filtered = [...this.tests];

    // Text search
    if (this.searchText.trim()) {
      const searchLower = this.searchText.toLowerCase();
      filtered = filtered.filter(test =>
        test.test_id.toLowerCase().includes(searchLower) ||
        test.tags.some(tag => tag.toLowerCase().includes(searchLower))
      );
    }

    // Tag filter
    if (this.selectedTag) {
      filtered = filtered.filter(test => test.tags.includes(this.selectedTag));
    }

    // Status filter
    if (this.selectedStatus === 'active') {
      filtered = filtered.filter(test => !test.skip);
    } else if (this.selectedStatus === 'skipped') {
      filtered = filtered.filter(test => test.skip);
    }

    this.filteredTests = filtered;
  }

  resetFilters() {
    this.searchText = '';
    this.selectedTag = '';
    this.selectedStatus = '';
    this.filterTests();
  }

  masterToggle() {
    if (this.isAllSelected()) {
      this.selection.clear();
    } else {
      this.tests.forEach(row => this.selection.select(row));
    }
  }

  isAllSelected(): boolean {
    const numSelected = this.selection.selected.length;
    const numRows = this.tests.length;
    return numSelected === numRows && numRows > 0;
  }

  selectAll() {
    this.tests.forEach(row => this.selection.select(row));
  }

  clearSelection() {
    this.selection.clear();
  }

  runSelected() {
    if (!this.selection.selected.length) {
      this.snackBar.open('Please select at least one test', 'Close', { duration: 3000 });
      return;
    }

    const totalExecutions = this.selection.selected.length * this.repeatControl.value;
    const threshold = this.appConfigService.getTestRecapThreshold();

    // Only show recap popup if total executions exceed threshold
    if (totalExecutions > threshold) {
      const summaryMessage = `You are about to run ${totalExecutions} test execution(s):
- Selected Tests: ${this.selection.selected.length}
- Repeat Count: ${this.repeatControl.value}
- Mode: ${this.modeControl.value}
- Workers: ${this.modeControl.value === 'parallel' ? this.workersControl.value : 1}
- Repeat Mode: ${this.repeatModeControl.value}

This may take some time depending on your test duration.`;

      const dialogRef = this.dialog.open(ExecutionSummaryDialog, {
        width: '500px',
        data: { message: summaryMessage }
      });

      dialogRef.afterClosed().subscribe(result => {
        if (result) {
          this.executeTests();
        }
      });
    } else {
      // If below threshold, execute without confirmation
      this.executeTests();
    }
  }

  private executeTests() {
    const request: BulkTestExecutionRequest = {
      test_ids: this.selection.selected.map(t => t.test_id),
      mode: this.modeControl.value,
      repeat: this.repeatControl.value,
      parallel_workers: this.workersControl.value,
      repeat_mode: this.repeatModeControl.value
    };

    this.currentExecutionRequest = request;
    this.isRunning = true;
    this.api.runTestsBulk(request).subscribe({
      next: (result) => {
        this.lastResult = result;
        this.isRunning = false;
        this.currentExecutionRequest = null;

        // Save execution history to localStorage
        this.saveExecutionHistory(request, result);

        const message = `Tests completed: ${result.passed} passed, ${result.failed} failed`;
        this.snackBar.open(message, 'Close', { duration: 5000 });
      },
      error: (err) => {
        this.isRunning = false;
        this.currentExecutionRequest = null;
        this.snackBar.open('Test execution failed', 'Close', { duration: 5000 });
        console.error('Error running tests:', err);
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

  private saveExecutionHistory(request: BulkTestExecutionRequest, result: BulkTestExecutionResult) {
    const history = JSON.parse(localStorage.getItem('test_execution_history') || '[]');
    const record = {
      timestamp: new Date().toISOString(),
      mode: request.mode,
      testCount: request.test_ids.length,
      result: result
    };
    history.unshift(record);
    // Keep only last 100 executions
    if (history.length > 100) {
      history.pop();
    }
    localStorage.setItem('test_execution_history', JSON.stringify(history));
  }
}

// Execution Summary Dialog Component
import { MatDialogRef, MAT_DIALOG_DATA } from '@angular/material/dialog';
import { Inject } from '@angular/core';

@Component({
  selector: 'app-execution-summary-dialog',
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
export class ExecutionSummaryDialog {
  constructor(
    public dialogRef: MatDialogRef<ExecutionSummaryDialog>,
    @Inject(MAT_DIALOG_DATA) public data: { message: string }
  ) {}

  onConfirm() {
    this.dialogRef.close(true);
  }

  onCancel() {
    this.dialogRef.close(false);
  }
}
