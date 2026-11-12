type MeasureDiff = () => (() => void) | undefined;

const pending = new Set<MeasureDiff>();
let frame = 0;

export function scheduleDiffRender(measure: MeasureDiff) {
  pending.add(measure);
  if (frame) return;
  frame = requestAnimationFrame(() => {
    frame = 0;
    const measures = [...pending];
    pending.clear();
    // Measure every mounted diff before any Pierre render invalidates layout.
    const renders = measures.map(read => read());
    for (const render of renders) render?.();
  });
}

export function cancelDiffRender(measure: MeasureDiff) {
  pending.delete(measure);
  if (!pending.size && frame) {
    cancelAnimationFrame(frame);
    frame = 0;
  }
}
