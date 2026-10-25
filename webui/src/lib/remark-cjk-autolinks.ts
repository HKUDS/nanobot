import type { Root } from "mdast";
import type { Code, Construct, Extension, State, Tokenizer } from "micromark-util-types";
import type { Plugin } from "unified";
import type {} from "micromark-extension-gfm-autolink-literal";

const CJK_PUNCTUATION = /[。，、；：！？（）【】《》「」『』“”‘’]/u;
const TRAILING_MARKERS = /[?!.,:*_~]/u;

function isCjkPunctuation(code: Code): boolean {
  return code !== null && code >= 0 && CJK_PUNCTUATION.test(String.fromCodePoint(code));
}

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
  const cjkAutolink: Construct = {
    ...construct,
    tokenize(effects, ok, nok) {
      return construct.tokenize.call(this, effects, (code) => {
        // A successful GFM tokenizer has just closed its literalAutolink token.
        // Inspect only that URL, never text beyond GFM's own link boundary.
        const token = this.events[this.events.length - 1][1];
        return CJK_PUNCTUATION.test(this.sliceSerialize(token)) ? ok(code) : nok(code);
      }, nok);
    },
  };
  const tokenize: Tokenizer = function (effects, ok, nok) {
    // Bound only URLs already accepted by GFM. Closing emphasis markers stay
    // available to CommonMark, while ordinary text keeps GFM's fast rejection.
    return effects.check(cjkAutolink, start, (code) =>
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
