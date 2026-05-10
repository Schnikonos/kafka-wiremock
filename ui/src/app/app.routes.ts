import { Routes } from '@angular/router';
import { LayoutComponent } from './layouts/main-layout/main-layout.component';
import { TestsComponent } from './features/tests/tests.component';
import { SendsComponent } from './features/sends/sends.component';
import { RulesComponent } from './features/rules/rules.component';
import { MessagesComponent } from './features/messages/messages.component';
import { LogsComponent } from './features/logs/logs.component';
import { RuleMatcherDebugComponent } from './features/debug/rule-matcher-debug.component';
import { TemplatePreviewComponent } from './features/tools/template-preview.component';
import { ExecutionHistoryComponent } from './features/tools/execution-history.component';
import { ConfigViewComponent } from './features/config/config-view.component';

export const routes: Routes = [
  {
    path: '',
    component: LayoutComponent,
    children: [
      { path: 'tests', component: TestsComponent },
      { path: 'sends', component: SendsComponent },
      { path: 'rules', component: RulesComponent },
      { path: 'messages', component: MessagesComponent },
      { path: 'logs', component: LogsComponent },
      { path: 'debug/rule-matcher', component: RuleMatcherDebugComponent },
      { path: 'tools/template-preview', component: TemplatePreviewComponent },
      { path: 'tools/execution-history', component: ExecutionHistoryComponent },
      { path: 'configuration', component: ConfigViewComponent },
      { path: '', redirectTo: 'tests', pathMatch: 'full' }
    ]
  }
];
