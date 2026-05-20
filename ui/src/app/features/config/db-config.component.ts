import { Component, OnInit, OnDestroy } from '@angular/core';
import { CommonModule } from '@angular/common';
import { MatTableModule, MatTableDataSource } from '@angular/material/table';
import { MatToolbarModule } from '@angular/material/toolbar';
import { MatIconModule } from '@angular/material/icon';
import { MatButtonModule } from '@angular/material/button';
import { MatChipsModule } from '@angular/material/chips';
import { MatProgressSpinnerModule } from '@angular/material/progress-spinner';
import { MatTooltipModule } from '@angular/material/tooltip';
import { MatCardModule } from '@angular/material/card';
import { MatDialogModule, MatDialog } from '@angular/material/dialog';
import { MatDividerModule } from '@angular/material/divider';
import { ConfigService } from '../../core/services/config.service';
import { SnackBarService } from '../../core/services/snack-bar.service';

export interface DbEntry {
  name: string;
  provider: string;
  host: string;
  available: number;
  in_use: number;
  max_size: number;
  providerInstalled: boolean;
}

@Component({
  selector: 'app-db-config',
  standalone: true,
  templateUrl: './db-config.component.html',
  styleUrls: ['./db-config.component.scss'],
  imports: [
    CommonModule,
    MatTableModule,
    MatToolbarModule,
    MatIconModule,
    MatButtonModule,
    MatChipsModule,
    MatProgressSpinnerModule,
    MatTooltipModule,
    MatCardModule,
    MatDialogModule,
    MatDividerModule,
  ]
})
export class DbConfigComponent implements OnInit, OnDestroy {
  displayedColumns: string[] = ['name', 'provider', 'host', 'pool_available', 'pool_in_use', 'pool_max', 'status'];
  dataSource = new MatTableDataSource<DbEntry>();

  loading = false;
  hasNoDatabases = false;
  message = '';

  /** Raw providers map from /api/db/providers */
  private providersMap: Record<string, any> = {};

  constructor(
    private configService: ConfigService,
    private snackBar: SnackBarService
  ) {}

  ngOnInit(): void {
    this.load();
  }

  ngOnDestroy(): void {}

  load(): void {
    this.loading = true;
    this.hasNoDatabases = false;
    this.message = '';

    // Load both status and providers in parallel
    this.configService.getDatabaseProviders().subscribe({
      next: (resp: any) => {
        this.providersMap = resp?.providers || {};
        this.loadStatus();
      },
      error: () => {
        // Providers endpoint can fail gracefully
        this.loadStatus();
      }
    });
  }

  private loadStatus(): void {
    this.configService.getDatabaseStatus().subscribe({
      next: (resp: any) => {
        const dbs: Record<string, any> = resp?.databases || {};
        const keys = Object.keys(dbs);
        if (keys.length === 0) {
          this.hasNoDatabases = true;
          this.message = resp?.message || 'No databases configured (see db-config/databases.yaml)';
          this.dataSource.data = [];
        } else {
          this.dataSource.data = keys.map(name => {
            const db = dbs[name];
            const pool = db?.pool || {};
            const providerKey = db?.provider || '';
            const providerInfo = this.providersMap[providerKey];
            return {
              name,
              provider: providerKey,
              host: db?.host || '—',
              available: pool.available ?? 0,
              in_use: pool.in_use ?? 0,
              max_size: pool.max_size ?? 0,
              providerInstalled: providerInfo?.available ?? true,
            } as DbEntry;
          });
        }
        this.loading = false;
      },
      error: (err: any) => {
        this.snackBar.error('Failed to load database status: ' + (err.message || 'Unknown error'));
        this.loading = false;
      }
    });
  }

  refresh(): void {
    this.load();
  }

  getConnectionStatusClass(entry: DbEntry): string {
    // A database is "active" when the pool has allocated at least one connection
    return (entry.available + entry.in_use) > 0 ? 'status-active' : 'status-unknown';
  }

  getConnectionStatusLabel(entry: DbEntry): string {
    return (entry.available + entry.in_use) > 0 ? 'Active' : 'Unknown';
  }

  getPoolUsagePercent(entry: DbEntry): number {
    if (!entry.max_size) return 0;
    return Math.round((entry.in_use / entry.max_size) * 100);
  }
}

