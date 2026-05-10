import { Component, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { MatToolbarModule } from '@angular/material/toolbar';
import { MatTabsModule } from '@angular/material/tabs';
import { MatIconModule } from '@angular/material/icon';
import { MatButtonModule } from '@angular/material/button';
import { MatProgressSpinnerModule } from '@angular/material/progress-spinner';
import { ConfigService } from '../../core/services/config.service';
import { SnackBarService } from '../../core/services/snack-bar.service';
import { TopicConfigComponent } from './topic-config.component';
import { JmsConfigComponent } from './jms-config.component';
import { ProvidersInfoComponent } from './providers-info.component';

@Component({
  selector: 'app-config-view',
  standalone: true,
  templateUrl: './config-view.component.html',
  styleUrls: ['./config-view.component.scss'],
  imports: [
    CommonModule,
    MatToolbarModule,
    MatTabsModule,
    MatIconModule,
    MatButtonModule,
    MatProgressSpinnerModule,
    TopicConfigComponent,
    JmsConfigComponent,
    ProvidersInfoComponent
  ]
})
export class ConfigViewComponent implements OnInit {
  selectedTab = 0;

  // Topics
  topicConfig: any = null;
  topicLoading = false;

  // JMS Queue Managers
  jmsConfig: any = null;
  jmsLoading = false;

  // Providers
  providers: any = null;
  providersLoading = false;

  constructor(
    private configService: ConfigService,
    private snackBar: SnackBarService
  ) {}

  ngOnInit(): void {
    this.loadAllConfigurations();
  }

  loadAllConfigurations(): void {
    this.loadTopics();
    this.loadQueueManagers();
    this.loadProviders();
  }

  loadTopics(): void {
    this.topicLoading = true;
    this.configService.getTopics().subscribe(
      (data) => {
        this.topicConfig = data;
        this.topicLoading = false;
      },
      (error) => {
        this.snackBar.error('Failed to load topic configurations');
        this.topicLoading = false;
      }
    );
  }

  loadQueueManagers(): void {
    this.jmsLoading = true;
    this.configService.getQueueManagers().subscribe(
      (data) => {
        this.jmsConfig = data;
        this.jmsLoading = false;
      },
      (error) => {
        this.snackBar.error('Failed to load queue manager configurations');
        this.jmsLoading = false;
      }
    );
  }

  loadProviders(): void {
    this.providersLoading = true;
    this.configService.getAvailableProviders().subscribe(
      (data) => {
        this.providers = data;
        this.providersLoading = false;
      },
      (error) => {
        this.snackBar.error('Failed to load provider information');
        this.providersLoading = false;
      }
    );
  }

  onTabChange(index: number): void {
    this.selectedTab = index;
  }

  refresh(): void {
    this.loadAllConfigurations();
  }

  downloadAsJson(): void {
    const config = {
      topics: this.topicConfig,
      queueManagers: this.jmsConfig,
      providers: this.providers,
      timestamp: new Date().toISOString()
    };

    const dataStr = JSON.stringify(config, null, 2);
    const dataBlob = new Blob([dataStr], { type: 'application/json' });
    const url = URL.createObjectURL(dataBlob);
    const link = document.createElement('a');
    link.href = url;
    link.download = `kafka-wiremock-config-${new Date().getTime()}.json`;
    link.click();
    URL.revokeObjectURL(url);

    this.snackBar.success('Configuration downloaded');
  }
}


