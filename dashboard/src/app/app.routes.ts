import { Routes } from '@angular/router';
import { ControlCenterComponent } from './pages/control-center/control-center.component';
import { CommunicationCenterComponent } from './pages/communication-center/communication-center.component';

export const routes: Routes = [
  { path: '', component: ControlCenterComponent },
  { path: 'communications', component: CommunicationCenterComponent },
  { path: '**', redirectTo: '' }
];
