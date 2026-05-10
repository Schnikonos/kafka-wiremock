import { Component, Input } from '@angular/core';
import { CommonModule } from '@angular/common';
import { MatCardModule } from '@angular/material/card';
import { MatChipsModule } from '@angular/material/chips';
import { MatIconModule } from '@angular/material/icon';
import { MatButtonModule } from '@angular/material/button';
import { MatExpansionModule } from '@angular/material/expansion';
import { MatTooltipModule } from '@angular/material/tooltip';

@Component({
  selector: 'app-providers-info',
  standalone: true,
  templateUrl: './providers-info.component.html',
  styleUrls: ['./providers-info.component.scss'],
  imports: [
    CommonModule,
    MatCardModule,
    MatChipsModule,
    MatIconModule,
    MatButtonModule,
    MatExpansionModule,
    MatTooltipModule
  ]
})
export class ProvidersInfoComponent {
  @Input() providers: any = null;

  constructor() {}

  getInstallCommand(provider: any): string {
    return provider.install_command || 'N/A';
  }

  copyToClipboard(text: string): void {
    navigator.clipboard.writeText(text).then(() => {
      // Silent success - user will see the button feedback
    });
  }
}


