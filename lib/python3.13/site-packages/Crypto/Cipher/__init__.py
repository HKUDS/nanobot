#
# A block cipher is instantiated as a combination of:
# 1. A base cipher (such as AES)
# 2. A mode of operation (such as CBC)
#
# Both items are implemented as C modules.
#
# The API of #1 is (replace "AES" with the name of the actual cipher):
# - AES_start_operaion(key) --> base_cipher_state
# - AES_encrypt(base_cipher_state, in, out, length)
# - AES_decrypt(base_cipher_state, in, out, length)
# - AES_stop_operation(base_cipher_state)
#
# Where base_cipher_state is AES_State, a struct with BlockBase (set of
# pointers to encrypt/decrypt/stop) followed by cipher-specific data.
#
# The API of #2 is (replace "CBC" with the name of the actual mode):
# - CBC_start_operation(base_cipher_state) --> mode_state
# - CBC_encrypt(mode_state, in, out, length)
# - CBC_decrypt(mode_state, in, out, length)
# - CBC_stop_operation(mode_state)
#
# where mode_state is a a pointer to base_cipher_state plus mode-specific data.

def _create_cipher(factory, key, mode, *args, **kwargs):

    kwargs["key"] = key

    if args:
        if mode in (8, 9, 10, 11, 12):
            if len(args) > 1:
                raise TypeError("Too many arguments for this mode")
            kwargs["nonce"] = args[0]
        elif mode in (2, 3, 5, 7):
            if len(args) > 1:
                raise TypeError("Too many arguments for this mode")
            kwargs["IV"] = args[0]
        elif mode == 6:
            if len(args) > 0:
                raise TypeError("Too many arguments for this mode")
        elif mode == 1:
            raise TypeError("IV is not meaningful for the ECB mode")

    res = None
    extra_modes = kwargs.pop("add_aes_modes", False)

    if mode == 1:
        from Crypto.Cipher._mode_ecb import _create_ecb_cipher
        res = _create_ecb_cipher(factory, **kwargs)
    elif mode == 2:
        from Crypto.Cipher._mode_cbc import _create_cbc_cipher
        res = _create_cbc_cipher(factory, **kwargs)
    elif mode == 3:
        from Crypto.Cipher._mode_cfb import _create_cfb_cipher
        res = _create_cfb_cipher(factory, **kwargs)
    elif mode == 5:
        from Crypto.Cipher._mode_ofb import _create_ofb_cipher
        res = _create_ofb_cipher(factory, **kwargs)
    elif mode == 6:
        from Crypto.Cipher._mode_ctr import _create_ctr_cipher
        res = _create_ctr_cipher(factory, **kwargs)
    elif mode == 7:
        from Crypto.Cipher._mode_openpgp import _create_openpgp_cipher
        res = _create_openpgp_cipher(factory, **kwargs)
    elif mode == 9:
        from Crypto.Cipher._mode_eax import _create_eax_cipher
        res = _create_eax_cipher(factory, **kwargs)
    elif extra_modes:
        if mode == 8:
            from Crypto.Cipher._mode_ccm import _create_ccm_cipher
            res = _create_ccm_cipher(factory, **kwargs)
        elif mode == 10:
            from Crypto.Cipher._mode_siv import _create_siv_cipher
            res = _create_siv_cipher(factory, **kwargs)
        elif mode == 11:
            from Crypto.Cipher._mode_gcm import _create_gcm_cipher
            res = _create_gcm_cipher(factory, **kwargs)
        elif mode == 12:
            from Crypto.Cipher._mode_ocb import _create_ocb_cipher
            res = _create_ocb_cipher(factory, **kwargs)
        elif mode == 13:
            from Crypto.Cipher._mode_kw import _create_kw_cipher
            res = _create_kw_cipher(factory, **kwargs)
        elif mode == 14:
            from Crypto.Cipher._mode_kwp import _create_kwp_cipher
            res = _create_kwp_cipher(factory, **kwargs)

    if res is None:
        raise ValueError("Mode not supported")

    return res
