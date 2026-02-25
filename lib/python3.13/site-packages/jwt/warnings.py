class RemovedInPyjwt3Warning(DeprecationWarning):
    """Warning for features that will be removed in PyJWT 3."""

    pass


class InsecureKeyLengthWarning(UserWarning):
    """Warning emitted when a cryptographic key is shorter than the minimum
    recommended length. See :ref:`key-length-validation` for details."""

    pass
