import { Component, input } from '@angular/core';

@Component({
  selector: 'app-json-viewer',
  standalone: true,
  template: `<pre class="json-block">{{ formatted() }}</pre>`,
  styles: [`
    :host {
      display: block;
      min-width: 0;
    }

    .json-block {
      margin: 0;
      white-space: pre-wrap;
      word-break: break-word;
      overflow-x: auto;
      max-width: 100%;
      box-sizing: border-box;
    }
  `]
})
export class JsonViewerComponent {
  readonly value = input<unknown>(null);

  formatted(): string {
    return JSON.stringify(this.value(), null, 2);
  }
}