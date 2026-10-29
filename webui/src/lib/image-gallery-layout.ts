export interface ImageDimensions {
  width: number;
  height: number;
}

export interface ImageRow {
  start: number;
  widths: number[];
  height: number;
}

export const IMAGE_GAP = 8;

// Extreme screenshots keep their full content inside a bounded portrait/landscape frame.
export function imageFrameRatio(image: ImageDimensions | null): number {
  return image ? Math.max(0.5, Math.min(3, image.width / image.height)) : 1.5;
}

/** Choose ordered, equal-height rows for the gallery's at most four previews. */
export function layoutImageRows(
  images: (ImageDimensions | null)[],
  width: number,
  targetHeight: number,
  maxHeight: number,
): ImageRow[] {
  let best: ImageRow[] = [];
  let bestScore = Infinity;
  const ratios = images.map(imageFrameRatio);

  function visit(start: number, rows: ImageRow[], score: number) {
    if (start === images.length) {
      if (score < bestScore) { best = rows; bestScore = score; }
      return;
    }
    if (rows.length === 2) return;
    for (let end = start + 1; end <= images.length; end += 1) {
      const count = end - start;
      const rowRatios = ratios.slice(start, end);
      const ratioSum = rowRatios.reduce((sum, ratio) => sum + ratio, 0);
      const naturalHeight = Math.min(...images.slice(start, end).map((image, i) =>
        image ? Math.min(image.height, image.width / rowRatios[i]) : maxHeight));
      const height = Math.min((width - IMAGE_GAP * (count - 1)) / ratioSum, maxHeight, naturalHeight);
      const widths = rowRatios.map((ratio) => ratio * height);
      const unusedWidth = (width - ratioSum * height - IMAGE_GAP * (count - 1)) / width;
      const rowScore = count * (Math.log(height / targetHeight) ** 2 + unusedWidth ** 2) + 0.55;
      const lonelyLast = end === images.length && count === 1 && images.length > 2 ? 0.25 : 0;
      visit(end, [...rows, { start, widths, height }], score + rowScore + lonelyLast);
    }
  }

  visit(0, [], 0);
  return best;
}
