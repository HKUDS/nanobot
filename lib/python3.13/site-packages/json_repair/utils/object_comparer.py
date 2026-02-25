from typing import Any


class ObjectComparer:  # pragma: no cover
    def __init__(self) -> None:
        pass  # No operation performed in the constructor

    @staticmethod
    def is_same_object(obj1: Any, obj2: Any) -> bool:
        """
        Recursively compares two objects and ensures that:
        - Their types match
        - Their keys/structure match
        """
        if type(obj1) is not type(obj2):
            # Fail immediately if the types don't match
            return False

        if isinstance(obj1, dict):
            # Check that both are dicts and same length
            if not isinstance(obj2, dict) or len(obj1) != len(obj2):
                return False
            for key in obj1:
                if key not in obj2:
                    return False
                # Recursively compare each value
                if not ObjectComparer.is_same_object(obj1[key], obj2[key]):
                    return False
            return True

        if isinstance(obj1, list):
            # Check that both are lists and same length
            if not isinstance(obj2, list) or len(obj1) != len(obj2):
                return False
            # Recursively compare each item
            return all(ObjectComparer.is_same_object(obj1[i], obj2[i]) for i in range(len(obj1)))

        # For atomic values: types already match, so return True
        return True

    @staticmethod
    def is_strictly_empty(value: Any) -> bool:
        """
        Returns True if value is an empty container (str, list, dict, set, tuple).
        Returns False for non-containers like None, 0, False, etc.
        """
        return isinstance(value, str | list | dict | set | tuple) and len(value) == 0
