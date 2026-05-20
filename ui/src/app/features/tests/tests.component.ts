import { Component, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule, ReactiveFormsModule, FormBuilder } from '@angular/forms';
import { Router } from '@angular/router';
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
import { MatTooltipModule } from '@angular/material/tooltip';
import { forkJoin, of } from 'rxjs';
import { catchError, map } from 'rxjs/operators';
import { ApiService } from '../../core/services/api.service';
import { AppConfigService } from '../../core/services/app-config.service';
import { ExportService } from '../../core/services/export.service';
import { Test, BulkTestExecutionRequest, BulkTestExecutionResult } from '../../core/models';
import { SelectionModel } from '@angular/cdk/collections';
import { TruncJsonPipe } from '../../core/pipes/trunc-json.pipe';

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
    MatDialogModule,
    MatTooltipModule,
    TruncJsonPipe,
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
              <button mat-stroked-button color="primary" (click)="goToLoadTest()"
                      matTooltip="Open Load Test builder{{selection.selected.length > 0 ? ' with ' + selection.selected.length + ' selected test(s)' : ''}}">
                <mat-icon>speed</mat-icon>
                Load Test{{selection.selected.length > 0 ? ' (' + selection.selected.length + ')' : ''}}
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
              'result-passed': lastResult.failed === 0,
              'result-failed': lastResult.failed > 0
            }">{{ lastResult.failed === 0 ? 'check_circle' : 'error' }}</mat-icon>
            Last Execution Results
          </mat-panel-title>
          <mat-panel-description>
            {{ lastResult.passed }} passed, {{ lastResult.failed }} failed, {{ lastResult.skipped }} skipped
            <button mat-icon-button color="primary" (click)="exportResults($event)"
                    [disabled]="isExporting"
                    [matTooltip]="isExporting ? 'Loading log data for export…' : 'Export (' + (appConfigService.getExportFormat() | uppercase) + ')'"
                    style="margin-left: 8px;">
              <mat-icon>{{ isExporting ? 'hourglass_empty' : 'download' }}</mat-icon>
            </button>
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

        <!-- Per-test expandable result rows -->
        <div class="result-details">
          <h3>Execution Details <span class="detail-hint">(expand a row to see log details)</span></h3>

          <div *ngFor="let r of lastResult.results" class="result-item">
            <mat-expansion-panel class="result-panel" (opened)="loadTestLog(r.test_id)">
              <mat-expansion-panel-header class="result-header">
                <mat-panel-title class="result-row-title">
                  <span class="result-test-id">{{ r.test_id }}</span>
                  <span [ngClass]="'status-badge status-' + r.status.toLowerCase()">{{ r.status }}</span>
                  <span class="result-duration">{{ r.elapsed_ms }}ms</span>
                </mat-panel-title>
              </mat-expansion-panel-header>

              <!-- Loading -->
              <div *ngIf="testLogsLoading[r.test_id]" class="log-loading-row">
                <mat-progress-bar mode="indeterminate"></mat-progress-bar>
                <p>Loading log details…</p>
              </div>

              <!-- Log details -->
              <ng-container *ngIf="!testLogsLoading[r.test_id] && testLogs[r.test_id] as run">

                <div *ngIf="run.errors && run.errors.length > 0" class="log-section errors-section">
                  <h5 class="section-title">Errors</h5>
                  <ul class="error-list">
                    <li *ngFor="let err of run.errors" class="error-item">{{ err }}</li>
                  </ul>
                </div>

                <div *ngIf="run.expectations && run.expectations.length > 0" class="log-section">
                  <h5 class="section-title">Expectations</h5>
                  <div *ngFor="let exp of run.expectations" class="exp-item">
                    <span class="exp-topic">{{ exp.topic }}</span>
                    <span [ngClass]="'status-badge status-' + (exp.status || '').toLowerCase()">{{ exp.status }}</span>
                    <span class="exp-counts">received {{ exp.received }}/{{ exp.expected }}</span>
                    <span class="exp-time">{{ exp.elapsed_ms }}ms</span>
                  </div>
                </div>

                <!-- When section: DB actions (when) + sent messages, sorted by timestamp -->
                <div *ngIf="getWhenItems(run).length > 0" class="log-section">
                  <h5 class="section-title">When ({{ getWhenItems(run).length }} item{{ getWhenItems(run).length !== 1 ? 's' : '' }})</h5>
                  <ng-container *ngFor="let item of getWhenItems(run)">
                    <div *ngIf="item._type === 'sent'" class="msg-item sent-msg">
                      <div class="msg-topic">→ {{ item.topic }}</div>
                      <pre class="msg-payload">{{ item.payload | json }}</pre>
                      <div *ngIf="item.headers" class="msg-headers">Headers: {{ item.headers | json }}</div>
                    </div>
                    <div *ngIf="item._type === 'db_action'" class="msg-item db-action-item">
                      <div class="db-action-header">
                        <span class="db-op-badge op-{{item.operation}}">{{ item.operation | uppercase }}</span>
                        <span class="db-step-id">step: <code>{{ item.step_id }}</code></span>
                        <span class="db-ref">db: <code>{{ item.db_ref }}</code></span>
                      </div>
                      <pre *ngIf="item.query" class="db-query">{{ item.query }}</pre>
                      <div *ngIf="item.params" class="db-params">params: <code>{{ item.params | json }}</code></div>
                      <div class="db-action-result">
                        <span *ngIf="item.rows_affected != null">rows affected: <strong>{{ item.rows_affected }}</strong></span>
                        <span *ngIf="item.row_count != null">rows returned: <strong>{{ item.row_count }}</strong></span>
                        <span *ngIf="item.generated_key != null">generated key: <code>{{ item.generated_key }}</code></span>
                      </div>
                      <pre *ngIf="item.rows && item.rows.length > 0" class="msg-payload">{{ item.rows | json }}</pre>
                    </div>
                  </ng-container>
                </div>

                <!-- Then section: DB actions (then) + received messages, sorted by timestamp -->
                <div *ngIf="getThenItems(run).length > 0" class="log-section">
                  <h5 class="section-title">Then ({{ getThenItems(run).length }} item{{ getThenItems(run).length !== 1 ? 's' : '' }})</h5>
                  <ng-container *ngFor="let item of getThenItems(run)">
                    <div *ngIf="item._type === 'received'" class="msg-item recv-msg">
                      <div class="msg-topic">
                        ← {{ item.topic }}
                        <span *ngIf="item.correlation_mismatch" class="corr-mismatch-badge">correlation mismatch</span>
                        <span *ngIf="!item.correlation_mismatch && item.conditions_matched !== undefined" class="cond-badge"
                              [ngClass]="item.conditions_matched === item.total_conditions ? 'cond-ok' : 'cond-fail'">
                          {{ item.conditions_matched }}/{{ item.total_conditions }} cond
                        </span>
                      </div>
                      <div *ngIf="item.correlation_mismatch" class="corr-mismatch-detail">
                        <span class="corr-mismatch-label">Correlation mismatch</span>
                        <span *ngIf="item.correlation_mismatch.target?.header">header: <code>{{ item.correlation_mismatch.target.header }}</code></span>
                        <span *ngIf="item.correlation_mismatch.target?.jsonpath">jsonpath: <code>{{ item.correlation_mismatch.target.jsonpath }}</code></span>
                        <span>expected: <code class="corr-expected">{{ item.correlation_mismatch.expected }}</code></span>
                        <span>actual: <code class="corr-actual">{{ item.correlation_mismatch.actual ?? '(not found)' }}</code></span>
                        <span *ngIf="item.correlation_mismatch.error" class="corr-error">error: {{ item.correlation_mismatch.error }}</span>
                      </div>
                      <pre class="msg-payload">{{ item.payload | json }}</pre>
                      <div *ngIf="item.headers && (item.headers | json) !== '{}'" class="msg-headers">Headers: {{ item.headers | json }}</div>
                      <div *ngIf="item.failed_conditions && item.failed_conditions.length > 0" class="failed-conds">
                        <span class="failed-title">Failed conditions:</span>
                        <div *ngFor="let fc of item.failed_conditions" class="failed-cond-row">
                          <span class="fc-type">[{{ fc.type }}]</span>
                          <span *ngIf="fc.expression" class="fc-expr">{{ fc.expression }}</span>
                          <span class="fc-expected">expected: <code>{{ fc.expected?.value != null ? fc.expected.value : (fc.expected?.regex != null ? '/' + fc.expected.regex + '/' : '—') }}</code></span>
                          <span class="fc-actual">actual: <code>{{ fc.actual | truncJson }}</code></span>
                        </div>
                      </div>
                    </div>
                    <div *ngIf="item._type === 'db_action'" class="msg-item db-action-item">
                      <div class="db-action-header">
                        <span class="db-op-badge op-{{item.operation}}">{{ item.operation | uppercase }}</span>
                        <span class="db-step-id">step: <code>{{ item.step_id }}</code></span>
                        <span class="db-ref">db: <code>{{ item.db_ref }}</code></span>
                      </div>
                      <pre *ngIf="item.query" class="db-query">{{ item.query }}</pre>
                      <div *ngIf="item.params" class="db-params">params: <code>{{ item.params | json }}</code></div>
                      <div class="db-action-result">
                        <span *ngIf="item.rows_affected != null">rows affected: <strong>{{ item.rows_affected }}</strong></span>
                        <span *ngIf="item.row_count != null">rows returned: <strong>{{ item.row_count }}</strong></span>
                        <span *ngIf="item.generated_key != null">generated key: <code>{{ item.generated_key }}</code></span>
                      </div>
                      <pre *ngIf="item.rows && item.rows.length > 0" class="msg-payload">{{ item.rows | json }}</pre>
                    </div>
                  </ng-container>
                </div>

                <div *ngIf="run.closest_match" class="log-section closest-section">
                  <h5 class="section-title">Closest Match ({{ run.closest_match.tier_name }})</h5>
                  <pre class="msg-payload">{{ run.closest_match.message?.payload | json }}</pre>
                  <div *ngIf="run.closest_match.message?.failed_conditions?.length > 0" class="failed-conds">
                    <span class="failed-title">Failed matchers:</span>
                    <div *ngFor="let fc of run.closest_match.message.failed_conditions" class="failed-cond-row">
                      <span class="fc-type">[{{ fc.type }}]</span>
                      <span *ngIf="fc.expression" class="fc-expr">{{ fc.expression }}</span>
                      <span class="fc-expected">expected: <code>{{ fc.expected?.value != null ? fc.expected.value : (fc.expected?.regex != null ? '/' + fc.expected.regex + '/' : '—') }}</code></span>
                      <span class="fc-actual">actual: <code>{{ fc.actual | truncJson }}</code></span>
                    </div>
                  </div>
                </div>

                <div *ngIf="run.raw" class="log-section">
                  <pre class="msg-payload">{{ run.raw }}</pre>
                </div>

              </ng-container>

              <!-- No data -->
              <div *ngIf="!testLogsLoading[r.test_id] && testLogs[r.test_id] === null" class="log-no-data">
                <mat-icon>info_outline</mat-icon>
                <span>No log available for this test</span>
              </div>
            </mat-expansion-panel>
          </div>

          <!-- Export loading indicator -->
          <div *ngIf="isExporting" class="export-loading">
            <mat-progress-bar mode="indeterminate"></mat-progress-bar>
            <p>Loading log data for export…</p>
          </div>
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

    /* Status badges */
    .status-badge  { padding: 2px 8px; border-radius: 4px; font-size: 12px; font-weight: 500; }
    .status-active   { background: #e8f5e9; color: #2e7d32; }
    .status-passed   { background: #c8e6c9; color: #2e7d32; }
    .status-failed   { background: #ffcdd2; color: #c62828; }
    .status-skipped  { background: #ffe0b2; color: #ef6c00; }
    .status-timeout  { background: #e1bee7; color: #6a1b9a; }
    .status-matched  { background: #c8e6c9; color: #1b5e20; }
    .status-no_match { background: #ffcdd2; color: #b71c1c; }
    .status-unknown  { background: #eeeeee; color: #555; }

    .result-stats {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(100px, 1fr));
      gap: 16px;
      padding: 16px;
      background-color: #f5f5f5;
      border-radius: 4px;
      margin-bottom: 16px;
    }

    .stat-item { text-align: center; }
    .stat-label { font-size: 12px; color: #757575; margin-bottom: 4px; }
    .stat-value { font-size: 24px; font-weight: 500; color: #212121; }
    .stat-passed  { color: #2e7d32; }
    .stat-failed  { color: #c62828; }
    .stat-skipped { color: #f57c00; }

    .result-details { margin-top: 16px; }
    .result-details h3 { font-size: 14px; font-weight: 500; margin: 0 0 12px 0; }
    .detail-hint { font-size: 12px; color: #999; font-weight: 400; }

    /* Per-result expansion panels */
    .result-item { margin-bottom: 6px; }
    .result-panel { box-shadow: none !important; border: 1px solid #e0e0e0 !important; border-radius: 4px !important; }
    .result-row-title { display: flex; align-items: center; gap: 12px; flex: 1; }
    .result-test-id { font-weight: 600; color: #1976d2; flex: 1; font-size: 13px; }
    .result-duration { font-size: 12px; color: #888; background: #f5f5f5; padding: 2px 8px; border-radius: 3px; }

    /* Log body sections */
    .log-section { margin-bottom: 14px; }
    .section-title { font-size: 12px; font-weight: 600; color: #666; margin: 0 0 6px 0; text-transform: uppercase; letter-spacing: 0.5px; }
    .errors-section { background: #fff8f8; padding: 10px; border-radius: 4px; border-left: 3px solid #ef9a9a; }
    .error-list { margin: 0; padding-left: 18px; }
    .error-item { color: #b71c1c; font-size: 13px; margin-bottom: 4px; }
    .exp-item { display: flex; align-items: center; gap: 10px; padding: 4px; font-size: 13px; flex-wrap: wrap; }
    .exp-topic { color: #1976d2; font-weight: 500; flex: 1; min-width: 120px; }
    .exp-counts { color: #666; font-size: 12px; }
    .exp-time { color: #999; font-size: 11px; }
    .msg-item { border: 1px solid #eee; border-radius: 4px; padding: 8px 10px; margin-bottom: 8px; }
    .sent-msg { border-left: 3px solid #42a5f5; }
    .recv-msg { border-left: 3px solid #66bb6a; }
    .db-action-item { border-left: 3px solid #ff9800; }
    .db-action-header { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; margin-bottom: 4px; }
    .db-action-result { font-size: 12px; color: #555; display: flex; gap: 12px; flex-wrap: wrap; }
    .db-query { font-size: 11px; background: #f5f5f5; padding: 4px 8px; border-radius: 3px; margin: 4px 0; color: #333; white-space: pre-wrap; word-break: break-all; }
    .db-params { font-size: 11px; color: #666; margin: 2px 0; }
    .corr-mismatch-badge { font-size: 10px; font-weight: 700; padding: 1px 6px; border-radius: 3px; background: #fff3e0; color: #e65100; border: 1px solid #ffb74d; }
    .corr-mismatch-detail { font-size: 11px; background: #fff8f0; border: 1px solid #ffcc80; border-radius: 4px; padding: 5px 8px; margin: 4px 0; display: flex; flex-wrap: wrap; gap: 8px; align-items: center; }
    .corr-mismatch-label { font-weight: 700; color: #e65100; }
    .corr-expected { color: #2e7d32; }
    .corr-actual { color: #c62828; }
    .corr-error { color: #b71c1c; font-style: italic; }
    .db-phase-badge { font-size: 10px; font-weight: 700; padding: 1px 5px; border-radius: 3px; background: #e3f2fd; color: #0d47a1; }
    .phase-then { background: #fce4ec; color: #880e4f; }
    .db-op-badge { font-size: 10px; font-weight: 700; padding: 1px 5px; border-radius: 3px; }
    .op-select { background: #e8f5e9; color: #1b5e20; }
    .op-insert { background: #e3f2fd; color: #0d47a1; }
    .op-update { background: #fff3e0; color: #e65100; }
    .op-delete { background: #ffebee; color: #b71c1c; }
    .db-step-id, .db-ref { font-size: 11px; color: #777; }
    .msg-topic { font-size: 12px; font-weight: 600; color: #555; margin-bottom: 4px; display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
    .msg-headers { font-size: 11px; color: #888; margin-top: 4px; }
    .msg-payload {
      background: #1e1e1e; color: #d4d4d4; padding: 8px 10px; border-radius: 4px;
      font-size: 11px; line-height: 1.4; overflow-x: auto; max-height: 200px; overflow-y: auto;
      margin: 4px 0; white-space: pre-wrap; word-break: break-all;
    }
    .cond-badge { font-size: 11px; padding: 2px 6px; border-radius: 3px; }
    .cond-ok   { background: #c8e6c9; color: #1b5e20; }
    .cond-fail { background: #ffcdd2; color: #b71c1c; }
    .failed-conds { font-size: 12px; color: #c62828; margin-top: 4px; }
    .failed-conds .failed-title { font-weight: 600; display: block; margin-bottom: 2px; }
    .failed-conds code { background: #f5f5f5; padding: 1px 4px; border-radius: 3px; margin: 0 2px; color: #333; }
    .failed-cond-row { display: flex; flex-wrap: wrap; align-items: baseline; gap: 6px; padding: 2px 0; border-bottom: 1px solid #fce4e4; }
    .failed-cond-row:last-child { border-bottom: none; }
    .fc-type { font-weight: 700; color: #b71c1c; min-width: 70px; }
    .fc-expr { color: #555; font-style: italic; }
    .fc-expected { color: #555; }
    .fc-actual { color: #555; }
    .closest-section { background: #fffde7; padding: 8px; border-radius: 4px; border-left: 3px solid #ffd54f; }
    .log-loading-row { padding: 16px; text-align: center; color: #999; }
    .log-loading-row p { margin: 8px 0 0 0; font-size: 13px; }
    .log-no-data { display: flex; align-items: center; gap: 8px; color: #aaa; padding: 16px; font-size: 13px; }
    .export-loading { padding: 12px 0; }
    .export-loading p { margin: 8px 0 0 0; color: #666; font-size: 13px; text-align: center; }

    .result-passed { color: #2e7d32; }
    .result-failed { color: #c62828; }

    mat-chip-set { display: flex; flex-wrap: wrap; gap: 4px; }

    .search-section {
      margin-bottom: 16px;
      display: flex;
      gap: 16px;
      align-items: center;
    }
    .search-field { width: 300px; max-width: 100%; }

    .filter-section {
      display: flex; gap: 12px; margin-bottom: 16px;
      align-items: flex-end; flex-wrap: wrap;
    }
    .filter-field { width: 150px; flex: 0 0 auto; }

    .execution-settings {
      padding: 16px; background-color: #fafafa;
      border-left: 4px solid #2196f3; margin-bottom: 16px;
    }
    .execution-settings h3 { margin: 0 0 12px 0; font-size: 14px; font-weight: 500; }
    .settings-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 16px; }
    .setting-item { display: flex; flex-direction: column; }
    .setting-label { font-size: 12px; color: #666; margin-bottom: 4px; font-weight: 500; }
    .setting-value { font-size: 14px; color: #333; font-weight: 500; }
  `]
})
export class TestsComponent implements OnInit {
  tests: Test[] = [];
  filteredTests: Test[] = [];
  selection = new SelectionModel<Test>(true, []);
  isRunning = false;
  isExporting = false;
  lastResult: BulkTestExecutionResult | null = null;
  searchText = '';
  selectedTag = '';
  selectedStatus = '';
  allTags: string[] = [];

  // Test log cache: test_id → last run data (null = loaded but empty)
  testLogs: { [id: string]: any } = {};
  testLogsLoading: { [id: string]: boolean } = {};

  private currentExecutionRequest: any = null;

  modeControl = new FormBuilder().control<'sequential' | 'parallel'>('sequential', { nonNullable: true });
  workersControl = new FormBuilder().control<number>(4, { nonNullable: true });
  repeatControl = new FormBuilder().control<number>(1, { nonNullable: true });
  repeatModeControl = new FormBuilder().control<'interleaved-repeats' | 'sequential-repeats'>('interleaved-repeats', { nonNullable: true });

  displayedColumns: string[] = ['select', 'test_id', 'tags', 'priority', 'injections', 'expectations', 'status'];

  constructor(
    private api: ApiService,
    private snackBar: MatSnackBar,
    private fb: FormBuilder,
    private dialog: MatDialog,
    public appConfigService: AppConfigService,
    private exportService: ExportService,
    private router: Router,
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
        console.warn('Failed to load tests - backend may be unavailable:', err);
        this.snackBar.open('Failed to load tests - backend connection may be unavailable', 'Close', { duration: 5000 });
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

    if (this.searchText.trim()) {
      const searchLower = this.searchText.toLowerCase();
      filtered = filtered.filter(test =>
        test.test_id.toLowerCase().includes(searchLower) ||
        test.tags.some(tag => tag.toLowerCase().includes(searchLower))
      );
    }

    if (this.selectedTag) {
      filtered = filtered.filter(test => test.tags.includes(this.selectedTag));
    }

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
      this.filteredTests.filter(row => !row.skip).forEach(row => this.selection.select(row));
    }
  }

  isAllSelected(): boolean {
    const numSelected = this.selection.selected.length;
    const numActive = this.filteredTests.filter(t => !t.skip).length;
    return numSelected === numActive && numActive > 0;
  }

  selectAll() {
    this.filteredTests.filter(row => !row.skip).forEach(row => this.selection.select(row));
  }

  clearSelection() {
    this.selection.clear();
  }

  loadTestLog(testId: string) {
    if (testId in this.testLogs || this.testLogsLoading[testId]) return;
    this.testLogsLoading[testId] = true;
    this.api.getTestLog(testId).subscribe({
      next: (resp: any) => {
        this.testLogsLoading[testId] = false;
        this.testLogs[testId] = resp?.runs?.[0] ?? null;
      },
      error: () => {
        this.testLogsLoading[testId] = false;
        this.testLogs[testId] = null;
      }
    });
  }

  runSelected() {
    if (!this.selection.selected.length) {
      this.snackBar.open('Please select at least one test', 'Close', { duration: 3000 });
      return;
    }

    const totalExecutions = this.selection.selected.length * this.repeatControl.value;
    const threshold = this.appConfigService.getTestRecapThreshold();

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
      this.executeTests();
    }
  }

  private executeTests() {
    const hasSkipped = this.selection.selected.some(t => t.skip);
    const request: BulkTestExecutionRequest = {
      test_ids: this.selection.selected.map(t => t.test_id),
      mode: this.modeControl.value,
      repeat: this.repeatControl.value,
      parallel_workers: this.workersControl.value,
      repeat_mode: this.repeatModeControl.value,
      force_run: hasSkipped,
    };

    this.currentExecutionRequest = request;
    this.isRunning = true;
    // Clear log cache for fresh run
    this.testLogs = {};
    this.testLogsLoading = {};

    this.api.runTestsBulk(request).subscribe({
      next: (result) => {
        this.lastResult = result;
        this.isRunning = false;
        this.currentExecutionRequest = null;
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
  }

  /** Navigate to the Load Test page, pre-populating with selected test IDs. */
  goToLoadTest(): void {
    const ids = this.selection.selected.map(t => t.test_id);
    this.router.navigate(['/tests/load-test'], {
      queryParams: ids.length > 0 ? { test_ids: ids.join(',') } : {}
    });
  }

  exportResults(event: Event) {
    event.stopPropagation();
    if (!this.lastResult) return;

    const fmt = this.appConfigService.getExportFormat();
    const ts = new Date().toISOString().replace(/[:.]/g, '-').slice(0, 19);

    // CSV is flat — export immediately without fetching log details
    if (fmt === 'csv') {
      const { headers, rows } = this.exportService.buildResultsCsv(this.lastResult);
      this.exportService.downloadCsv(`test-results-${ts}.csv`, headers, rows);
      this.snackBar.open('Results exported as CSV', 'Close', { duration: 3000 });
      return;
    }

    // For JSON / HTML: pre-fetch any uncached test logs for rich detail
    const testIds = (this.lastResult.results || []).map((r: any) => r.test_id as string);
    const toLoad = testIds.filter(id => !(id in this.testLogs));

    const doExport = () => {
      if (fmt === 'html') {
        this.exportService.downloadHtml(
          `test-results-${ts}.html`,
          this.exportService.buildResultsHtml(this.lastResult!, this.testLogs)
        );
      } else {
        this.exportService.downloadJson(
          `test-results-${ts}.json`,
          this.exportService.buildResultsJson(this.lastResult!, this.testLogs)
        );
      }
      this.isExporting = false;
      this.snackBar.open(`Results exported as ${fmt.toUpperCase()}`, 'Close', { duration: 3000 });
    };

    if (toLoad.length === 0) { doExport(); return; }

    this.isExporting = true;
    const requests = toLoad.map(id =>
      this.api.getTestLog(id).pipe(
        map((resp: any) => ({ id, run: resp?.runs?.[0] ?? null })),
        catchError(() => of({ id, run: null as any }))
      )
    );

    forkJoin(requests).subscribe((results: any[]) => {
      results.forEach(({ id, run }) => { this.testLogs[id] = run; });
      doExport();
    });
  }

  getWhenItems(run: any): any[] {
    const items: any[] = [];
    for (const msg of (run.sent_messages || [])) {
      items.push({ ...msg, _type: 'sent' });
    }
    for (const a of (run.db_actions || [])) {
      if (a.phase === 'when') items.push({ ...a, _type: 'db_action' });
    }
    items.sort((a, b) => (a.timestamp || '').localeCompare(b.timestamp || ''));
    return items;
  }

  getThenItems(run: any): any[] {
    const items: any[] = [];
    for (const msg of (run.received_messages || [])) {
      items.push({ ...msg, _type: 'received' });
    }
    for (const a of (run.db_actions || [])) {
      if (a.phase === 'then') items.push({ ...a, _type: 'db_action' });
    }
    items.sort((a, b) => (a.timestamp || '').localeCompare(b.timestamp || ''));
    return items;
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
