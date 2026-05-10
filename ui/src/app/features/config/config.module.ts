import { NgModule } from '@angular/core';
import { CommonModule } from '@angular/common';
import { HttpClientModule } from '@angular/common/http';

// Material imports
import { MatTableModule } from '@angular/material/table';
import { MatToolbarModule } from '@angular/material/toolbar';
import { MatIconModule } from '@angular/material/icon';
import { MatButtonModule } from '@angular/material/button';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatInputModule } from '@angular/material/input';
import { MatChipsModule } from '@angular/material/chips';
import { MatProgressSpinnerModule } from '@angular/material/progress-spinner';
import { MatDialogModule } from '@angular/material/dialog';
import { MatTabsModule } from '@angular/material/tabs';
import { MatCardModule } from '@angular/material/card';
import { MatExpansionModule } from '@angular/material/expansion';
import { MatTooltipModule } from '@angular/material/tooltip';

// Components
import { ConfigViewComponent } from './config-view.component';
import { TopicConfigComponent, TopicDetailDialog } from './topic-config.component';
import { JmsConfigComponent, JmsDetailDialog } from './jms-config.component';
import { ProvidersInfoComponent } from './providers-info.component';

@NgModule({
  declarations: [
    ConfigViewComponent,
    TopicConfigComponent,
    TopicDetailDialog,
    JmsConfigComponent,
    JmsDetailDialog,
    ProvidersInfoComponent
  ],
  imports: [
    CommonModule,
    HttpClientModule,
    MatTableModule,
    MatToolbarModule,
    MatIconModule,
    MatButtonModule,
    MatFormFieldModule,
    MatInputModule,
    MatChipsModule,
    MatProgressSpinnerModule,
    MatDialogModule,
    MatTabsModule,
    MatCardModule,
    MatExpansionModule,
    MatTooltipModule
  ]
})
export class ConfigModule { }

