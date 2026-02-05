# Generated content DO NOT EDIT
class Normalizer:
    """
    Base class for all normalizers

    This class is not supposed to be instantiated directly. Instead, any implementation of a
    Normalizer will return an instance of this class when instantiated.
    """
    def __getstate__(self):
        """ """
        pass

    def __setstate__(self, state):
        """ """
        pass

    @staticmethod
    def custom(normalizer):
        """ """
        pass

    def normalize(self, normalized):
        """
        Normalize a :class:`~tokenizers.NormalizedString` in-place

        This method allows to modify a :class:`~tokenizers.NormalizedString` to
        keep track of the alignment information. If you just want to see the result
        of the normalization on a raw string, you can use
        :meth:`~tokenizers.normalizers.Normalizer.normalize_str`

        Args:
            normalized (:class:`~tokenizers.NormalizedString`):
                The normalized string on which to apply this
                :class:`~tokenizers.normalizers.Normalizer`
        """
        pass

    def normalize_str(self, sequence):
        """
        Normalize the given string

        This method provides a way to visualize the effect of a
        :class:`~tokenizers.normalizers.Normalizer` but it does not keep track of the alignment
        information. If you need to get/convert offsets, you can use
        :meth:`~tokenizers.normalizers.Normalizer.normalize`

        Args:
            sequence (:obj:`str`):
                A string to normalize

        Returns:
            :obj:`str`: A string after normalization
        """
        pass

class BertNormalizer(Normalizer):
    """
    BertNormalizer

    Takes care of normalizing raw text before giving it to a Bert model.
    This includes cleaning the text, handling accents, chinese chars and lowercasing

    Args:
        clean_text (:obj:`bool`, `optional`, defaults to :obj:`True`):
            Whether to clean the text, by removing any control characters
            and replacing all whitespaces by the classic one.

        handle_chinese_chars (:obj:`bool`, `optional`, defaults to :obj:`True`):
            Whether to handle chinese chars by putting spaces around them.

        strip_accents (:obj:`bool`, `optional`):
            Whether to strip all accents. If this option is not specified (ie == None),
            then it will be determined by the value for `lowercase` (as in the original Bert).

        lowercase (:obj:`bool`, `optional`, defaults to :obj:`True`):
            Whether to lowercase.
    """
    def __init__(self, clean_text=True, handle_chinese_chars=True, strip_accents=None, lowercase=True):
        pass

    def __getstate__(self):
        """ """
        pass

    def __setstate__(self, state):
        """ """
        pass

    @property
    def clean_text(self):
        """ """
        pass

    @clean_text.setter
    def clean_text(self, value):
        """ """
        pass

    @staticmethod
    def custom(normalizer):
        """ """
        pass

    @property
    def handle_chinese_chars(self):
        """ """
        pass

    @handle_chinese_chars.setter
    def handle_chinese_chars(self, value):
        """ """
        pass

    @property
    def lowercase(self):
        """ """
        pass

    @lowercase.setter
    def lowercase(self, value):
        """ """
        pass

    def normalize(self, normalized):
        """
        Normalize a :class:`~tokenizers.NormalizedString` in-place

        This method allows to modify a :class:`~tokenizers.NormalizedString` to
        keep track of the alignment information. If you just want to see the result
        of the normalization on a raw string, you can use
        :meth:`~tokenizers.normalizers.Normalizer.normalize_str`

        Args:
            normalized (:class:`~tokenizers.NormalizedString`):
                The normalized string on which to apply this
                :class:`~tokenizers.normalizers.Normalizer`
        """
        pass

    def normalize_str(self, sequence):
        """
        Normalize the given string

        This method provides a way to visualize the effect of a
        :class:`~tokenizers.normalizers.Normalizer` but it does not keep track of the alignment
        information. If you need to get/convert offsets, you can use
        :meth:`~tokenizers.normalizers.Normalizer.normalize`

        Args:
            sequence (:obj:`str`):
                A string to normalize

        Returns:
            :obj:`str`: A string after normalization
        """
        pass

    @property
    def strip_accents(self):
        """ """
        pass

    @strip_accents.setter
    def strip_accents(self, value):
        """ """
        pass

class ByteLevel(Normalizer):
    """
    Bytelevel Normalizer
    """
    def __init__(self):
        pass

    def __getstate__(self):
        """ """
        pass

    def __setstate__(self, state):
        """ """
        pass

    @staticmethod
    def custom(normalizer):
        """ """
        pass

    def normalize(self, normalized):
        """
        Normalize a :class:`~tokenizers.NormalizedString` in-place

        This method allows to modify a :class:`~tokenizers.NormalizedString` to
        keep track of the alignment information. If you just want to see the result
        of the normalization on a raw string, you can use
        :meth:`~tokenizers.normalizers.Normalizer.normalize_str`

        Args:
            normalized (:class:`~tokenizers.NormalizedString`):
                The normalized string on which to apply this
                :class:`~tokenizers.normalizers.Normalizer`
        """
        pass

    def normalize_str(self, sequence):
        """
        Normalize the given string

        This method provides a way to visualize the effect of a
        :class:`~tokenizers.normalizers.Normalizer` but it does not keep track of the alignment
        information. If you need to get/convert offsets, you can use
        :meth:`~tokenizers.normalizers.Normalizer.normalize`

        Args:
            sequence (:obj:`str`):
                A string to normalize

        Returns:
            :obj:`str`: A string after normalization
        """
        pass

class Lowercase(Normalizer):
    """
    Lowercase Normalizer
    """
    def __init__(self):
        pass

    def __getstate__(self):
        """ """
        pass

    def __setstate__(self, state):
        """ """
        pass

    @staticmethod
    def custom(normalizer):
        """ """
        pass

    def normalize(self, normalized):
        """
        Normalize a :class:`~tokenizers.NormalizedString` in-place

        This method allows to modify a :class:`~tokenizers.NormalizedString` to
        keep track of the alignment information. If you just want to see the result
        of the normalization on a raw string, you can use
        :meth:`~tokenizers.normalizers.Normalizer.normalize_str`

        Args:
            normalized (:class:`~tokenizers.NormalizedString`):
                The normalized string on which to apply this
                :class:`~tokenizers.normalizers.Normalizer`
        """
        pass

    def normalize_str(self, sequence):
        """
        Normalize the given string

        This method provides a way to visualize the effect of a
        :class:`~tokenizers.normalizers.Normalizer` but it does not keep track of the alignment
        information. If you need to get/convert offsets, you can use
        :meth:`~tokenizers.normalizers.Normalizer.normalize`

        Args:
            sequence (:obj:`str`):
                A string to normalize

        Returns:
            :obj:`str`: A string after normalization
        """
        pass

class NFC(Normalizer):
    """
    NFC Unicode Normalizer
    """
    def __init__(self):
        pass

    def __getstate__(self):
        """ """
        pass

    def __setstate__(self, state):
        """ """
        pass

    @staticmethod
    def custom(normalizer):
        """ """
        pass

    def normalize(self, normalized):
        """
        Normalize a :class:`~tokenizers.NormalizedString` in-place

        This method allows to modify a :class:`~tokenizers.NormalizedString` to
        keep track of the alignment information. If you just want to see the result
        of the normalization on a raw string, you can use
        :meth:`~tokenizers.normalizers.Normalizer.normalize_str`

        Args:
            normalized (:class:`~tokenizers.NormalizedString`):
                The normalized string on which to apply this
                :class:`~tokenizers.normalizers.Normalizer`
        """
        pass

    def normalize_str(self, sequence):
        """
        Normalize the given string

        This method provides a way to visualize the effect of a
        :class:`~tokenizers.normalizers.Normalizer` but it does not keep track of the alignment
        information. If you need to get/convert offsets, you can use
        :meth:`~tokenizers.normalizers.Normalizer.normalize`

        Args:
            sequence (:obj:`str`):
                A string to normalize

        Returns:
            :obj:`str`: A string after normalization
        """
        pass

class NFD(Normalizer):
    """
    NFD Unicode Normalizer
    """
    def __init__(self):
        pass

    def __getstate__(self):
        """ """
        pass

    def __setstate__(self, state):
        """ """
        pass

    @staticmethod
    def custom(normalizer):
        """ """
        pass

    def normalize(self, normalized):
        """
        Normalize a :class:`~tokenizers.NormalizedString` in-place

        This method allows to modify a :class:`~tokenizers.NormalizedString` to
        keep track of the alignment information. If you just want to see the result
        of the normalization on a raw string, you can use
        :meth:`~tokenizers.normalizers.Normalizer.normalize_str`

        Args:
            normalized (:class:`~tokenizers.NormalizedString`):
                The normalized string on which to apply this
                :class:`~tokenizers.normalizers.Normalizer`
        """
        pass

    def normalize_str(self, sequence):
        """
        Normalize the given string

        This method provides a way to visualize the effect of a
        :class:`~tokenizers.normalizers.Normalizer` but it does not keep track of the alignment
        information. If you need to get/convert offsets, you can use
        :meth:`~tokenizers.normalizers.Normalizer.normalize`

        Args:
            sequence (:obj:`str`):
                A string to normalize

        Returns:
            :obj:`str`: A string after normalization
        """
        pass

class NFKC(Normalizer):
    """
    NFKC Unicode Normalizer
    """
    def __init__(self):
        pass

    def __getstate__(self):
        """ """
        pass

    def __setstate__(self, state):
        """ """
        pass

    @staticmethod
    def custom(normalizer):
        """ """
        pass

    def normalize(self, normalized):
        """
        Normalize a :class:`~tokenizers.NormalizedString` in-place

        This method allows to modify a :class:`~tokenizers.NormalizedString` to
        keep track of the alignment information. If you just want to see the result
        of the normalization on a raw string, you can use
        :meth:`~tokenizers.normalizers.Normalizer.normalize_str`

        Args:
            normalized (:class:`~tokenizers.NormalizedString`):
                The normalized string on which to apply this
                :class:`~tokenizers.normalizers.Normalizer`
        """
        pass

    def normalize_str(self, sequence):
        """
        Normalize the given string

        This method provides a way to visualize the effect of a
        :class:`~tokenizers.normalizers.Normalizer` but it does not keep track of the alignment
        information. If you need to get/convert offsets, you can use
        :meth:`~tokenizers.normalizers.Normalizer.normalize`

        Args:
            sequence (:obj:`str`):
                A string to normalize

        Returns:
            :obj:`str`: A string after normalization
        """
        pass

class NFKD(Normalizer):
    """
    NFKD Unicode Normalizer
    """
    def __init__(self):
        pass

    def __getstate__(self):
        """ """
        pass

    def __setstate__(self, state):
        """ """
        pass

    @staticmethod
    def custom(normalizer):
        """ """
        pass

    def normalize(self, normalized):
        """
        Normalize a :class:`~tokenizers.NormalizedString` in-place

        This method allows to modify a :class:`~tokenizers.NormalizedString` to
        keep track of the alignment information. If you just want to see the result
        of the normalization on a raw string, you can use
        :meth:`~tokenizers.normalizers.Normalizer.normalize_str`

        Args:
            normalized (:class:`~tokenizers.NormalizedString`):
                The normalized string on which to apply this
                :class:`~tokenizers.normalizers.Normalizer`
        """
        pass

    def normalize_str(self, sequence):
        """
        Normalize the given string

        This method provides a way to visualize the effect of a
        :class:`~tokenizers.normalizers.Normalizer` but it does not keep track of the alignment
        information. If you need to get/convert offsets, you can use
        :meth:`~tokenizers.normalizers.Normalizer.normalize`

        Args:
            sequence (:obj:`str`):
                A string to normalize

        Returns:
            :obj:`str`: A string after normalization
        """
        pass

class Nmt(Normalizer):
    """
    Nmt normalizer
    """
    def __init__(self):
        pass

    def __getstate__(self):
        """ """
        pass

    def __setstate__(self, state):
        """ """
        pass

    @staticmethod
    def custom(normalizer):
        """ """
        pass

    def normalize(self, normalized):
        """
        Normalize a :class:`~tokenizers.NormalizedString` in-place

        This method allows to modify a :class:`~tokenizers.NormalizedString` to
        keep track of the alignment information. If you just want to see the result
        of the normalization on a raw string, you can use
        :meth:`~tokenizers.normalizers.Normalizer.normalize_str`

        Args:
            normalized (:class:`~tokenizers.NormalizedString`):
                The normalized string on which to apply this
                :class:`~tokenizers.normalizers.Normalizer`
        """
        pass

    def normalize_str(self, sequence):
        """
        Normalize the given string

        This method provides a way to visualize the effect of a
        :class:`~tokenizers.normalizers.Normalizer` but it does not keep track of the alignment
        information. If you need to get/convert offsets, you can use
        :meth:`~tokenizers.normalizers.Normalizer.normalize`

        Args:
            sequence (:obj:`str`):
                A string to normalize

        Returns:
            :obj:`str`: A string after normalization
        """
        pass

class Precompiled(Normalizer):
    """
    Precompiled normalizer
    Don't use manually it is used for compatibility for SentencePiece.
    """
    def __init__(self, precompiled_charsmap):
        pass

    def __getstate__(self):
        """ """
        pass

    def __setstate__(self, state):
        """ """
        pass

    @staticmethod
    def custom(normalizer):
        """ """
        pass

    def normalize(self, normalized):
        """
        Normalize a :class:`~tokenizers.NormalizedString` in-place

        This method allows to modify a :class:`~tokenizers.NormalizedString` to
        keep track of the alignment information. If you just want to see the result
        of the normalization on a raw string, you can use
        :meth:`~tokenizers.normalizers.Normalizer.normalize_str`

        Args:
            normalized (:class:`~tokenizers.NormalizedString`):
                The normalized string on which to apply this
                :class:`~tokenizers.normalizers.Normalizer`
        """
        pass

    def normalize_str(self, sequence):
        """
        Normalize the given string

        This method provides a way to visualize the effect of a
        :class:`~tokenizers.normalizers.Normalizer` but it does not keep track of the alignment
        information. If you need to get/convert offsets, you can use
        :meth:`~tokenizers.normalizers.Normalizer.normalize`

        Args:
            sequence (:obj:`str`):
                A string to normalize

        Returns:
            :obj:`str`: A string after normalization
        """
        pass

class Prepend(Normalizer):
    """
    Prepend normalizer
    """
    def __init__(self, prepend):
        pass

    def __getstate__(self):
        """ """
        pass

    def __setstate__(self, state):
        """ """
        pass

    @staticmethod
    def custom(normalizer):
        """ """
        pass

    def normalize(self, normalized):
        """
        Normalize a :class:`~tokenizers.NormalizedString` in-place

        This method allows to modify a :class:`~tokenizers.NormalizedString` to
        keep track of the alignment information. If you just want to see the result
        of the normalization on a raw string, you can use
        :meth:`~tokenizers.normalizers.Normalizer.normalize_str`

        Args:
            normalized (:class:`~tokenizers.NormalizedString`):
                The normalized string on which to apply this
                :class:`~tokenizers.normalizers.Normalizer`
        """
        pass

    def normalize_str(self, sequence):
        """
        Normalize the given string

        This method provides a way to visualize the effect of a
        :class:`~tokenizers.normalizers.Normalizer` but it does not keep track of the alignment
        information. If you need to get/convert offsets, you can use
        :meth:`~tokenizers.normalizers.Normalizer.normalize`

        Args:
            sequence (:obj:`str`):
                A string to normalize

        Returns:
            :obj:`str`: A string after normalization
        """
        pass

    @property
    def prepend(self):
        """ """
        pass

    @prepend.setter
    def prepend(self, value):
        """ """
        pass

class Replace(Normalizer):
    """
    Replace normalizer
    """
    def __init__(self, pattern, content):
        pass

    def __getstate__(self):
        """ """
        pass

    def __setstate__(self, state):
        """ """
        pass

    @property
    def content(self):
        """ """
        pass

    @content.setter
    def content(self, value):
        """ """
        pass

    @staticmethod
    def custom(normalizer):
        """ """
        pass

    def normalize(self, normalized):
        """
        Normalize a :class:`~tokenizers.NormalizedString` in-place

        This method allows to modify a :class:`~tokenizers.NormalizedString` to
        keep track of the alignment information. If you just want to see the result
        of the normalization on a raw string, you can use
        :meth:`~tokenizers.normalizers.Normalizer.normalize_str`

        Args:
            normalized (:class:`~tokenizers.NormalizedString`):
                The normalized string on which to apply this
                :class:`~tokenizers.normalizers.Normalizer`
        """
        pass

    def normalize_str(self, sequence):
        """
        Normalize the given string

        This method provides a way to visualize the effect of a
        :class:`~tokenizers.normalizers.Normalizer` but it does not keep track of the alignment
        information. If you need to get/convert offsets, you can use
        :meth:`~tokenizers.normalizers.Normalizer.normalize`

        Args:
            sequence (:obj:`str`):
                A string to normalize

        Returns:
            :obj:`str`: A string after normalization
        """
        pass

    @property
    def pattern(self):
        """ """
        pass

    @pattern.setter
    def pattern(self, value):
        """ """
        pass

class Sequence(Normalizer):
    """
    Allows concatenating multiple other Normalizer as a Sequence.
    All the normalizers run in sequence in the given order

    Args:
        normalizers (:obj:`List[Normalizer]`):
            A list of Normalizer to be run as a sequence
    """
    def __init__(self, normalizers):
        pass

    def __getitem__(self, key):
        """
        Return self[key].
        """
        pass

    def __getnewargs__(self):
        """ """
        pass

    def __getstate__(self):
        """ """
        pass

    def __setitem__(self, key, value):
        """
        Set self[key] to value.
        """
        pass

    def __setstate__(self, state):
        """ """
        pass

    @staticmethod
    def custom(normalizer):
        """ """
        pass

    def normalize(self, normalized):
        """
        Normalize a :class:`~tokenizers.NormalizedString` in-place

        This method allows to modify a :class:`~tokenizers.NormalizedString` to
        keep track of the alignment information. If you just want to see the result
        of the normalization on a raw string, you can use
        :meth:`~tokenizers.normalizers.Normalizer.normalize_str`

        Args:
            normalized (:class:`~tokenizers.NormalizedString`):
                The normalized string on which to apply this
                :class:`~tokenizers.normalizers.Normalizer`
        """
        pass

    def normalize_str(self, sequence):
        """
        Normalize the given string

        This method provides a way to visualize the effect of a
        :class:`~tokenizers.normalizers.Normalizer` but it does not keep track of the alignment
        information. If you need to get/convert offsets, you can use
        :meth:`~tokenizers.normalizers.Normalizer.normalize`

        Args:
            sequence (:obj:`str`):
                A string to normalize

        Returns:
            :obj:`str`: A string after normalization
        """
        pass

class Strip(Normalizer):
    """
    Strip normalizer
    """
    def __init__(self, left=True, right=True):
        pass

    def __getstate__(self):
        """ """
        pass

    def __setstate__(self, state):
        """ """
        pass

    @staticmethod
    def custom(normalizer):
        """ """
        pass

    @property
    def left(self):
        """ """
        pass

    @left.setter
    def left(self, value):
        """ """
        pass

    def normalize(self, normalized):
        """
        Normalize a :class:`~tokenizers.NormalizedString` in-place

        This method allows to modify a :class:`~tokenizers.NormalizedString` to
        keep track of the alignment information. If you just want to see the result
        of the normalization on a raw string, you can use
        :meth:`~tokenizers.normalizers.Normalizer.normalize_str`

        Args:
            normalized (:class:`~tokenizers.NormalizedString`):
                The normalized string on which to apply this
                :class:`~tokenizers.normalizers.Normalizer`
        """
        pass

    def normalize_str(self, sequence):
        """
        Normalize the given string

        This method provides a way to visualize the effect of a
        :class:`~tokenizers.normalizers.Normalizer` but it does not keep track of the alignment
        information. If you need to get/convert offsets, you can use
        :meth:`~tokenizers.normalizers.Normalizer.normalize`

        Args:
            sequence (:obj:`str`):
                A string to normalize

        Returns:
            :obj:`str`: A string after normalization
        """
        pass

    @property
    def right(self):
        """ """
        pass

    @right.setter
    def right(self, value):
        """ """
        pass

class StripAccents(Normalizer):
    """
    StripAccents normalizer
    """
    def __init__(self):
        pass

    def __getstate__(self):
        """ """
        pass

    def __setstate__(self, state):
        """ """
        pass

    @staticmethod
    def custom(normalizer):
        """ """
        pass

    def normalize(self, normalized):
        """
        Normalize a :class:`~tokenizers.NormalizedString` in-place

        This method allows to modify a :class:`~tokenizers.NormalizedString` to
        keep track of the alignment information. If you just want to see the result
        of the normalization on a raw string, you can use
        :meth:`~tokenizers.normalizers.Normalizer.normalize_str`

        Args:
            normalized (:class:`~tokenizers.NormalizedString`):
                The normalized string on which to apply this
                :class:`~tokenizers.normalizers.Normalizer`
        """
        pass

    def normalize_str(self, sequence):
        """
        Normalize the given string

        This method provides a way to visualize the effect of a
        :class:`~tokenizers.normalizers.Normalizer` but it does not keep track of the alignment
        information. If you need to get/convert offsets, you can use
        :meth:`~tokenizers.normalizers.Normalizer.normalize`

        Args:
            sequence (:obj:`str`):
                A string to normalize

        Returns:
            :obj:`str`: A string after normalization
        """
        pass

from typing import Dict

NORMALIZERS: Dict[str, Normalizer]

def unicode_normalizer_from_str(normalizer: str) -> Normalizer: ...
