import {
  Component, OnInit, OnDestroy, ChangeDetectorRef, ChangeDetectionStrategy
} from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { Router, ActivatedRoute } from '@angular/router';
import { MatCardModule } from '@angular/material/card';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatInputModule } from '@angular/material/input';
import { MatSelectModule } from '@angular/material/select';
import { MatChipsModule } from '@angular/material/chips';
import { MatTableModule } from '@angular/material/table';
import { MatProgressBarModule } from '@angular/material/progress-bar';
import { MatTooltipModule } from '@angular/material/tooltip';
import { MatSnackBar, MatSnackBarModule } from '@angular/material/snack-bar';
import { MatDividerModule } from '@angular/material/divider';
import { ApiService } from '../../../core/services/api.service';
import { LoadPhase, LoadJobStatus, Test } from '../../../core/models';

interface PhaseRow extends LoadPhase {
  _id: number;
}

@Component({
  selector: 'app-load-test',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.Default,
  imports: [
    CommonModule, FormsModule,
    MatCardModule, MatButtonModule, MatIconModule,
    MatFormFieldModule, MatInputModule, MatSelectModule,
    MatChipsModule, MatTableModule, MatProgressBarModule,
    MatTooltipModule, MatSnackBarModule, MatDividerModule,
  ],
  template: `
<div class="container">

  <!-- ── Header ── -->
  <mat-card class="header-card">
    <mat-card-header>
      <mat-card-title>
        <mat-icon class="title-icon">speed</mat-icon>
        Load Test — Scenario Builder
      </mat-card-title>
      <mat-card-subtitle>
        Gatling-style closed-model: maintain N concurrent virtual users running seleted tests in a loop.
      </mat-card-subtitle>
    </mat-card-header>
  </mat-card>

  <div class="two-col">

    <!-- ── Left: Configuration form ── -->
    <div class="config-col">

      <!-- Scenario settings -->
      <mat-card>
        <mat-card-header><mat-card-title>Scenario Settings</mat-card-title></mat-card-header>
        <mat-card-content>
          <mat-form-field appearance="outline" class="full-width">
            <mat-label>Scenario Name</mat-label>
            <input matInput [(ngModel)]="scenarioName" placeholder="my-load-test">
          </mat-form-field>

          <div class="row-fields">
            <mat-form-field appearance="outline">
              <mat-label>Think Time (ms)</mat-label>
              <input matInput type="number" [(ngModel)]="thinkTimeMs" min="0">
              <mat-hint>Pause between iterations per user</mat-hint>
            </mat-form-field>
            <mat-form-field appearance="outline">
              <mat-label>Metrics Bucket (s)</mat-label>
              <input matInput type="number" [(ngModel)]="bucketS" min="1" max="60">
              <mat-hint>Aggregation window</mat-hint>
            </mat-form-field>
          </div>
        </mat-card-content>
      </mat-card>

      <!-- Test selection -->
      <mat-card>
        <mat-card-header>
          <mat-card-title>Tests to Execute</mat-card-title>
          <mat-card-subtitle>Selected tests run round-robin by each virtual user</mat-card-subtitle>
        </mat-card-header>
        <mat-card-content>
          <div class="test-chips">
            <span *ngFor="let id of selectedTestIds" class="chip-active">
              {{id}}
              <mat-icon class="chip-remove" (click)="removeTest(id)">close</mat-icon>
            </span>
            <mat-form-field appearance="outline" class="add-test-field">
              <mat-label>Add test</mat-label>
              <mat-select [(ngModel)]="testToAdd" (ngModelChange)="addTest($event)">
                <mat-option *ngFor="let t of availableTests" [value]="t.test_id">{{t.test_id}}</mat-option>
              </mat-select>
            </mat-form-field>
          </div>
          <p *ngIf="selectedTestIds.length === 0" class="hint-none">Select at least one test</p>
        </mat-card-content>
      </mat-card>

      <!-- Phase editor -->
      <mat-card>
        <mat-card-header>
          <mat-card-title>Load Phases</mat-card-title>
          <mat-card-subtitle>Defines virtual user ramp-up, steady-state, and ramp-down</mat-card-subtitle>
        </mat-card-header>
        <mat-card-content>
          <table class="phase-table" *ngIf="phases.length > 0">
            <thead>
              <tr>
                <th>#</th>
                <th>Type</th>
                <th>Duration (s)</th>
                <th>From users</th>
                <th>To users</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              <tr *ngFor="let phase of phases; let i = index">
                <td class="idx-col">{{i+1}}</td>
                <td>
                  <mat-select [(ngModel)]="phase.type" class="type-select">
                    <mat-option value="ramp">Ramp</mat-option>
                    <mat-option value="steady">Steady</mat-option>
                  </mat-select>
                </td>
                <td><input type="number" [(ngModel)]="phase.duration_s" min="1" class="num-input"></td>
                <td>
                  <input *ngIf="phase.type === 'ramp'" type="number" [(ngModel)]="phase.from_users" min="0" class="num-input">
                  <span *ngIf="phase.type === 'steady'" class="muted">—</span>
                </td>
                <td><input type="number" [(ngModel)]="phase.to_users" min="0" class="num-input"></td>
                <td>
                  <button mat-icon-button color="warn" (click)="removePhase(i)" matTooltip="Remove phase">
                    <mat-icon>delete</mat-icon>
                  </button>
                </td>
              </tr>
            </tbody>
          </table>
          <p *ngIf="phases.length === 0" class="hint-none">Add at least one phase</p>
          <div class="phase-actions">
            <button mat-stroked-button (click)="addPhase('ramp')">
              <mat-icon>trending_up</mat-icon> Add Ramp
            </button>
            <button mat-stroked-button (click)="addPhase('steady')">
              <mat-icon>remove</mat-icon> Add Steady
            </button>
          </div>

          <!-- Total duration badge -->
          <div class="duration-badge" *ngIf="phases.length > 0">
            Total duration: <strong>{{totalDurationS}} s</strong>
            <span *ngIf="maxUsersInScenario > 0"> · Peak: <strong>{{maxUsersInScenario}} users</strong></span>
          </div>
        </mat-card-content>
      </mat-card>

      <!-- Run button -->
      <div class="run-row">
        <button mat-raised-button color="primary" class="run-btn"
                [disabled]="isRunning || selectedTestIds.length === 0 || phases.length === 0"
                (click)="startRun()">
          <mat-icon>play_arrow</mat-icon>
          {{isRunning ? 'Running…' : 'Start Load Test'}}
        </button>
        <button mat-stroked-button color="warn" *ngIf="isRunning" (click)="cancelRun()">
          <mat-icon>stop</mat-icon> Cancel
        </button>
      </div>

      <!-- Progress -->
      <mat-card *ngIf="isRunning || currentJob" class="progress-card">
        <mat-card-content>
          <div class="progress-header">
            <span class="progress-title">{{currentJob?.scenario_name}}</span>
            <span class="progress-pct">{{currentJob?.progress_pct ?? 0}}%</span>
          </div>
          <mat-progress-bar mode="determinate" [value]="currentJob?.progress_pct ?? 0"></mat-progress-bar>
          <div class="live-stats" *ngIf="currentJob">
            <div class="stat-box"><span class="stat-label">Active Users</span><span class="stat-val users">{{currentJob.active_users}}</span></div>
            <div class="stat-box"><span class="stat-label">Elapsed</span><span class="stat-val">{{currentJob.elapsed_s}}s</span></div>
            <div class="stat-box"><span class="stat-label">OK</span><span class="stat-val ok">{{liveOk}}</span></div>
            <div class="stat-box"><span class="stat-label">KO</span><span class="stat-val ko">{{liveKo}}</span></div>
            <div class="stat-box"><span class="stat-label">Error %</span><span class="stat-val" [class.ko]="liveErrorPct > 2">{{liveErrorPct | number:'1.1-1'}}%</span></div>
          </div>
          <div class="done-actions" *ngIf="!isRunning && currentJob && (currentJob.status === 'COMPLETED' || currentJob.status === 'CANCELLED')">
            <button mat-raised-button color="accent" (click)="viewReport()">
              <mat-icon>bar_chart</mat-icon> View Full Report
            </button>
          </div>
        </mat-card-content>
      </mat-card>
    </div>

    <!-- ── Right: Load Shape Preview ── -->
    <div class="preview-col">
      <mat-card class="preview-card">
        <mat-card-header>
          <mat-card-title>Load Shape Preview</mat-card-title>
          <mat-card-subtitle>Visual representation of virtual user count over time</mat-card-subtitle>
        </mat-card-header>
        <mat-card-content>
          <div class="svg-wrapper" *ngIf="loadShape.totalSeconds > 0; else emptyShape">
            <svg [attr.viewBox]="loadShape.viewBox" preserveAspectRatio="none" class="shape-svg">
              <!-- Grid lines -->
              <line x1="0" [attr.y1]="loadShape.h * 0.25" [attr.x2]="loadShape.w" [attr.y2]="loadShape.h * 0.25" stroke="#e0e0e0" stroke-width="0.5"/>
              <line x1="0" [attr.y1]="loadShape.h * 0.5"  [attr.x2]="loadShape.w" [attr.y2]="loadShape.h * 0.5"  stroke="#e0e0e0" stroke-width="0.5"/>
              <line x1="0" [attr.y1]="loadShape.h * 0.75" [attr.x2]="loadShape.w" [attr.y2]="loadShape.h * 0.75" stroke="#e0e0e0" stroke-width="0.5"/>
              <!-- Phase separators -->
              <line *ngFor="let m of loadShape.markers"
                    [attr.x1]="m.x" y1="0"
                    [attr.x2]="m.x" [attr.y2]="loadShape.h"
                    stroke="#9e9e9e" stroke-width="0.8" stroke-dasharray="2,3"/>
              <!-- Filled area -->
              <path [attr.d]="loadShape.path" fill="rgba(63,81,181,0.18)" stroke="#3f51b5" stroke-width="1.5" stroke-linejoin="round"/>
              <!-- Live progress marker: red vertical line at current elapsed position -->
              <line *ngIf="(isRunning || currentJob?.status === 'COMPLETED') && currentJob && nowLineX > 0"
                    [attr.x1]="nowLineX" y1="0"
                    [attr.x2]="nowLineX" [attr.y2]="loadShape.h"
                    stroke="#f44336" stroke-width="2" opacity="0.85"/>
              <!-- Tiny circle at current position on the shape -->
              <circle *ngIf="(isRunning || currentJob?.status === 'COMPLETED') && currentJob && nowLineX > 0"
                      [attr.cx]="nowLineX" [attr.cy]="loadShape.h * 0.08"
                      r="3" fill="#f44336" opacity="0.9"/>
            </svg>
            <!-- Axis labels -->
            <div class="axis-labels">
              <span class="axis-label-left">{{loadShape.maxUsers}} users</span>
              <span class="axis-label-right">0s → {{loadShape.totalSeconds}}s</span>
            </div>
            <!-- Phase labels -->
            <div class="phase-labels">
              <span *ngFor="let m of loadShape.markers; let i = index"
                    class="phase-label"
                    [style.left.%]="m.pct">
                Phase {{i+2}}
              </span>
            </div>
            <!-- Live stats overlay bar (shown during/after run) -->
            <div class="live-overlay" *ngIf="currentJob && latestBucket">
              <div class="ol-stat users">
                <span class="ol-lbl">👤 Active</span>
                <span class="ol-val">{{currentJob.active_users}}</span>
              </div>
              <div class="ol-sep"></div>
              <div class="ol-stat">
                <span class="ol-lbl">⏱ Mean</span>
                <span class="ol-val">{{latestBucket.mean_ms | number:'1.0-0'}} ms</span>
              </div>
              <div class="ol-sep"></div>
              <div class="ol-stat ok">
                <span class="ol-lbl">✅ OK/s</span>
                <span class="ol-val">{{liveOkTps | number:'1.1-1'}}</span>
              </div>
              <div class="ol-sep"></div>
              <div class="ol-stat ko">
                <span class="ol-lbl">❌ KO/s</span>
                <span class="ol-val">{{liveKoTps | number:'1.1-1'}}</span>
              </div>
            </div>
          </div>
          <ng-template #emptyShape>
            <div class="empty-shape">
              <mat-icon>show_chart</mat-icon>
              <p>Add phases to see the load shape preview</p>
            </div>
          </ng-template>
        </mat-card-content>
      </mat-card>

      <!-- Quick reference -->
      <mat-card class="ref-card">
        <mat-card-header><mat-card-title>Phase Reference</mat-card-title></mat-card-header>
        <mat-card-content>
          <div class="ref-row"><strong>Ramp</strong> — Linearly increase / decrease users from <em>from</em> to <em>to</em> over the duration</div>
          <div class="ref-row"><strong>Steady</strong> — Maintain a constant number of users for the duration</div>
          <mat-divider style="margin: 12px 0"></mat-divider>
          <div class="ref-row"><strong>Virtual User</strong> — An asyncio task that loops: run test → think → run test → …</div>
          <div class="ref-row"><strong>Closed model</strong> — Concurrency is capped; each user waits for the previous iteration to complete before starting the next</div>
        </mat-card-content>
      </mat-card>
    </div>

  </div>
</div>
  `,
  styles: [`
    .container { padding: 16px; max-width: 1400px; margin: 0 auto; }
    .header-card { margin-bottom: 16px; }
    .title-icon { vertical-align: middle; margin-right: 8px; }

    .two-col { display: grid; grid-template-columns: 1fr 420px; gap: 16px; align-items: start; }
    @media (max-width: 1100px) { .two-col { grid-template-columns: 1fr; } }

    .config-col { display: flex; flex-direction: column; gap: 16px; }
    .preview-col { display: flex; flex-direction: column; gap: 16px; position: sticky; top: 80px; }

    mat-card { margin-bottom: 0; }
    mat-card-content { padding-top: 12px; }

    .full-width { width: 100%; }
    .row-fields { display: flex; gap: 16px; flex-wrap: wrap; }
    .row-fields mat-form-field { flex: 1; min-width: 140px; }

    /* test chips */
    .test-chips { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; }
    .chip-active {
      display: inline-flex; align-items: center; gap: 4px;
      background: #e8eaf6; color: #3f51b5; border-radius: 16px;
      padding: 4px 10px; font-size: 13px; font-weight: 500;
    }
    .chip-remove { font-size: 16px; width: 16px; height: 16px; cursor: pointer; color: #9e9e9e; }
    .chip-remove:hover { color: #f44336; }
    .add-test-field { min-width: 180px; }
    .hint-none { color: #9e9e9e; font-style: italic; font-size: 13px; margin: 8px 0 0; }

    /* phase table */
    .phase-table { width: 100%; border-collapse: collapse; font-size: 13px; margin-bottom: 12px; }
    .phase-table th { text-align: left; padding: 6px 8px; border-bottom: 2px solid #e0e0e0; color: rgba(0,0,0,.54); font-weight: 600; }
    .phase-table td { padding: 6px 8px; border-bottom: 1px solid #f0f0f0; }
    .idx-col { color: #9e9e9e; width: 28px; }
    .type-select { font-size: 13px; }
    .num-input { width: 70px; padding: 4px 6px; border: 1px solid #ccc; border-radius: 4px; font-size: 13px; }
    .num-input:focus { outline: none; border-color: #3f51b5; }
    .muted { color: #bdbdbd; }
    .phase-actions { display: flex; gap: 8px; margin-top: 4px; }
    .duration-badge { margin-top: 12px; font-size: 13px; color: rgba(0,0,0,.6); background: #f5f5f5; padding: 6px 12px; border-radius: 4px; }

    /* run row */
    .run-row { display: flex; gap: 12px; align-items: center; }
    .run-btn { min-width: 160px; }

    /* progress */
    .progress-card { background: #f8f9ff; }
    .progress-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px; }
    .progress-title { font-weight: 600; font-size: 14px; }
    .progress-pct { font-size: 13px; color: #3f51b5; font-weight: 600; }
    .live-stats { display: flex; gap: 12px; flex-wrap: wrap; margin-top: 12px; }
    .stat-box { display: flex; flex-direction: column; align-items: center; background: white; border-radius: 8px; padding: 8px 14px; box-shadow: 0 1px 3px rgba(0,0,0,0.1); min-width: 72px; }
    .stat-label { font-size: 11px; color: #9e9e9e; text-transform: uppercase; letter-spacing: .5px; }
    .stat-val { font-size: 20px; font-weight: 700; color: #333; }
    .stat-val.users { color: #3f51b5; }
    .stat-val.ok { color: #4caf50; }
    .stat-val.ko { color: #f44336; }
    .done-actions { margin-top: 12px; }

    /* svg preview */
    .preview-card { }
    .svg-wrapper { position: relative; }
    .shape-svg { display: block; width: 100%; height: 160px; border: 1px solid #e0e0e0; border-radius: 4px; background: #fafafa; }
    .axis-labels { display: flex; justify-content: space-between; font-size: 11px; color: #9e9e9e; margin-top: 4px; }
    .phase-labels { position: relative; height: 16px; }
    .phase-label { position: absolute; font-size: 10px; color: #9e9e9e; transform: translateX(-50%); }
    .empty-shape { display: flex; flex-direction: column; align-items: center; padding: 32px; color: #bdbdbd; }
    .empty-shape mat-icon { font-size: 48px; width: 48px; height: 48px; }
    .empty-shape p { margin-top: 8px; font-size: 13px; }

    /* live overlay stats bar */
    .live-overlay {
      display: flex; align-items: center; gap: 0;
      background: rgba(33,33,33,0.88); border-radius: 6px;
      padding: 5px 10px; margin-top: 6px; width: fit-content;
    }
    .ol-stat { display: flex; flex-direction: column; align-items: center; padding: 2px 10px; }
    .ol-lbl { font-size: 10px; color: rgba(255,255,255,0.6); text-transform: uppercase; letter-spacing: .4px; }
    .ol-val { font-size: 14px; font-weight: 700; color: #fff; font-variant-numeric: tabular-nums; }
    .ol-stat.users .ol-val { color: #90caf9; }
    .ol-stat.ok .ol-val { color: #a5d6a7; }
    .ol-stat.ko .ol-val { color: #ef9a9a; }
    .ol-sep { width: 1px; height: 28px; background: rgba(255,255,255,0.15); margin: 0 2px; }

    /* ref */
    .ref-card { font-size: 13px; }
    .ref-row { margin-bottom: 8px; line-height: 1.5; }
  `],
})
export class LoadTestComponent implements OnInit, OnDestroy {
  // ─── Scenario config ──────────────────────────────────────────────────────
  scenarioName = 'load-scenario';
  thinkTimeMs = 0;
  bucketS = 5;
  selectedTestIds: string[] = [];
  testToAdd = '';
  phases: PhaseRow[] = [];
  availableTests: Test[] = [];

  private _phaseCounter = 0;

  // ─── Run state ────────────────────────────────────────────────────────────
  isRunning = false;
  currentJobId: string | null = null;
  currentJob: LoadJobStatus | null = null;
  private pollInterval: any;

  constructor(
    private api: ApiService,
    private router: Router,
    private route: ActivatedRoute,
    private snack: MatSnackBar,
    private cd: ChangeDetectorRef,
  ) {}

  ngOnInit(): void {
    // Load available tests
    this.api.getTests().subscribe({
      next: (resp) => { this.availableTests = resp.tests; },
      error: () => {},
    });

    // Pre-populate from query params (when navigated from Tests page)
    this.route.queryParams.subscribe(params => {
      const ids: string = params['test_ids'] || '';
      if (ids) {
        this.selectedTestIds = ids.split(',').filter(Boolean);
      }
    });

    // Seed with a default useful scenario
    if (this.phases.length === 0) {
      this.addPhase('ramp', { from_users: 0, to_users: 5, duration_s: 30 });
      this.addPhase('steady', { to_users: 5, duration_s: 60 });
      this.addPhase('ramp', { from_users: 5, to_users: 0, duration_s: 15 });
    }
  }

  ngOnDestroy(): void {
    this.stopPolling();
  }

  // ─── Phase management ─────────────────────────────────────────────────────
  addPhase(type: 'ramp' | 'steady', defaults?: Partial<PhaseRow>): void {
    const lastTo = this.phases.length > 0 ? this.phases[this.phases.length - 1].to_users : 0;
    this.phases.push({
      _id: this._phaseCounter++,
      type,
      duration_s: defaults?.duration_s ?? 30,
      from_users: defaults?.from_users ?? lastTo,
      to_users: defaults?.to_users ?? lastTo,
      model: 'closed',
    });
  }

  removePhase(idx: number): void {
    this.phases.splice(idx, 1);
  }

  // ─── Test selection ───────────────────────────────────────────────────────
  addTest(id: string): void {
    if (id && !this.selectedTestIds.includes(id)) {
      this.selectedTestIds = [...this.selectedTestIds, id];
    }
    this.testToAdd = '';
  }

  removeTest(id: string): void {
    this.selectedTestIds = this.selectedTestIds.filter(t => t !== id);
  }

  // ─── Computed: load shape SVG ─────────────────────────────────────────────
  get loadShape(): {
    path: string; viewBox: string; w: number; h: number;
    maxUsers: number; totalSeconds: number;
    markers: { x: number; pct: number }[];
  } {
    const W = 400, H = 100, PAD = 8;
    const total = this.phases.reduce((s, p) => s + (p.duration_s || 0), 0);
    const maxU = Math.max(...this.phases.map(p => Math.max(p.from_users || 0, p.to_users || 0)), 1);

    if (total === 0 || this.phases.length === 0) {
      return { path: '', viewBox: `0 0 ${W} ${H}`, w: W, h: H, maxUsers: 0, totalSeconds: 0, markers: [] };
    }

    const toX = (t: number) => (t / total) * W;
    const toY = (u: number) => H - PAD - ((u / maxU) * (H - PAD * 2));

    const pts: string[] = [`M0,${H}`];
    let t = 0;
    const markers: { x: number; pct: number }[] = [];

    for (let i = 0; i < this.phases.length; i++) {
      const ph = this.phases[i];
      const x1 = toX(t);
      const x2 = toX(t + (ph.duration_s || 0));

      if (ph.type === 'ramp') {
        pts.push(`L${x1},${toY(ph.from_users || 0)}`);
        pts.push(`L${x2},${toY(ph.to_users || 0)}`);
      } else {
        pts.push(`L${x1},${toY(ph.to_users || 0)}`);
        pts.push(`L${x2},${toY(ph.to_users || 0)}`);
      }

      t += ph.duration_s || 0;
      if (i < this.phases.length - 1) {
        markers.push({ x: toX(t), pct: (t / total) * 100 });
      }
    }

    pts.push(`L${W},${H}`, 'Z');
    return {
      path: pts.join(' '),
      viewBox: `0 0 ${W} ${H}`,
      w: W, h: H,
      maxUsers: maxU,
      totalSeconds: total,
      markers,
    };
  }

  get totalDurationS(): number {
    return this.phases.reduce((s, p) => s + (p.duration_s || 0), 0);
  }

  get maxUsersInScenario(): number {
    return Math.max(...this.phases.map(p => p.to_users || 0), 0);
  }

  get liveOk(): number {
    return (this.currentJob?.buckets ?? []).reduce((s, b) => s + b.ok, 0);
  }

  get liveKo(): number {
    return (this.currentJob?.buckets ?? []).reduce((s, b) => s + b.ko, 0);
  }

  get liveErrorPct(): number {
    const total = this.liveOk + this.liveKo;
    return total > 0 ? (this.liveKo / total) * 100 : 0;
  }

  /** X coordinate in SVG space for the current elapsed time (the "now" line). */
  get nowLineX(): number {
    if (!this.currentJob || !this.loadShape.totalSeconds) return 0;
    return Math.min(
      (this.currentJob.elapsed_s / this.loadShape.totalSeconds) * this.loadShape.w,
      this.loadShape.w
    );
  }

  /** Most recently flushed metrics bucket. */
  get latestBucket(): any | null {
    const buckets = this.currentJob?.buckets;
    return buckets?.length ? buckets[buckets.length - 1] : null;
  }

  /** OK tests per second in the latest bucket. */
  get liveOkTps(): number {
    if (!this.latestBucket) return 0;
    const bs = this.currentJob?.scenario?.bucket_s ?? 5;
    return this.latestBucket.ok / bs;
  }

  /** KO tests per second in the latest bucket. */
  get liveKoTps(): number {
    if (!this.latestBucket) return 0;
    const bs = this.currentJob?.scenario?.bucket_s ?? 5;
    return this.latestBucket.ko / bs;
  }

  // ─── Run / Cancel ─────────────────────────────────────────────────────────
  startRun(): void {
    if (this.selectedTestIds.length === 0) {
      this.snack.open('Select at least one test', 'Close', { duration: 3000 });
      return;
    }
    if (this.phases.length === 0) {
      this.snack.open('Add at least one phase', 'Close', { duration: 3000 });
      return;
    }

    const request = {
      name: this.scenarioName || 'load-scenario',
      test_ids: this.selectedTestIds,
      phases: this.phases.map(p => ({
        type: p.type,
        duration_s: p.duration_s,
        from_users: p.from_users,
        to_users: p.to_users,
        model: 'closed' as const,
      })),
      think_time_ms: this.thinkTimeMs,
      bucket_s: this.bucketS,
    };

    this.isRunning = true;
    this.currentJob = null;

    this.api.startLoadTest(request).subscribe({
      next: (resp) => {
        this.currentJobId = resp.job_id;
        this.snack.open(`Load test started (job ${resp.job_id.substring(0, 8)}…)`, 'Close', { duration: 3000 });
        this.startPolling();
      },
      error: (err) => {
        this.isRunning = false;
        this.snack.open(`Failed to start: ${err.message}`, 'Close', { duration: 5000 });
      },
    });
  }

  cancelRun(): void {
    if (!this.currentJobId) return;
    this.api.cancelLoadJob(this.currentJobId).subscribe({
      next: () => {
        this.snack.open('Cancel requested', 'Close', { duration: 2000 });
      },
    });
  }

  viewReport(): void {
    if (this.currentJobId) {
      this.router.navigate(['/tests/load-report', this.currentJobId]);
    }
  }

  // ─── Polling ──────────────────────────────────────────────────────────────
  private startPolling(): void {
    this.stopPolling();
    this.pollInterval = setInterval(() => this.poll(), 2000);
    this.poll(); // immediate first fetch
  }

  private stopPolling(): void {
    if (this.pollInterval) {
      clearInterval(this.pollInterval);
      this.pollInterval = null;
    }
  }

  private poll(): void {
    if (!this.currentJobId) return;
    this.api.getLoadJob(this.currentJobId).subscribe({
      next: (job) => {
        this.currentJob = job;
        if (job.status !== 'RUNNING' && job.status !== 'PENDING') {
          this.isRunning = false;
          this.stopPolling();
        }
        this.cd.markForCheck();
      },
      error: () => {
        this.isRunning = false;
        this.stopPolling();
      },
    });
  }
}

