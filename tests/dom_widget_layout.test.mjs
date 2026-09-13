import assert from "node:assert/strict";
import { pinDOMWidgetFullWidth } from "../web/dom_widget_layout.mjs";

const widget = { width: 460, y: 12 };
const returned = pinDOMWidgetFullWidth(widget);

assert.equal(returned, widget);
assert.equal(widget.width, undefined);
assert.equal(widget.y, 12);

// Reproduce the Properties/App host write that causes ComfyUI_frontend#12443.
widget.width = 394;
assert.equal(widget.width, undefined);

const descriptor = Object.getOwnPropertyDescriptor(widget, "width");
assert.equal(descriptor?.configurable, true);
assert.equal(typeof descriptor?.set, "function");

// Re-applying the guard is harmless during onConfigure/nodeCreated races.
pinDOMWidgetFullWidth(widget);
widget.width = 520;
assert.equal(widget.width, undefined);

console.log("DOM_WIDGET_LAYOUT_OK full-width fallback survives stale host writes");
