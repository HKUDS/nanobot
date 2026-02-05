"""
cssselect.parser
================

Tokenizer, parser and parsed objects for CSS selectors.


:copyright: (c) 2007-2012 Ian Bicking and contributors.
See AUTHORS for more details.
:license: BSD, see LICENSE for more details.

"""

from __future__ import annotations

import operator
import re
import sys
from typing import TYPE_CHECKING, Literal, Protocol, TypeAlias, Union, cast, overload

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator, Sequence

    # typing.Self requires Python 3.11
    from typing_extensions import Self


def ascii_lower(string: str) -> str:
    """Lower-case, but only in the ASCII range."""
    return string.encode("utf8").lower().decode("utf8")


class SelectorError(Exception):
    """Common parent for :class:`SelectorSyntaxError` and
    :class:`ExpressionError`.

    You can just use ``except SelectorError:`` when calling
    :meth:`~GenericTranslator.css_to_xpath` and handle both exceptions types.

    """


class SelectorSyntaxError(SelectorError, SyntaxError):
    """Parsing a selector that does not match the grammar."""


#### Parsed objects

Tree: TypeAlias = Union[
    "Element",
    "Hash",
    "Class",
    "Function",
    "Pseudo",
    "Attrib",
    "Negation",
    "Relation",
    "Matching",
    "SpecificityAdjustment",
    "CombinedSelector",
]
PseudoElement: TypeAlias = Union["FunctionalPseudoElement", str]


class Selector:
    """
    Represents a parsed selector.

    :meth:`~GenericTranslator.selector_to_xpath` accepts this object,
    but ignores :attr:`pseudo_element`. It is the user’s responsibility
    to account for pseudo-elements and reject selectors with unknown
    or unsupported pseudo-elements.

    """

    def __init__(self, tree: Tree, pseudo_element: PseudoElement | None = None) -> None:
        self.parsed_tree = tree
        if pseudo_element is not None and not isinstance(
            pseudo_element, FunctionalPseudoElement
        ):
            pseudo_element = ascii_lower(pseudo_element)
        #: A :class:`FunctionalPseudoElement`,
        #: or the identifier for the pseudo-element as a string,
        #  or ``None``.
        #:
        #: +-------------------------+----------------+--------------------------------+
        #: |                         | Selector       | Pseudo-element                 |
        #: +=========================+================+================================+
        #: | CSS3 syntax             | ``a::before``  | ``'before'``                   |
        #: +-------------------------+----------------+--------------------------------+
        #: | Older syntax            | ``a:before``   | ``'before'``                   |
        #: +-------------------------+----------------+--------------------------------+
        #: | From the Lists3_ draft, | ``li::marker`` | ``'marker'``                   |
        #: | not in Selectors3       |                |                                |
        #: +-------------------------+----------------+--------------------------------+
        #: | Invalid pseudo-class    | ``li:marker``  | ``None``                       |
        #: +-------------------------+----------------+--------------------------------+
        #: | Functional              | ``a::foo(2)``  | ``FunctionalPseudoElement(…)`` |
        #: +-------------------------+----------------+--------------------------------+
        #:
        #: .. _Lists3: http://www.w3.org/TR/2011/WD-css3-lists-20110524/#marker-pseudoelement
        self.pseudo_element = pseudo_element

    def __repr__(self) -> str:
        if isinstance(self.pseudo_element, FunctionalPseudoElement):
            pseudo_element = repr(self.pseudo_element)
        elif self.pseudo_element:
            pseudo_element = f"::{self.pseudo_element}"
        else:
            pseudo_element = ""
        return f"{self.__class__.__name__}[{self.parsed_tree!r}{pseudo_element}]"

    def canonical(self) -> str:
        """Return a CSS representation for this selector (a string)"""
        if isinstance(self.pseudo_element, FunctionalPseudoElement):
            pseudo_element = f"::{self.pseudo_element.canonical()}"
        elif self.pseudo_element:
            pseudo_element = f"::{self.pseudo_element}"
        else:
            pseudo_element = ""
        res = f"{self.parsed_tree.canonical()}{pseudo_element}"
        if len(res) > 1:
            res = res.lstrip("*")
        return res

    def specificity(self) -> tuple[int, int, int]:
        """Return the specificity_ of this selector as a tuple of 3 integers.

        .. _specificity: http://www.w3.org/TR/selectors/#specificity

        """
        a, b, c = self.parsed_tree.specificity()
        if self.pseudo_element:
            c += 1
        return a, b, c


class Class:
    """
    Represents selector.class_name
    """

    def __init__(self, selector: Tree, class_name: str) -> None:
        self.selector = selector
        self.class_name = class_name

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}[{self.selector!r}.{self.class_name}]"

    def canonical(self) -> str:
        return f"{self.selector.canonical()}.{self.class_name}"

    def specificity(self) -> tuple[int, int, int]:
        a, b, c = self.selector.specificity()
        b += 1
        return a, b, c


class FunctionalPseudoElement:
    """
    Represents selector::name(arguments)

    .. attribute:: name

        The name (identifier) of the pseudo-element, as a string.

    .. attribute:: arguments

        The arguments of the pseudo-element, as a list of tokens.

        **Note:** tokens are not part of the public API,
        and may change between cssselect versions.
        Use at your own risks.

    """

    def __init__(self, name: str, arguments: Sequence[Token]):
        self.name = ascii_lower(name)
        self.arguments = arguments

    def __repr__(self) -> str:
        token_values = [token.value for token in self.arguments]
        return f"{self.__class__.__name__}[::{self.name}({token_values!r})]"

    def argument_types(self) -> list[str]:
        return [token.type for token in self.arguments]

    def canonical(self) -> str:
        args = "".join(token.css() for token in self.arguments)
        return f"{self.name}({args})"


class Function:
    """
    Represents selector:name(expr)
    """

    def __init__(self, selector: Tree, name: str, arguments: Sequence[Token]) -> None:
        self.selector = selector
        self.name = ascii_lower(name)
        self.arguments = arguments

    def __repr__(self) -> str:
        token_values = [token.value for token in self.arguments]
        return f"{self.__class__.__name__}[{self.selector!r}:{self.name}({token_values!r})]"

    def argument_types(self) -> list[str]:
        return [token.type for token in self.arguments]

    def canonical(self) -> str:
        args = "".join(token.css() for token in self.arguments)
        return f"{self.selector.canonical()}:{self.name}({args})"

    def specificity(self) -> tuple[int, int, int]:
        a, b, c = self.selector.specificity()
        b += 1
        return a, b, c


class Pseudo:
    """
    Represents selector:ident
    """

    def __init__(self, selector: Tree, ident: str) -> None:
        self.selector = selector
        self.ident = ascii_lower(ident)

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}[{self.selector!r}:{self.ident}]"

    def canonical(self) -> str:
        return f"{self.selector.canonical()}:{self.ident}"

    def specificity(self) -> tuple[int, int, int]:
        a, b, c = self.selector.specificity()
        b += 1
        return a, b, c


class Negation:
    """
    Represents selector:not(subselector)
    """

    def __init__(self, selector: Tree, subselector: Tree) -> None:
        self.selector = selector
        self.subselector = subselector

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}[{self.selector!r}:not({self.subselector!r})]"

    def canonical(self) -> str:
        subsel = self.subselector.canonical()
        if len(subsel) > 1:
            subsel = subsel.lstrip("*")
        return f"{self.selector.canonical()}:not({subsel})"

    def specificity(self) -> tuple[int, int, int]:
        a1, b1, c1 = self.selector.specificity()
        a2, b2, c2 = self.subselector.specificity()
        return a1 + a2, b1 + b2, c1 + c2


class Relation:
    """
    Represents selector:has(subselector)
    """

    def __init__(self, selector: Tree, combinator: Token, subselector: Selector):
        self.selector = selector
        self.combinator = combinator
        self.subselector = subselector

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}[{self.selector!r}:has({self.subselector!r})]"

    def canonical(self) -> str:
        try:
            subsel = self.subselector[0].canonical()  # type: ignore[index]
        except TypeError:
            subsel = self.subselector.canonical()
        if len(subsel) > 1:
            subsel = subsel.lstrip("*")
        return f"{self.selector.canonical()}:has({subsel})"

    def specificity(self) -> tuple[int, int, int]:
        a1, b1, c1 = self.selector.specificity()
        try:
            a2, b2, c2 = self.subselector[-1].specificity()  # type: ignore[index]
        except TypeError:
            a2, b2, c2 = self.subselector.specificity()
        return a1 + a2, b1 + b2, c1 + c2


class Matching:
    """
    Represents selector:is(selector_list)
    """

    def __init__(self, selector: Tree, selector_list: Iterable[Tree]):
        self.selector = selector
        self.selector_list = selector_list

    def __repr__(self) -> str:
        args_str = ", ".join(repr(s) for s in self.selector_list)
        return f"{self.__class__.__name__}[{self.selector!r}:is({args_str})]"

    def canonical(self) -> str:
        selector_arguments = []
        for s in self.selector_list:
            selarg = s.canonical()
            selector_arguments.append(selarg.lstrip("*"))
        args_str = ", ".join(str(s) for s in selector_arguments)
        return f"{self.selector.canonical()}:is({args_str})"

    def specificity(self) -> tuple[int, int, int]:
        return max(x.specificity() for x in self.selector_list)


class SpecificityAdjustment:
    """
    Represents selector:where(selector_list)
    Same as selector:is(selector_list), but its specificity is always 0
    """

    def __init__(self, selector: Tree, selector_list: list[Tree]):
        self.selector = selector
        self.selector_list = selector_list

    def __repr__(self) -> str:
        args_str = ", ".join(repr(s) for s in self.selector_list)
        return f"{self.__class__.__name__}[{self.selector!r}:where({args_str})]"

    def canonical(self) -> str:
        selector_arguments = []
        for s in self.selector_list:
            selarg = s.canonical()
            selector_arguments.append(selarg.lstrip("*"))
        args_str = ", ".join(str(s) for s in selector_arguments)
        return f"{self.selector.canonical()}:where({args_str})"

    def specificity(self) -> tuple[int, int, int]:
        return 0, 0, 0


class Attrib:
    """
    Represents selector[namespace|attrib operator value]
    """

    @overload
    def __init__(
        self,
        selector: Tree,
        namespace: str | None,
        attrib: str,
        operator: Literal["exists"],
        value: None,
    ) -> None: ...

    @overload
    def __init__(
        self,
        selector: Tree,
        namespace: str | None,
        attrib: str,
        operator: str,
        value: Token,
    ) -> None: ...

    def __init__(
        self,
        selector: Tree,
        namespace: str | None,
        attrib: str,
        operator: str,
        value: Token | None,
    ) -> None:
        self.selector = selector
        self.namespace = namespace
        self.attrib = attrib
        self.operator = operator
        self.value = value

    def __repr__(self) -> str:
        attrib = f"{self.namespace}|{self.attrib}" if self.namespace else self.attrib
        if self.operator == "exists":
            return f"{self.__class__.__name__}[{self.selector!r}[{attrib}]]"
        assert self.value is not None
        return f"{self.__class__.__name__}[{self.selector!r}[{attrib} {self.operator} {self.value.value!r}]]"

    def canonical(self) -> str:
        attrib = f"{self.namespace}|{self.attrib}" if self.namespace else self.attrib

        if self.operator == "exists":
            op = attrib
        else:
            assert self.value is not None
            op = f"{attrib}{self.operator}{self.value.css()}"

        return f"{self.selector.canonical()}[{op}]"

    def specificity(self) -> tuple[int, int, int]:
        a, b, c = self.selector.specificity()
        b += 1
        return a, b, c


class Element:
    """
    Represents namespace|element

    `None` is for the universal selector '*'

    """

    def __init__(
        self, namespace: str | None = None, element: str | None = None
    ) -> None:
        self.namespace = namespace
        self.element = element

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}[{self.canonical()}]"

    def canonical(self) -> str:
        element = self.element or "*"
        if self.namespace:
            element = f"{self.namespace}|{element}"
        return element

    def specificity(self) -> tuple[int, int, int]:
        if self.element:
            return 0, 0, 1
        return 0, 0, 0


class Hash:
    """
    Represents selector#id
    """

    def __init__(self, selector: Tree, id: str) -> None:  # noqa: A002
        self.selector = selector
        self.id = id

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}[{self.selector!r}#{self.id}]"

    def canonical(self) -> str:
        return f"{self.selector.canonical()}#{self.id}"

    def specificity(self) -> tuple[int, int, int]:
        a, b, c = self.selector.specificity()
        a += 1
        return a, b, c


class CombinedSelector:
    def __init__(self, selector: Tree, combinator: str, subselector: Tree) -> None:
        assert selector is not None
        self.selector = selector
        self.combinator = combinator
        self.subselector = subselector

    def __repr__(self) -> str:
        comb = "<followed>" if self.combinator == " " else self.combinator
        return (
            f"{self.__class__.__name__}[{self.selector!r} {comb} {self.subselector!r}]"
        )

    def canonical(self) -> str:
        subsel = self.subselector.canonical()
        if len(subsel) > 1:
            subsel = subsel.lstrip("*")
        return f"{self.selector.canonical()} {self.combinator} {subsel}"

    def specificity(self) -> tuple[int, int, int]:
        a1, b1, c1 = self.selector.specificity()
        a2, b2, c2 = self.subselector.specificity()
        return a1 + a2, b1 + b2, c1 + c2


#### Parser

# foo
_el_re = re.compile(r"^[ \t\r\n\f]*([a-zA-Z]+)[ \t\r\n\f]*$")

# foo#bar or #bar
_id_re = re.compile(r"^[ \t\r\n\f]*([a-zA-Z]*)#([a-zA-Z0-9_-]+)[ \t\r\n\f]*$")

# foo.bar or .bar
_class_re = re.compile(
    r"^[ \t\r\n\f]*([a-zA-Z]*)\.([a-zA-Z][a-zA-Z0-9_-]*)[ \t\r\n\f]*$"
)


def parse(css: str) -> list[Selector]:
    """Parse a CSS *group of selectors*.

    If you don't care about pseudo-elements or selector specificity,
    you can skip this and use :meth:`~GenericTranslator.css_to_xpath`.

    :param css:
        A *group of selectors* as a string.
    :raises:
        :class:`SelectorSyntaxError` on invalid selectors.
    :returns:
        A list of parsed :class:`Selector` objects, one for each
        selector in the comma-separated group.

    """
    # Fast path for simple cases
    match = _el_re.match(css)
    if match:
        return [Selector(Element(element=match.group(1)))]
    match = _id_re.match(css)
    if match is not None:
        return [Selector(Hash(Element(element=match.group(1) or None), match.group(2)))]
    match = _class_re.match(css)
    if match is not None:
        return [
            Selector(Class(Element(element=match.group(1) or None), match.group(2)))
        ]

    stream = TokenStream(tokenize(css))
    stream.source = css
    return list(parse_selector_group(stream))


#    except SelectorSyntaxError:
#        e = sys.exc_info()[1]
#        message = "%s at %s -> %r" % (
#            e, stream.used, stream.peek())
#        e.msg = message
#        e.args = tuple([message])
#        raise


def parse_selector_group(stream: TokenStream) -> Iterator[Selector]:
    stream.skip_whitespace()
    while 1:
        yield Selector(*parse_selector(stream))
        if stream.peek() == ("DELIM", ","):
            stream.next()
            stream.skip_whitespace()
        else:
            break


def parse_selector(stream: TokenStream) -> tuple[Tree, PseudoElement | None]:
    result, pseudo_element = parse_simple_selector(stream)
    while 1:
        stream.skip_whitespace()
        peek = stream.peek()
        if peek in (("EOF", None), ("DELIM", ",")):
            break
        if pseudo_element:
            raise SelectorSyntaxError(
                f"Got pseudo-element ::{pseudo_element} not at the end of a selector"
            )
        if peek.is_delim("+", ">", "~"):
            # A combinator
            combinator = cast("str", stream.next().value)
            stream.skip_whitespace()
        else:
            # By exclusion, the last parse_simple_selector() ended
            # at peek == ' '
            combinator = " "
        next_selector, pseudo_element = parse_simple_selector(stream)
        result = CombinedSelector(result, combinator, next_selector)
    return result, pseudo_element


def parse_simple_selector(
    stream: TokenStream, inside_negation: bool = False
) -> tuple[Tree, PseudoElement | None]:
    stream.skip_whitespace()
    selector_start = len(stream.used)
    peek = stream.peek()
    if peek.type == "IDENT" or peek == ("DELIM", "*"):
        if peek.type == "IDENT":
            namespace = stream.next().value
        else:
            stream.next()
            namespace = None
        if stream.peek() == ("DELIM", "|"):
            stream.next()
            element = stream.next_ident_or_star()
        else:
            element = namespace
            namespace = None
    else:
        element = namespace = None
    result: Tree = Element(namespace, element)
    pseudo_element: PseudoElement | None = None
    while 1:
        peek = stream.peek()
        if (
            peek.type in ("S", "EOF")
            or peek.is_delim(",", "+", ">", "~")
            or (inside_negation and peek == ("DELIM", ")"))
        ):
            break
        if pseudo_element:
            raise SelectorSyntaxError(
                f"Got pseudo-element ::{pseudo_element} not at the end of a selector"
            )
        if peek.type == "HASH":
            result = Hash(result, cast("str", stream.next().value))
        elif peek == ("DELIM", "."):
            stream.next()
            result = Class(result, stream.next_ident())
        elif peek == ("DELIM", "|"):
            stream.next()
            result = Element(None, stream.next_ident())
        elif peek == ("DELIM", "["):
            stream.next()
            result = parse_attrib(result, stream)
        elif peek == ("DELIM", ":"):
            stream.next()
            if stream.peek() == ("DELIM", ":"):
                stream.next()
                pseudo_element = stream.next_ident()
                if stream.peek() == ("DELIM", "("):
                    stream.next()
                    pseudo_element = FunctionalPseudoElement(
                        pseudo_element, parse_arguments(stream)
                    )
                continue
            ident = stream.next_ident()
            if ident.lower() in ("first-line", "first-letter", "before", "after"):
                # Special case: CSS 2.1 pseudo-elements can have a single ':'
                # Any new pseudo-element must have two.
                pseudo_element = str(ident)
                continue
            if stream.peek() != ("DELIM", "("):
                result = Pseudo(result, ident)
                if repr(result) == "Pseudo[Element[*]:scope]" and not (
                    len(stream.used) == 2
                    or (len(stream.used) == 3 and stream.used[0].type == "S")
                    or (len(stream.used) >= 3 and stream.used[-3].is_delim(","))
                    or (
                        len(stream.used) >= 4
                        and stream.used[-3].type == "S"
                        and stream.used[-4].is_delim(",")
                    )
                ):
                    raise SelectorSyntaxError(
                        'Got immediate child pseudo-element ":scope" '
                        "not at the start of a selector"
                    )
                continue
            stream.next()
            stream.skip_whitespace()
            if ident.lower() == "not":
                if inside_negation:
                    raise SelectorSyntaxError("Got nested :not()")
                argument, argument_pseudo_element = parse_simple_selector(
                    stream, inside_negation=True
                )
                next_ = stream.next()
                if argument_pseudo_element:
                    raise SelectorSyntaxError(
                        f"Got pseudo-element ::{argument_pseudo_element} inside :not() at {next_.pos}"
                    )
                if next_ != ("DELIM", ")"):
                    raise SelectorSyntaxError(f"Expected ')', got {next_}")
                result = Negation(result, argument)
            elif ident.lower() == "has":
                combinator, arguments = parse_relative_selector(stream)
                result = Relation(result, combinator, arguments)

            elif ident.lower() in ("matches", "is"):
                selectors = parse_simple_selector_arguments(stream)
                result = Matching(result, selectors)
            elif ident.lower() == "where":
                selectors = parse_simple_selector_arguments(stream)
                result = SpecificityAdjustment(result, selectors)
            else:
                result = Function(result, ident, parse_arguments(stream))
        else:
            raise SelectorSyntaxError(f"Expected selector, got {peek}")
    if len(stream.used) == selector_start:
        raise SelectorSyntaxError(f"Expected selector, got {stream.peek()}")
    return result, pseudo_element


def parse_arguments(stream: TokenStream) -> list[Token]:  # noqa: RET503
    arguments: list[Token] = []
    while 1:
        stream.skip_whitespace()
        next_ = stream.next()
        if next_.type in ("IDENT", "STRING", "NUMBER") or next_ in [
            ("DELIM", "+"),
            ("DELIM", "-"),
        ]:
            arguments.append(next_)
        elif next_ == ("DELIM", ")"):
            return arguments
        else:
            raise SelectorSyntaxError(f"Expected an argument, got {next_}")


def parse_relative_selector(stream: TokenStream) -> tuple[Token, Selector]:  # noqa: RET503
    stream.skip_whitespace()
    subselector = ""
    next_ = stream.next()

    if next_ in [("DELIM", "+"), ("DELIM", "-"), ("DELIM", ">"), ("DELIM", "~")]:
        combinator = next_
        stream.skip_whitespace()
        next_ = stream.next()
    else:
        combinator = Token("DELIM", " ", pos=0)

    while 1:
        if next_.type in ("IDENT", "STRING", "NUMBER") or next_ in [
            ("DELIM", "."),
            ("DELIM", "*"),
        ]:
            subselector += cast("str", next_.value)
        elif next_ == ("DELIM", ")"):
            result = parse(subselector)
            return combinator, result[0]
        else:
            raise SelectorSyntaxError(f"Expected an argument, got {next_}")
        next_ = stream.next()


def parse_simple_selector_arguments(stream: TokenStream) -> list[Tree]:
    arguments = []
    while 1:
        result, pseudo_element = parse_simple_selector(stream, True)
        if pseudo_element:
            raise SelectorSyntaxError(
                f"Got pseudo-element ::{pseudo_element} inside function"
            )
        stream.skip_whitespace()
        next_ = stream.next()
        if next_ in (("EOF", None), ("DELIM", ",")):
            stream.next()
            stream.skip_whitespace()
            arguments.append(result)
        elif next_ == ("DELIM", ")"):
            arguments.append(result)
            break
        else:
            raise SelectorSyntaxError(f"Expected an argument, got {next_}")
    return arguments


def parse_attrib(selector: Tree, stream: TokenStream) -> Attrib:
    stream.skip_whitespace()
    attrib = stream.next_ident_or_star()
    if attrib is None and stream.peek() != ("DELIM", "|"):
        raise SelectorSyntaxError(f"Expected '|', got {stream.peek()}")
    namespace: str | None
    op: str | None
    if stream.peek() == ("DELIM", "|"):
        stream.next()
        if stream.peek() == ("DELIM", "="):
            namespace = None
            stream.next()
            op = "|="
        else:
            namespace = attrib
            attrib = stream.next_ident()
            op = None
    else:
        namespace = op = None
    if op is None:
        stream.skip_whitespace()
        next_ = stream.next()
        if next_ == ("DELIM", "]"):
            return Attrib(selector, namespace, cast("str", attrib), "exists", None)
        if next_ == ("DELIM", "="):
            op = "="
        elif next_.is_delim("^", "$", "*", "~", "|", "!") and (
            stream.peek() == ("DELIM", "=")
        ):
            op = cast("str", next_.value) + "="
            stream.next()
        else:
            raise SelectorSyntaxError(f"Operator expected, got {next_}")
    stream.skip_whitespace()
    value = stream.next()
    if value.type not in ("IDENT", "STRING"):
        raise SelectorSyntaxError(f"Expected string or ident, got {value}")
    stream.skip_whitespace()
    next_ = stream.next()
    if next_ != ("DELIM", "]"):
        raise SelectorSyntaxError(f"Expected ']', got {next_}")
    return Attrib(selector, namespace, cast("str", attrib), op, value)


def parse_series(tokens: Iterable[Token]) -> tuple[int, int]:
    """
    Parses the arguments for :nth-child() and friends.

    :raises: A list of tokens
    :returns: :``(a, b)``

    """
    for token in tokens:
        if token.type == "STRING":
            raise ValueError("String tokens not allowed in series.")
    s = "".join(cast("str", token.value) for token in tokens).strip()
    if s == "odd":
        return 2, 1
    if s == "even":
        return 2, 0
    if s == "n":
        return 1, 0
    if "n" not in s:
        # Just b
        return 0, int(s)
    a, b = s.split("n", 1)
    a_as_int: int
    if not a:
        a_as_int = 1
    elif a in {"-", "+"}:
        a_as_int = int(a + "1")
    else:
        a_as_int = int(a)
    b_as_int = int(b) if b else 0
    return a_as_int, b_as_int


#### Token objects


class Token(tuple[str, str | None]):  # noqa: SLOT001
    @overload
    def __new__(
        cls,
        type_: Literal["IDENT", "HASH", "STRING", "S", "DELIM", "NUMBER"],
        value: str,
        pos: int,
    ) -> Self: ...

    @overload
    def __new__(cls, type_: Literal["EOF"], value: None, pos: int) -> Self: ...

    def __new__(cls, type_: str, value: str | None, pos: int) -> Self:
        obj = tuple.__new__(cls, (type_, value))
        obj.pos = pos
        return obj

    def __repr__(self) -> str:
        return f"<{self.type} '{self.value}' at {self.pos}>"

    def is_delim(self, *values: str) -> bool:
        return self.type == "DELIM" and self.value in values

    pos: int

    @property
    def type(self) -> str:
        return self[0]

    @property
    def value(self) -> str | None:
        return self[1]

    def css(self) -> str:
        if self.type == "STRING":
            return repr(self.value)
        return cast("str", self.value)


class EOFToken(Token):
    def __new__(cls, pos: int) -> Self:
        return Token.__new__(cls, "EOF", None, pos)

    def __repr__(self) -> str:
        return f"<{self.type} at {self.pos}>"


#### Tokenizer


class TokenMacros:
    unicode_escape = r"\\([0-9a-f]{1,6})(?:\r\n|[ \n\r\t\f])?"
    escape = unicode_escape + r"|\\[^\n\r\f0-9a-f]"
    string_escape = r"\\(?:\n|\r\n|\r|\f)|" + escape
    nonascii = r"[^\0-\177]"
    nmchar = f"[_a-z0-9-]|{escape}|{nonascii}"
    nmstart = f"[_a-z]|{escape}|{nonascii}"


class MatchFunc(Protocol):
    def __call__(
        self, string: str, pos: int = ..., endpos: int = ...
    ) -> re.Match[str] | None: ...


def _compile(pattern: str) -> MatchFunc:
    return re.compile(pattern % vars(TokenMacros), re.IGNORECASE).match


_match_whitespace = _compile(r"[ \t\r\n\f]+")
_match_number = _compile(r"[+-]?(?:[0-9]*\.[0-9]+|[0-9]+)")
_match_hash = _compile("#(?:%(nmchar)s)+")
_match_ident = _compile("-?(?:%(nmstart)s)(?:%(nmchar)s)*")
_match_string_by_quote = {
    "'": _compile(r"([^\n\r\f\\']|%(string_escape)s)*"),
    '"': _compile(r'([^\n\r\f\\"]|%(string_escape)s)*'),
}

_sub_simple_escape = re.compile(r"\\(.)").sub
_sub_unicode_escape = re.compile(TokenMacros.unicode_escape, re.IGNORECASE).sub
_sub_newline_escape = re.compile(r"\\(?:\n|\r\n|\r|\f)").sub

# Same as r'\1', but faster on CPython
_replace_simple = operator.methodcaller("group", 1)


def _replace_unicode(match: re.Match[str]) -> str:
    codepoint = int(match.group(1), 16)
    if codepoint > sys.maxunicode:
        codepoint = 0xFFFD
    return chr(codepoint)


def unescape_ident(value: str) -> str:
    value = _sub_unicode_escape(_replace_unicode, value)
    return _sub_simple_escape(_replace_simple, value)


def tokenize(s: str) -> Iterator[Token]:
    pos = 0
    len_s = len(s)
    while pos < len_s:
        match = _match_whitespace(s, pos=pos)
        if match:
            yield Token("S", " ", pos)
            pos = match.end()
            continue

        match = _match_ident(s, pos=pos)
        if match:
            value = _sub_simple_escape(
                _replace_simple, _sub_unicode_escape(_replace_unicode, match.group())
            )
            yield Token("IDENT", value, pos)
            pos = match.end()
            continue

        match = _match_hash(s, pos=pos)
        if match:
            value = _sub_simple_escape(
                _replace_simple,
                _sub_unicode_escape(_replace_unicode, match.group()[1:]),
            )
            yield Token("HASH", value, pos)
            pos = match.end()
            continue

        quote = s[pos]
        if quote in _match_string_by_quote:
            match = _match_string_by_quote[quote](s, pos=pos + 1)
            assert match, "Should have found at least an empty match"
            end_pos = match.end()
            if end_pos == len_s:
                raise SelectorSyntaxError(f"Unclosed string at {pos}")
            if s[end_pos] != quote:
                raise SelectorSyntaxError(f"Invalid string at {pos}")
            value = _sub_simple_escape(
                _replace_simple,
                _sub_unicode_escape(
                    _replace_unicode, _sub_newline_escape("", match.group())
                ),
            )
            yield Token("STRING", value, pos)
            pos = end_pos + 1
            continue

        match = _match_number(s, pos=pos)
        if match:
            value = match.group()
            yield Token("NUMBER", value, pos)
            pos = match.end()
            continue

        pos2 = pos + 2
        if s[pos:pos2] == "/*":
            pos = s.find("*/", pos2)
            if pos == -1:
                pos = len_s
            else:
                pos += 2
            continue

        yield Token("DELIM", s[pos], pos)
        pos += 1

    assert pos == len_s
    yield EOFToken(pos)


class TokenStream:
    def __init__(self, tokens: Iterable[Token], source: str | None = None) -> None:
        self.used: list[Token] = []
        self.tokens = iter(tokens)
        self.source = source
        self.peeked: Token | None = None
        self._peeking = False
        self.next_token = self.tokens.__next__

    def next(self) -> Token:
        if self._peeking:
            self._peeking = False
            assert self.peeked is not None
            self.used.append(self.peeked)
            return self.peeked
        next_ = self.next_token()
        self.used.append(next_)
        return next_

    def peek(self) -> Token:
        if not self._peeking:
            self.peeked = self.next_token()
            self._peeking = True
        assert self.peeked is not None
        return self.peeked

    def next_ident(self) -> str:
        next_ = self.next()
        if next_.type != "IDENT":
            raise SelectorSyntaxError(f"Expected ident, got {next_}")
        return cast("str", next_.value)

    def next_ident_or_star(self) -> str | None:
        next_ = self.next()
        if next_.type == "IDENT":
            return next_.value
        if next_ == ("DELIM", "*"):
            return None
        raise SelectorSyntaxError(f"Expected ident or '*', got {next_}")

    def skip_whitespace(self) -> None:
        peek = self.peek()
        if peek.type == "S":
            self.next()
