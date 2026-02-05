import builtins
import inspect
import io
import keyword
import linecache
import os
import re
import sys
import sysconfig
import tokenize
import traceback

if sys.version_info >= (3, 11):

    def is_exception_group(exc):
        return isinstance(exc, ExceptionGroup)

else:
    try:
        from exceptiongroup import ExceptionGroup
    except ImportError:

        def is_exception_group(exc):
            return False

    else:

        def is_exception_group(exc):
            return isinstance(exc, ExceptionGroup)


class SyntaxHighlighter:
    _default_style = frozenset(
        {
            "comment": "\x1b[30m\x1b[1m{}\x1b[0m",
            "keyword": "\x1b[35m\x1b[1m{}\x1b[0m",
            "builtin": "\x1b[1m{}\x1b[0m",
            "string": "\x1b[36m{}\x1b[0m",
            "number": "\x1b[34m\x1b[1m{}\x1b[0m",
            "operator": "\x1b[35m\x1b[1m{}\x1b[0m",
            "punctuation": "\x1b[1m{}\x1b[0m",
            "constant": "\x1b[36m\x1b[1m{}\x1b[0m",
            "identifier": "\x1b[1m{}\x1b[0m",
            "other": "{}",
        }.items()
    )

    _builtins = frozenset(dir(builtins))
    _constants = frozenset({"True", "False", "None"})
    _punctuation = frozenset({"(", ")", "[", "]", "{", "}", ":", ",", ";"})

    if sys.version_info >= (3, 12):
        _strings = frozenset(
            {tokenize.STRING, tokenize.FSTRING_START, tokenize.FSTRING_MIDDLE, tokenize.FSTRING_END}
        )
        _fstring_middle = tokenize.FSTRING_MIDDLE
    else:
        _strings = frozenset({tokenize.STRING})
        _fstring_middle = None

    def __init__(self, style=None):
        self._style = style or dict(self._default_style)

    def highlight(self, source):
        style = self._style
        row, column = 0, 0
        output = ""

        for token in self.tokenize(source):
            type_, string, (start_row, start_column), (_, end_column), line = token

            if type_ == self._fstring_middle:
                # When an f-string contains "{{" or "}}", they appear as "{" or "}" in the "string"
                # attribute of the token. However, they do not count in the column position.
                end_column += string.count("{") + string.count("}")

            if type_ == tokenize.NAME:
                if string in self._constants:
                    color = style["constant"]
                elif keyword.iskeyword(string):
                    color = style["keyword"]
                elif string in self._builtins:
                    color = style["builtin"]
                else:
                    color = style["identifier"]
            elif type_ == tokenize.OP:
                if string in self._punctuation:
                    color = style["punctuation"]
                else:
                    color = style["operator"]
            elif type_ == tokenize.NUMBER:
                color = style["number"]
            elif type_ in self._strings:
                color = style["string"]
            elif type_ == tokenize.COMMENT:
                color = style["comment"]
            else:
                color = style["other"]

            if start_row != row:
                source = source[column:]
                row, column = start_row, 0

            if type_ != tokenize.ENCODING:
                output += line[column:start_column]
                output += color.format(line[start_column:end_column])

            column = end_column

        output += source[column:]

        return output

    @staticmethod
    def tokenize(source):
        # Worth reading: https://www.asmeurer.com/brown-water-python/
        source = source.encode("utf-8")
        source = io.BytesIO(source)

        try:
            yield from tokenize.tokenize(source.readline)
        except tokenize.TokenError:
            return


class ExceptionFormatter:
    _default_theme = frozenset(
        {
            "introduction": "\x1b[33m\x1b[1m{}\x1b[0m",
            "cause": "\x1b[1m{}\x1b[0m",
            "context": "\x1b[1m{}\x1b[0m",
            "dirname": "\x1b[32m{}\x1b[0m",
            "basename": "\x1b[32m\x1b[1m{}\x1b[0m",
            "line": "\x1b[33m{}\x1b[0m",
            "function": "\x1b[35m{}\x1b[0m",
            "exception_type": "\x1b[31m\x1b[1m{}\x1b[0m",
            "exception_value": "\x1b[1m{}\x1b[0m",
            "arrows": "\x1b[36m{}\x1b[0m",
            "value": "\x1b[36m\x1b[1m{}\x1b[0m",
        }.items()
    )

    def __init__(
        self,
        colorize=False,
        backtrace=False,
        diagnose=True,
        theme=None,
        style=None,
        max_length=128,
        encoding="ascii",
        hidden_frames_filename=None,
        prefix="",
    ):
        self._colorize = colorize
        self._diagnose = diagnose
        self._theme = theme or dict(self._default_theme)
        self._backtrace = backtrace
        self._syntax_highlighter = SyntaxHighlighter(style)
        self._max_length = max_length
        self._encoding = encoding
        self._hidden_frames_filename = hidden_frames_filename
        self._prefix = prefix
        self._lib_dirs = self._get_lib_dirs()
        self._pipe_char = self._get_char("\u2502", "|")
        self._cap_char = self._get_char("\u2514", "->")
        self._catch_point_identifier = " <Loguru catch point here>"

    @staticmethod
    def _get_lib_dirs():
        schemes = sysconfig.get_scheme_names()
        names = ["stdlib", "platstdlib", "platlib", "purelib"]
        paths = {sysconfig.get_path(name, scheme) for scheme in schemes for name in names}
        return [os.path.abspath(path).lower() + os.sep for path in paths if path in sys.path]

    @staticmethod
    def _indent(text, count, *, prefix="| "):
        if count == 0:
            yield text
            return
        for line in text.splitlines(True):
            indented = "  " * count + prefix + line
            yield indented.rstrip() + "\n"

    def _get_char(self, char, default):
        try:
            char.encode(self._encoding)
        except (UnicodeEncodeError, LookupError):
            return default
        else:
            return char

    def _is_file_mine(self, file):
        filepath = os.path.abspath(file).lower()
        if not filepath.endswith(".py"):
            return False
        return not any(filepath.startswith(d) for d in self._lib_dirs)

    def _extract_frames(self, tb, is_first, *, limit=None, from_decorator=False):
        frames, final_source = [], None

        if tb is None or (limit is not None and limit <= 0):
            return frames, final_source

        def is_valid(frame):
            return frame.f_code.co_filename != self._hidden_frames_filename

        def get_info(frame, lineno):
            filename = frame.f_code.co_filename
            function = frame.f_code.co_name
            source = linecache.getline(filename, lineno).strip()
            return filename, lineno, function, source

        infos = []

        if is_valid(tb.tb_frame):
            infos.append((get_info(tb.tb_frame, tb.tb_lineno), tb.tb_frame))

        get_parent_only = from_decorator and not self._backtrace

        if (self._backtrace and is_first) or get_parent_only:
            frame = tb.tb_frame.f_back
            while frame:
                if is_valid(frame):
                    infos.insert(0, (get_info(frame, frame.f_lineno), frame))
                    if get_parent_only:
                        break
                frame = frame.f_back

            if infos and not get_parent_only:
                (filename, lineno, function, source), frame = infos[-1]
                function += self._catch_point_identifier
                infos[-1] = ((filename, lineno, function, source), frame)

        tb = tb.tb_next

        while tb:
            if is_valid(tb.tb_frame):
                infos.append((get_info(tb.tb_frame, tb.tb_lineno), tb.tb_frame))
            tb = tb.tb_next

        if limit is not None:
            infos = infos[-limit:]

        for (filename, lineno, function, source), frame in infos:
            final_source = source
            if source:
                colorize = self._colorize and self._is_file_mine(filename)
                lines = []
                if colorize:
                    lines.append(self._syntax_highlighter.highlight(source))
                else:
                    lines.append(source)
                if self._diagnose:
                    relevant_values = self._get_relevant_values(source, frame)
                    values = self._format_relevant_values(list(relevant_values), colorize)
                    lines += list(values)
                source = "\n    ".join(lines)
            frames.append((filename, lineno, function, source))

        return frames, final_source

    def _get_relevant_values(self, source, frame):
        value = None
        pending = None
        is_attribute = False
        is_valid_value = False
        is_assignment = True

        for token in self._syntax_highlighter.tokenize(source):
            type_, string, (_, col), *_ = token

            if pending is not None:
                # Keyword arguments are ignored
                if type_ != tokenize.OP or string != "=" or is_assignment:
                    yield pending
                pending = None

            if type_ == tokenize.NAME and not keyword.iskeyword(string):
                if not is_attribute:
                    for variables in (frame.f_locals, frame.f_globals):
                        try:
                            value = variables[string]
                        except KeyError:
                            continue
                        else:
                            is_valid_value = True
                            pending = (col, self._format_value(value))
                            break
                elif is_valid_value:
                    try:
                        value = inspect.getattr_static(value, string)
                    except AttributeError:
                        is_valid_value = False
                    else:
                        yield (col, self._format_value(value))
            elif type_ == tokenize.OP and string == ".":
                is_attribute = True
                is_assignment = False
            elif type_ == tokenize.OP and string == ";":
                is_assignment = True
                is_attribute = False
                is_valid_value = False
            else:
                is_attribute = False
                is_valid_value = False
                is_assignment = False

        if pending is not None:
            yield pending

    def _format_relevant_values(self, relevant_values, colorize):
        for i in reversed(range(len(relevant_values))):
            col, value = relevant_values[i]
            pipe_cols = [pcol for pcol, _ in relevant_values[:i]]
            pre_line = ""
            index = 0

            for pc in pipe_cols:
                pre_line += (" " * (pc - index)) + self._pipe_char
                index = pc + 1

            pre_line += " " * (col - index)
            value_lines = value.split("\n")

            for n, value_line in enumerate(value_lines):
                if n == 0:
                    arrows = pre_line + self._cap_char + " "
                else:
                    arrows = pre_line + " " * (len(self._cap_char) + 1)

                if colorize:
                    arrows = self._theme["arrows"].format(arrows)
                    value_line = self._theme["value"].format(value_line)

                yield arrows + value_line

    def _format_value(self, v):
        try:
            v = repr(v)
        except Exception:
            v = "<unprintable %s object>" % type(v).__name__

        max_length = self._max_length
        if max_length is not None and len(v) > max_length:
            v = v[: max_length - 3] + "..."
        return v

    def _format_locations(self, frames_lines, *, has_introduction):
        prepend_with_new_line = has_introduction
        regex = r'^  File "(?P<file>.*?)", line (?P<line>[^,]+)(?:, in (?P<function>.*))?\n'

        for frame in frames_lines:
            match = re.match(regex, frame)

            if match:
                file, line, function = match.group("file", "line", "function")

                is_mine = self._is_file_mine(file)

                if function is not None:
                    pattern = '  File "{}", line {}, in {}\n'
                else:
                    pattern = '  File "{}", line {}\n'

                if self._backtrace and function and function.endswith(self._catch_point_identifier):
                    function = function[: -len(self._catch_point_identifier)]
                    pattern = ">" + pattern[1:]

                if self._colorize and is_mine:
                    dirname, basename = os.path.split(file)
                    if dirname:
                        dirname += os.sep
                    dirname = self._theme["dirname"].format(dirname)
                    basename = self._theme["basename"].format(basename)
                    file = dirname + basename
                    line = self._theme["line"].format(line)
                    function = self._theme["function"].format(function)

                if self._diagnose and (is_mine or prepend_with_new_line):
                    pattern = "\n" + pattern

                location = pattern.format(file, line, function)
                frame = location + frame[match.end() :]
                prepend_with_new_line = is_mine

            yield frame

    def _format_exception(
        self, value, tb, *, seen=None, is_first=False, from_decorator=False, group_nesting=0
    ):
        # Implemented from built-in traceback module:
        # https://github.com/python/cpython/blob/a5b76167/Lib/traceback.py#L468
        exc_type, exc_value, exc_traceback = type(value), value, tb

        if seen is None:
            seen = set()

        seen.add(id(exc_value))

        if exc_value:
            if exc_value.__cause__ is not None and id(exc_value.__cause__) not in seen:
                yield from self._format_exception(
                    exc_value.__cause__,
                    exc_value.__cause__.__traceback__,
                    seen=seen,
                    group_nesting=group_nesting,
                )
                cause = "The above exception was the direct cause of the following exception:"
                if self._colorize:
                    cause = self._theme["cause"].format(cause)
                if self._diagnose:
                    yield from self._indent("\n\n" + cause + "\n\n\n", group_nesting)
                else:
                    yield from self._indent("\n" + cause + "\n\n", group_nesting)

            elif (
                exc_value.__context__ is not None
                and id(exc_value.__context__) not in seen
                and not exc_value.__suppress_context__
            ):
                yield from self._format_exception(
                    exc_value.__context__,
                    exc_value.__context__.__traceback__,
                    seen=seen,
                    group_nesting=group_nesting,
                )
                context = "During handling of the above exception, another exception occurred:"
                if self._colorize:
                    context = self._theme["context"].format(context)
                if self._diagnose:
                    yield from self._indent("\n\n" + context + "\n\n\n", group_nesting)
                else:
                    yield from self._indent("\n" + context + "\n\n", group_nesting)

        is_grouped = is_exception_group(value)

        if is_grouped and group_nesting == 0:
            yield from self._format_exception(
                value,
                tb,
                seen=seen,
                group_nesting=1,
                is_first=is_first,
                from_decorator=from_decorator,
            )
            return

        try:
            traceback_limit = sys.tracebacklimit
        except AttributeError:
            traceback_limit = None

        frames, final_source = self._extract_frames(
            exc_traceback, is_first, limit=traceback_limit, from_decorator=from_decorator
        )
        exception_only = traceback.format_exception_only(exc_type, exc_value)

        # Determining the correct index for the "Exception: message" part in the formatted exception
        # is challenging. This is because it might be preceded by multiple lines specific to
        # "SyntaxError" or followed by various notes. However, we can make an educated guess based
        # on the indentation; the preliminary context for "SyntaxError" is always indented, while
        # the Exception itself is not. This allows us to identify the correct index for the
        # exception message.
        no_indented_indexes = (i for i, p in enumerate(exception_only) if not p.startswith(" "))
        error_message_index = next(no_indented_indexes, None)

        if error_message_index is not None:
            # Remove final new line temporarily.
            error_message = exception_only[error_message_index][:-1]

            if self._colorize:
                if ":" in error_message:
                    exception_type, exception_value = error_message.split(":", 1)
                    exception_type = self._theme["exception_type"].format(exception_type)
                    exception_value = self._theme["exception_value"].format(exception_value)
                    error_message = exception_type + ":" + exception_value
                else:
                    error_message = self._theme["exception_type"].format(error_message)

            if self._diagnose and frames:
                if issubclass(exc_type, AssertionError) and not str(exc_value) and final_source:
                    if self._colorize:
                        final_source = self._syntax_highlighter.highlight(final_source)
                    error_message += ": " + final_source

                error_message = "\n" + error_message

            exception_only[error_message_index] = error_message + "\n"

        if is_first:
            yield self._prefix

        has_introduction = bool(frames)

        if has_introduction:
            if is_grouped:
                introduction = "Exception Group Traceback (most recent call last):"
            else:
                introduction = "Traceback (most recent call last):"
            if self._colorize:
                introduction = self._theme["introduction"].format(introduction)
            if group_nesting == 1:  # Implies we're processing the root ExceptionGroup.
                yield from self._indent(introduction + "\n", group_nesting, prefix="+ ")
            else:
                yield from self._indent(introduction + "\n", group_nesting)

        frames_lines = self._format_list(frames) + exception_only
        if self._colorize or self._backtrace or self._diagnose:
            frames_lines = self._format_locations(frames_lines, has_introduction=has_introduction)

        yield from self._indent("".join(frames_lines), group_nesting)

        if is_grouped:
            exc = None
            for n, exc in enumerate(value.exceptions, start=1):
                ruler = "+" + (" %s " % ("..." if n > 15 else n)).center(35, "-")
                yield from self._indent(ruler, group_nesting, prefix="+-" if n == 1 else "  ")
                if n > 15:
                    message = "and %d more exceptions\n" % (len(value.exceptions) - 15)
                    yield from self._indent(message, group_nesting + 1)
                    break
                elif group_nesting == 10 and is_exception_group(exc):
                    message = "... (max_group_depth is 10)\n"
                    yield from self._indent(message, group_nesting + 1)
                else:
                    yield from self._format_exception(
                        exc,
                        exc.__traceback__,
                        seen=seen,
                        group_nesting=group_nesting + 1,
                    )
            if not is_exception_group(exc) or group_nesting == 10:
                yield from self._indent("-" * 35, group_nesting + 1, prefix="+-")

    def _format_list(self, frames):

        def source_message(filename, lineno, name, line):
            message = '  File "%s", line %d, in %s\n' % (filename, lineno, name)
            if line:
                message += "    %s\n" % line.strip()
            return message

        def skip_message(count):
            plural = "s" if count > 1 else ""
            return "  [Previous line repeated %d more time%s]\n" % (count, plural)

        result = []
        count = 0
        last_source = None

        for *source, line in frames:
            if source != last_source and count > 3:
                result.append(skip_message(count - 3))

            if source == last_source:
                count += 1
                if count > 3:
                    continue
            else:
                count = 1

            result.append(source_message(*source, line))
            last_source = source

        # Add a final skip message if the iteration of frames ended mid-repetition.
        if count > 3:
            result.append(skip_message(count - 3))

        return result

    def format_exception(self, type_, value, tb, *, from_decorator=False):
        yield from self._format_exception(value, tb, is_first=True, from_decorator=from_decorator)
