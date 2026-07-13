import { Component, input } from '@angular/core';

@Component({
  selector: 'app-json-viewer',
  standalone: true,
  template: `<pre class="json-block">{{ formatted() }}</pre>`
})
export class JsonViewerComponent {
  readonly value = input<unknown>(null);

  formatted(): string {
    return JSON.stringify(this.value(), null, 2);
  }
}
