import type { Root } from "mdast";
import type { Code, Construct, Effects, Extension, State, Token } from "micromark-util-types";
import type { Plugin } from "unified";
import type {} from "micromark-extension-math";

const BACKSLASH = 92;
const DOLLAR = 36;
const LEFT_PAREN = 40;
const RIGHT_PAREN = 41;
const LEFT_BRACKET = 91;
const RIGHT_BRACKET = 93;
const SPACE = 32;
const CARET = 94;
const UNDERSCORE = 95;
const EQUALS = 61;
const PLUS = 43;
const SLASH = 47;
const LESS_THAN = 60;
const GREATER_THAN = 62;
const LEFT_BRACE = 123;
const RIGHT_BRACE = 125;
const PIPE = 124;

type ProcessorData = {
  micromarkExtensions?: Extension[];
};

const texMathSyntax: Extension = {
  flow: {
    [BACKSLASH]: {
      tokenize: tokenizeTexMathFlow,
      concrete: true,
      name: "texMathFlow",
    },
  },
  text: {
    [BACKSLASH]: {
      tokenize: tokenizeTexMathText,
      name: "texMathText",
    },
    [DOLLAR]: {
      tokenize: tokenizeGuardedDollarMathText,
      name: "guardedDollarMathText",
    },
  },
};

export const remarkTexMath: Plugin<[], Root> = function remarkTexMath() {
  const data = this.data() as ProcessorData;
  const micromarkExtensions =
    data.micromarkExtensions || (data.micromarkExtensions = []);

  micromarkExtensions.push(texMathSyntax);
};

function isLineEnding(code: Code): boolean {
  return code === -5 || code === -4 || code === -3;
}

function isDigit(code: Code): boolean {
  return code !== null && code >= 48 && code <= 57;
}

function isOpeningDollarBlocked(code: Code): boolean {
  return code === null || code === DOLLAR || code === SPACE || isLineEnding(code);
}

function isMathSignal(code: Code): boolean {
  return code === BACKSLASH
    || code === CARET
    || code === UNDERSCORE
    || code === EQUALS
    || code === PLUS
    || code === SLASH
    || code === LESS_THAN
    || code === GREATER_THAN
    || code === LEFT_BRACE
    || code === RIGHT_BRACE
    || code === PIPE;
}

const texMathFlowClose: Construct = {
  tokenize: tokenizeTexMathFlowClose,
  partial: true,
};

// Model output commonly uses `$...$`; numeric-only spans are usually prices, not formulas.
function tokenizeGuardedDollarMathText(effects: Effects, ok: State, nok: State): State {
  let hasMathSignal = false;
  let hasContent = false;
  let firstDataCode: Code = null;
  let previousDataCode: Code = null;

  return start;

  function start(code: Code): State | undefined {
    effects.enter("mathText");
    effects.enter("mathTextSequence");
    effects.consume(code);
    return open;
  }

  function open(code: Code): State | undefined {
    if (isOpeningDollarBlocked(code)) return nok(code);

    effects.exit("mathTextSequence");
    effects.enter("mathTextData");
    return data(code);
  }

  function data(code: Code): State | undefined {
    if (code === null || isLineEnding(code)) {
      effects.exit("mathTextData");
      return nok(code);
    }

    if (code === DOLLAR) {
      effects.exit("mathTextData");
      effects.enter("mathTextSequence");
      effects.consume(code);
      effects.exit("mathTextSequence");
      effects.exit("mathText");
      return close;
    }

    consumeData(code);
    return code === BACKSLASH ? escaped : data;
  }

  function escaped(code: Code): State | undefined {
    if (code === null || isLineEnding(code)) {
      effects.exit("mathTextData");
      return nok(code);
    }

    consumeData(code);
    return data;
  }

  function close(code: Code): State | undefined {
    if (!hasContent || previousDataCode === SPACE) return nok(code);
    if (isDigit(firstDataCode) && !hasMathSignal) return nok(code);
    return ok(code);
  }

  function consumeData(code: Code): void {
    firstDataCode ??= code;
    hasContent = true;
    hasMathSignal ||= isMathSignal(code);
    previousDataCode = code;
    effects.consume(code);
  }
}

function tokenizeTexMathText(effects: Effects, ok: State, nok: State): State {
  let closeSequence: Token | undefined;

  return start;

  function start(code: Code): State | undefined {
    effects.enter("mathText");
    effects.enter("mathTextSequence");
    effects.consume(code);
    return open;
  }

  function open(code: Code): State | undefined {
    if (code !== LEFT_PAREN) return nok(code);

    effects.consume(code);
    effects.exit("mathTextSequence");
    effects.enter("mathTextData");
    return data;
  }

  function data(code: Code): State | undefined {
    if (code === null) {
      effects.exit("mathTextData");
      return nok(code);
    }

    if (code === BACKSLASH) {
      effects.exit("mathTextData");
      closeSequence = effects.enter("mathTextSequence");
      effects.consume(code);
      return close;
    }

    effects.consume(code);
    return data;
  }

  function close(code: Code): State | undefined {
    if (code === RIGHT_PAREN) {
      effects.consume(code);
      effects.exit("mathTextSequence");
      effects.exit("mathText");
      return ok;
    }

    if (closeSequence) closeSequence.type = "mathTextData";
    return data(code);
  }
}

function tokenizeTexMathFlow(effects: Effects, ok: State, nok: State): State {
  return start;

  function start(code: Code): State | undefined {
    effects.enter("mathFlow");
    effects.enter("mathFlowFence");
    effects.enter("mathFlowFenceSequence");
    effects.consume(code);
    return open;
  }

  function open(code: Code): State | undefined {
    if (code !== LEFT_BRACKET) return nok(code);

    effects.consume(code);
    effects.exit("mathFlowFenceSequence");
    effects.exit("mathFlowFence");
    return contentStart;
  }

  function contentStart(code: Code): State | undefined {
    if (code === null) return nok(code);

    if (isLineEnding(code)) {
      effects.enter("lineEnding");
      effects.consume(code);
      effects.exit("lineEnding");
      return contentStart;
    }

    if (code === BACKSLASH) {
      return effects.attempt(texMathFlowClose, done, contentStartAfterBackslash)(code);
    }

    effects.enter("mathFlowValue");
    return content(code);
  }

  function content(code: Code): State | undefined {
    if (code === null) {
      effects.exit("mathFlowValue");
      return nok(code);
    }

    if (isLineEnding(code)) {
      effects.exit("mathFlowValue");
      effects.enter("lineEnding");
      effects.consume(code);
      effects.exit("lineEnding");
      return contentStart;
    }

    if (code === BACKSLASH) {
      effects.exit("mathFlowValue");
      return effects.attempt(texMathFlowClose, done, contentStartAfterBackslash)(code);
    }

    effects.consume(code);
    return content;
  }

  function contentStartAfterBackslash(code: Code): State | undefined {
    effects.enter("mathFlowValue");
    effects.consume(code);
    return content;
  }

  function done(code: Code): State | undefined {
    effects.exit("mathFlow");
    return ok(code);
  }
}

function tokenizeTexMathFlowClose(effects: Effects, ok: State, nok: State): State {
  return start;

  function start(code: Code): State | undefined {
    effects.enter("mathFlowFence");
    effects.enter("mathFlowFenceSequence");
    effects.consume(code);
    return close;
  }

  function close(code: Code): State | undefined {
    if (code !== RIGHT_BRACKET) return nok(code);

    effects.consume(code);
    effects.exit("mathFlowFenceSequence");
    effects.exit("mathFlowFence");
    return ok;
  }
}
