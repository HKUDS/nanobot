import { Marked } from 'marked';
import { markedHighlight } from 'marked-highlight';
import hljs from 'highlight.js';

const marked = new Marked(
	markedHighlight({
		emptyLangClass: 'hljs',
		langPrefix: 'hljs language-',
		highlight(code, lang) {
			const language = hljs.getLanguage(lang) ? lang : 'plaintext';
			return hljs.highlight(code, { language }).value;
		}
	})
);

marked.setOptions({
	breaks: true,
	gfm: true
});

marked.use({
	renderer: {
		link(arg) {
			const base = marked.Renderer.prototype.link.call(this, arg);
			return base.replace('<a', '<a target="_blank" rel="noopener noreferrer"');
		}
	}
});

/** Regex pattern for matching code fence lines */
const CODE_FENCE_PATTERN = /^(\s*)(```+)(\w*)\s*$/;

interface FenceLine {
	indent: string;
	backtickCount: number;
	lang: string;
}

interface FenceInfo {
	lineIndex: number;
	backtickCount: number;
	isOpening: boolean;
	lang: string;
	matchedWith?: number;
}

interface OpenFence {
	startIndex: number;
	backtickCount: number;
}

function parseFenceLine(line: string): FenceLine | null {
	const match = line.match(CODE_FENCE_PATTERN);
	if (!match) return null;

	return {
		indent: match[1],
		backtickCount: match[2].length,
		lang: match[3] || ''
	};
}

function isClosingFence(fence: FenceLine, openFence: OpenFence): boolean {
	return fence.backtickCount >= openFence.backtickCount && !fence.lang;
}

function identifyCodeFences(lines: string[]): FenceInfo[] {
	const fenceStack: OpenFence[] = [];
	const fences: FenceInfo[] = [];

	for (let i = 0; i < lines.length; i++) {
		const parsed = parseFenceLine(lines[i]);
		if (!parsed) continue;

		const topOfStack = fenceStack[fenceStack.length - 1];

		if (topOfStack && isClosingFence(parsed, topOfStack)) {
			const openFence = fenceStack.pop()!;
			fences.push({
				lineIndex: i,
				backtickCount: parsed.backtickCount,
				isOpening: false,
				lang: '',
				matchedWith: openFence.startIndex
			});

			const openingInfo = fences.find((f) => f.lineIndex === openFence.startIndex && f.isOpening);
			if (openingInfo) {
				openingInfo.matchedWith = i;
			}
		} else {
			fenceStack.push({ startIndex: i, backtickCount: parsed.backtickCount });
			fences.push({
				lineIndex: i,
				backtickCount: parsed.backtickCount,
				isOpening: true,
				lang: parsed.lang
			});
		}
	}

	return fences;
}

function findMaxInnerBackticks(fences: FenceInfo[], startLine: number, endLine: number): number {
	let max = 0;
	for (const fence of fences) {
		if (fence.isOpening && fence.lineIndex > startLine && fence.lineIndex < endLine) {
			max = Math.max(max, fence.backtickCount);
		}
	}
	return max;
}

function calculateAdjustments(fences: FenceInfo[]): Map<number, number> {
	const adjustments = new Map<number, number>();

	for (const fence of fences) {
		if (!fence.isOpening || fence.matchedWith === undefined) continue;

		const maxInnerBackticks = findMaxInnerBackticks(fences, fence.lineIndex, fence.matchedWith);

		if (maxInnerBackticks >= fence.backtickCount) {
			const newCount = maxInnerBackticks + 1;
			adjustments.set(fence.lineIndex, newCount);
			adjustments.set(fence.matchedWith, newCount);
		}
	}

	return adjustments;
}

function applyAdjustments(lines: string[], adjustments: Map<number, number>): string[] {
	return lines.map((line, i) => {
		const newBacktickCount = adjustments.get(i);
		if (newBacktickCount === undefined) return line;

		const parsed = parseFenceLine(line);
		if (!parsed) return line;

		return parsed.indent + '`'.repeat(newBacktickCount) + parsed.lang;
	});
}

/**
 * Pre-processes markdown to fix nested code fences.
 * When a code fence contains inner fences with the same backtick count,
 * the outer fence is expanded to use more backticks to avoid premature closing.
 */
function fixNestedCodeFences(content: string): string {
	const lines = content.split('\n');
	const fences = identifyCodeFences(lines);
	const adjustments = calculateAdjustments(fences);
	const adjustedLines = applyAdjustments(lines, adjustments);
	return adjustedLines.join('\n');
}

export function renderMarkdown(content: string): string {
	if (!content) return '';
	const processedContent = fixNestedCodeFences(content);
	return marked.parse(processedContent) as string;
}
