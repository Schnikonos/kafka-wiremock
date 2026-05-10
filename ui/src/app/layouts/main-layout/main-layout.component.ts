import { Component, OnInit, ViewChild } from '@angular/core';
import { CommonModule } from '@angular/common';
import { MatSidenavModule, MatSidenav } from '@angular/material/sidenav';
import { MatToolbarModule } from '@angular/material/toolbar';
import { MatIconModule } from '@angular/material/icon';
import { MatButtonModule } from '@angular/material/button';
import { MatListModule } from '@angular/material/list';
import { MatDividerModule } from '@angular/material/divider';
import { MatPaginatorModule } from '@angular/material/paginator';
import { MatProgressBarModule } from '@angular/material/progress-bar';
import { MatBadgeModule } from '@angular/material/badge';
import { MatTooltipModule } from '@angular/material/tooltip';
import { MatDialogModule, MatDialog } from '@angular/material/dialog';
import { RouterModule } from '@angular/router';
import { ApiService } from '../../core/services/api.service';
import { HealthStatus } from '../../core/models';
import { AppSettingsDialogComponent } from '../../features/settings/app-settings-dialog.component';

@Component({
  selector: 'app-layout',
  standalone: true,
  imports: [
    CommonModule,
    RouterModule,
    MatSidenavModule,
    MatToolbarModule,
    MatIconModule,
    MatButtonModule,
    MatListModule,
    MatDividerModule,
    MatPaginatorModule,
    MatProgressBarModule,
    MatBadgeModule,
    MatTooltipModule,
    MatDialogModule
  ],
  template: `
    <mat-toolbar color="primary" class="app-toolbar">
      <button mat-icon-button (click)="sidenav.toggle()">
        <mat-icon>menu</mat-icon>
      </button>
      <h1 class="app-title">Kafka Wiremock Manager</h1>
      <span class="flex-spacer"></span>
      <button mat-icon-button (click)="openSettings()" matTooltip="Application Settings">
        <mat-icon>settings</mat-icon>
      </button>
      <span *ngIf="healthStatus?.status === 'UNAVAILABLE'"
            class="backend-unavailable"
            matTooltip="Backend server is not available">
        <mat-icon>cloud_off</mat-icon>
        <span class="text">Offline</span>
      </span>
      <span *ngIf="healthStatus?.status !== 'UNAVAILABLE'"
            class="backend-available"
            matTooltip="Backend server is available">
        <mat-icon>dashboard</mat-icon>
        <span class="text">Online</span>
      </span>
    </mat-toolbar>

    <mat-sidenav-container class="app-container">
      <mat-sidenav #sidenav class="app-sidenav" mode="side" opened="true">
        <mat-nav-list>
          <h2 matSubheader>Management</h2>
          <mat-list-item routerLink="/tests" routerLinkActive="active">
            <div class="nav-list-item">
              <mat-icon>assignment</mat-icon>
              <span>Test Suite</span>
            </div>
          </mat-list-item>
          <mat-list-item routerLink="/sends" routerLinkActive="active">
            <div class="nav-list-item">
              <mat-icon>send</mat-icon>
              <span>Send Messages</span>
            </div>
          </mat-list-item>
          <mat-divider></mat-divider>
          <h2 matSubheader>Infrastructure</h2>
          <mat-list-item routerLink="/rules" routerLinkActive="active">
            <div class="nav-list-item">
              <mat-icon>rule</mat-icon>
              <span>Rules</span>
            </div>
          </mat-list-item>
          <mat-list-item routerLink="/messages" routerLinkActive="active">
            <div class="nav-list-item">
              <mat-icon>message</mat-icon>
              <span>Messages</span>
            </div>
          </mat-list-item>
           <mat-list-item routerLink="/logs" routerLinkActive="active">
            <div class="nav-list-item">
              <mat-icon>description</mat-icon>
              <span>Logs</span>
            </div>
           </mat-list-item>
           <mat-list-item routerLink="/configuration" routerLinkActive="active">
             <div class="nav-list-item">
               <mat-icon>settings</mat-icon>
               <span>Configuration</span>
             </div>
           </mat-list-item>
            <mat-divider></mat-divider>
            <h2 matSubheader>Debugging</h2>
            <mat-list-item routerLink="/debug/rule-matcher" routerLinkActive="active">
              <div class="nav-list-item">
                <mat-icon>bug_report</mat-icon>
                <span>Rule Matcher</span>
              </div>
            </mat-list-item>
            <mat-divider></mat-divider>
            <h2 matSubheader>Tools</h2>
            <mat-list-item routerLink="/tools/template-preview" routerLinkActive="active">
              <div class="nav-list-item">
                <mat-icon>edit_note</mat-icon>
                <span>Template Preview</span>
              </div>
            </mat-list-item>
            <mat-list-item routerLink="/tools/execution-history" routerLinkActive="active">
              <div class="nav-list-item">
                <mat-icon>assessment</mat-icon>
                <span>Execution History</span>
              </div>
            </mat-list-item>
          </mat-nav-list>
      </mat-sidenav>

      <mat-sidenav-content class="app-content">
        <router-outlet></router-outlet>
      </mat-sidenav-content>
    </mat-sidenav-container>
  `,
  styles: [`
    :host {
      width: 100%;
    }

    .app-toolbar {
      position: sticky;
      top: 0;
      z-index: 1000;
      box-shadow: 0 2px 4px rgba(0, 0, 0, 0.1);
    }

    .app-title {
      margin: 0 0 0 16px;
      font-size: 20px;
      font-weight: 500;
    }

    .app-container {
      height: calc(100% - 64px);
    }

    .app-sidenav {
      width: 256px;
      border-right: 1px solid #e0e0e0;
    }

    .nav-list-item {
      display: flex;
      gap: 8px;
    }

    .app-content {
      width: calc(100% - 256px);
      overflow-y: auto;
      background-color: #fafafa;
    }

    .active {
      background-color: rgba(63, 81, 181, 0.08);
      border-left: 3px solid #3f51b5;
    }

    h2[matSubheader] {
      background-color: #f5f5f5;
      border-bottom: 1px solid #e0e0e0;
      padding: 12px 16px !important;
      margin: 8px 0 4px 0 !important;
      font-size: 12px !important;
      font-weight: 700 !important;
      letter-spacing: 0.5px;
      color: rgba(0, 0, 0, 0.54);
      text-transform: uppercase;
    }

    mat-divider {
      margin: 4px 0 !important;
    }

    mat-list-item {
      height: 48px;
    }

    .flex-spacer {
      flex: 1 1 auto;
    }

    .backend-unavailable {
      display: flex;
      align-items: center;
      gap: 8px;
      padding: 0 16px;
      color: #ffffff;
      font-size: 14px;
      font-weight: 500;
    }

    .backend-available {
      display: flex;
      align-items: center;
      gap: 8px;
      padding: 0 16px;
      color: #ffffff;
      font-size: 14px;
      font-weight: 500;
    }

    .backend-unavailable mat-icon {
      font-size: 20px;
      width: 20px;
      height: 20px;
    }

    .backend-unavailable .text {
      display: none;
    }

    @media (min-width: 600px) {
      .backend-unavailable .text {
        display: inline;
      }
    }
  `]
})
export class LayoutComponent implements OnInit {
  @ViewChild('sidenav') sidenav!: MatSidenav;
  healthStatus: HealthStatus | null = null;

  constructor(
    private api: ApiService,
    private dialog: MatDialog
  ) {}

  ngOnInit() {
    // Check health with a timeout to prevent blocking
    setTimeout(() => this.checkHealth(), 100);

    // Check health every 30 seconds after initial check
    setInterval(() => {
      this.checkHealth();
    }, 30000);
  }

  openSettings() {
    this.dialog.open(AppSettingsDialogComponent, {
      width: '500px',
      disableClose: false
    });
  }

  private checkHealth() {
    // Set a 5 second timeout for the health check to prevent hanging
    const timeoutPromise = new Promise<HealthStatus>((_, reject) =>
      setTimeout(() => reject(new Error('Health check timeout')), 5000)
    );

    const healthObservable = this.api.getHealth().toPromise();

    Promise.race([healthObservable, timeoutPromise])
      .then((status) => {
        this.healthStatus = status as HealthStatus;
      })
      .catch((err) => {
        // Gracefully handle health check failures
        // The UI should still work even if the backend is unavailable
        console.warn('Backend health check failed - frontend will work in offline mode:', err?.message || err);
        // Set a default unavailable status but don't block rendering
        this.healthStatus = { status: 'UNAVAILABLE' };
      });
  }
}

