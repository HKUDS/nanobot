import type { Root } from "mdast";
import type { Code, Construct, Extension, State, Tokenizer } from "micromark-util-types";
import type { Plugin } from "unified";
import type {} from "micromark-extension-gfm-autolink-literal";

const CJK_PUNCTUATION = /[。，、；：！？（）【】《》「」『』“”‘’]/u;
const TRAILING_MARKERS = /[?!.,:*_~]/u;

function isCjkPunctuation(code: Code): boolean {
  return code !== null && code >= 0 && CJK_PUNCTUATION.test(String.fromCodePoint(code));
}

// Look ahead without consuming source so ordinary GFM URLs keep their grammar.
const hasCjkBoundary: Construct = {
  partial: true,
  tokenize(effects, ok, nok) {
    return start;
    function start(code: Code) {
      effects.enter("data");
      return scan(code);
    }
    function scan(code: Code): ReturnType<State> {
      if (isCjkPunctuation(code)) {
        effects.exit("data");
        return ok(code);
      }
      if (code === null || code < 0 || /[\s<>]/u.test(String.fromCodePoint(code))) {
        effects.exit("data");
        return nok(code);
      }
      effects.consume(code);
      return scan;
    }
  },
};

const cjkTrail: Construct = {
  partial: true,
  tokenize(effects, ok, nok) {
    return start;
    function start(code: Code) {
      if (isCjkPunctuation(code)) return ok(code);
      if (code === null || code < 0 || !TRAILING_MARKERS.test(String.fromCodePoint(code))) {
        return nok(code);
      }
      effects.enter("data");
      effects.consume(code);
      return scan;
    }
    function scan(code: Code): ReturnType<State> {
      if (isCjkPunctuation(code)) {
        effects.exit("data");
        return ok(code);
      }
      if (code !== null && code >= 0 && TRAILING_MARKERS.test(String.fromCodePoint(code))) {
        effects.consume(code);
        return scan;
      }
      return nok(code);
    }
  },
};

function boundCjkAutolink(construct: Construct): Construct {
  if (construct.name !== "protocolAutolink" && construct.name !== "wwwAutolink") {
    return construct;
  }
  const tokenType = construct.name === "wwwAutolink" ? "literalAutolinkWww" : "literalAutolinkHttp";
  const tokenize: Tokenizer = function (effects, ok, nok) {
    // Validate with GFM, then emit its ordinary link tokens up to the prose
    // boundary. Closing emphasis markers stay available to CommonMark.
    return effects.check(hasCjkBoundary, effects.check(construct, start, nok), (code) =>
      construct.tokenize.call(this, effects, ok, nok)(code));

    function start(code: Code) {
      effects.enter("literalAutolink");
      effects.enter(tokenType);
      return scan(code);
    }
    function scan(code: Code): ReturnType<State> {
      return effects.check(cjkTrail, end, consume)(code);
    }
    function consume(code: Code) {
      effects.consume(code);
      return scan;
    }
    function end(code: Code) {
      effects.exit(tokenType);
      effects.exit("literalAutolink");
      return ok(code);
    }
  };
  return { ...construct, tokenize };
}

/** Bound GFM bare links at CJK prose without changing explicit link targets. */
export const remarkCjkAutolinks: Plugin<[], Root> = function () {
  const data = this.data();
  data.micromarkExtensions = data.micromarkExtensions?.map((extension): Extension => {
    if (!extension.text) return extension;
    const text = { ...extension.text };
    for (const code of [72, 104, 87, 119]) {
      const constructs = text[code];
      if (constructs) {
        text[code] = Array.isArray(constructs)
          ? constructs.map(boundCjkAutolink)
          : boundCjkAutolink(constructs);
      }
    }
    return { ...extension, text };
  });
};
