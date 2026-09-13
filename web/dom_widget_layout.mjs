// ComfyUI's Properties/App hosts may temporarily draw a legacy widget at the
// host width. Frontend versions affected by ComfyUI_frontend#12443 persist that
// host-local value on `widget.width`; the canvas then prefers it over the live
// node width and a DOM panel visibly collapses on the next click/selection.
//
// These widgets are deliberately full-width. Keep `width` absent so both the
// classic canvas and Nodes 2.0 use their documented node-width fallback. The
// no-op setter also makes the guard safe when a host tries to assign a width.
export function pinDOMWidgetFullWidth(widget) {
  if (!widget) return widget;

  const current = Object.getOwnPropertyDescriptor(widget, "width");
  if (current?.configurable === false) {
    try { widget.width = undefined; } catch (_error) { /* best effort */ }
    return widget;
  }

  try {
    Object.defineProperty(widget, "width", {
      configurable: true,
      enumerable: current?.enumerable ?? true,
      get: () => undefined,
      set: () => {},
    });
  } catch (_error) {
    try { widget.width = undefined; } catch (_fallbackError) { /* best effort */ }
  }
  return widget;
}
