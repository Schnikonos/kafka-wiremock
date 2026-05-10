import { Component, OnInit } from '@angular/core';
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
import { MatExpansionModule } from '@angular/material/expansion';
import { MatAccordion } from '@angular/material/expansion';
import { Inject } from '@angular/core';
import { ConfigService } from '../../core/services/config.service';
import { SnackBarService } from '../../core/services/snack-bar.service';

@Component({
  selector: 'app-topic-config',
  standalone: true,
  templateUrl: './topic-config.component.html',
  styleUrls: ['./topic-config.component.scss'],
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
    MatExpansionModule
  ]
})
export class TopicConfigComponent implements OnInit {
  displayedColumns: string[] = ['topic', 'message_format', 'schema_registry', 'correlation', 'actions'];
  dataSource = new MatTableDataSource<any>();
  filterText = '';
  loading = true;

  constructor(
    private configService: ConfigService,
    private dialog: MatDialog,
    private snackBar: SnackBarService
  ) {}

  ngOnInit(): void {
    this.loadTopics();
  }

  loadTopics(): void {
    this.loading = true;
    this.configService.getTopics().subscribe(
      (response: any) => {
        const topics = response.topics || [];
        this.dataSource.data = topics;
        this.loading = false;
      },
      (error) => {
        this.snackBar.error('Failed to load topics: ' + error.message);
        this.loading = false;
      }
    );
  }

  applyFilter(event: any): void {
    const filterValue = event.target.value?.toLowerCase() || '';
    this.dataSource.filter = filterValue;
  }

  viewDetails(topic: string): void {
    this.configService.getTopic(topic).subscribe(
      (config: any) => {
        this.dialog.open(TopicDetailDialog, {
          width: '600px',
          data: config
        });
      },
      (error) => {
        this.snackBar.error('Failed to load topic details');
      }
    );
  }

  refresh(): void {
    this.loadTopics();
  }
}

@Component({
  selector: 'app-topic-detail-dialog',
  standalone: true,
  template: `
    <h2 mat-dialog-title>Topic: {{ data.topic }}</h2>
    <mat-dialog-content>
      <div class="detail-section">
        <h3>Message Configuration</h3>
        <div class="config-item">
          <span class="label">Format:</span>
          <span class="value">{{ data.message_format || 'json' }}</span>
        </div>
        <div class="config-item" *ngIf="data.schema_registry_url">
          <span class="label">Schema Registry:</span>
          <span class="value">{{ data.schema_registry_url }}</span>
        </div>
      </div>

      <div class="detail-section" *ngIf="data.correlation">
        <h3>Correlation Rules</h3>
        <mat-accordion>
          <mat-expansion-panel *ngIf="data.correlation.extract">
            <mat-expansion-panel-header>
              <mat-panel-title>Extract Rules</mat-panel-title>
            </mat-expansion-panel-header>
            <pre>{{ data.correlation.extract | json }}</pre>
          </mat-expansion-panel>
          <mat-expansion-panel *ngIf="data.correlation.propagate">
            <mat-expansion-panel-header>
              <mat-panel-title>Propagate Rules</mat-panel-title>
            </mat-expansion-panel-header>
            <pre>{{ data.correlation.propagate | json }}</pre>
          </mat-expansion-panel>
        </mat-accordion>
      </div>

      <div class="detail-section" *ngIf="!data.correlation">
        <p class="text-muted">No correlation rules configured</p>
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
    pre {
      background: #f5f5f5;
      padding: 12px;
      border-radius: 4px;
      overflow: auto;
      font-size: 12px;
    }
    .text-muted {
      color: #999;
      font-style: italic;
    }
  `],
  imports: [
    CommonModule,
    MatDialogModule,
    MatExpansionModule,
    MatButton
  ]
})
export class TopicDetailDialog {
  constructor(
    public dialogRef: MatDialogRef<TopicDetailDialog>,
    @Inject(MAT_DIALOG_DATA) public data: any
  ) {}
}


