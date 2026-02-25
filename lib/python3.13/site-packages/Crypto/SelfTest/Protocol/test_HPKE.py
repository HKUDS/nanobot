import os
import json
import unittest
from binascii import unhexlify

from Crypto.Protocol import HPKE
from Crypto.Protocol.HPKE import DeserializeError

from Crypto.PublicKey import ECC
from Crypto.SelfTest.st_common import list_test_cases

from Crypto.Protocol import DH
from Crypto.Hash import SHA256, SHA384, SHA512


class HPKE_Tests(unittest.TestCase):

    key1 = ECC.generate(curve='p256')
    key2 = ECC.generate(curve='p256')

    # name, size of enc
    curves = {
        'p256': 65,
        'p384': 97,
        'p521': 133,
        'curve25519': 32,
        'curve448': 56,
    }

    def round_trip(self, curve, aead_id):
        key1 = ECC.generate(curve=curve)
        aead_id = aead_id

        encryptor = HPKE.new(receiver_key=key1.public_key(),
                             aead_id=aead_id)
        self.assertEqual(len(encryptor.enc), self.curves[curve])

        # First message
        ct = encryptor.seal(b'ABC', auth_data=b'DEF')

        decryptor = HPKE.new(receiver_key=key1,
                             aead_id=aead_id,
                             enc=encryptor.enc)

        pt = decryptor.unseal(ct, auth_data=b'DEF')
        self.assertEqual(b'ABC', pt)

        # Second message
        ct2 = encryptor.seal(b'GHI')
        pt2 = decryptor.unseal(ct2)
        self.assertEqual(b'GHI', pt2)

    def test_round_trip(self):
        for curve in self.curves.keys():
            for aead_id in HPKE.AEAD:
                self.round_trip(curve, aead_id)

    def test_psk(self):
        aead_id = HPKE.AEAD.AES128_GCM
        HPKE.new(receiver_key=self.key1.public_key(),
                 aead_id=aead_id,
                 psk=(b'a', b'c' * 32))

    def test_info(self):
        aead_id = HPKE.AEAD.AES128_GCM
        HPKE.new(receiver_key=self.key1.public_key(),
                 aead_id=aead_id,
                 info=b'baba')

    def test_neg_unsupported_curve(self):
        key3 = ECC.generate(curve='p224')
        with self.assertRaises(ValueError) as cm:
            HPKE.new(receiver_key=key3.public_key(),
                     aead_id=HPKE.AEAD.AES128_GCM)
        self.assertIn("Unsupported curve", str(cm.exception))

    def test_neg_too_many_private_keys(self):
        with self.assertRaises(ValueError) as cm:
            HPKE.new(receiver_key=self.key1,
                     sender_key=self.key2,
                     aead_id=HPKE.AEAD.AES128_GCM)
        self.assertIn("Exactly 1 private key", str(cm.exception))

    def test_neg_curve_mismatch(self):
        key3 = ECC.generate(curve='p384')
        with self.assertRaises(ValueError) as cm:
            HPKE.new(receiver_key=self.key1.public_key(),
                     sender_key=key3,
                     aead_id=HPKE.AEAD.AES128_GCM)
        self.assertIn("but recipient key", str(cm.exception))

    def test_neg_psk(self):
        with self.assertRaises(ValueError) as cm:
            HPKE.new(receiver_key=self.key1.public_key(),
                     psk=(b'', b'G' * 32),
                     aead_id=HPKE.AEAD.AES128_GCM)

        with self.assertRaises(ValueError) as cm:
            HPKE.new(receiver_key=self.key1.public_key(),
                     psk=(b'JJJ', b''),
                     aead_id=HPKE.AEAD.AES128_GCM)

        with self.assertRaises(ValueError) as cm:
            HPKE.new(receiver_key=self.key1.public_key(),
                     psk=(b'JJJ', b'Y' * 31),
                     aead_id=HPKE.AEAD.AES128_GCM)
        self.assertIn("at least 32", str(cm.exception))

    def test_neg_wrong_enc(self):
        wrong_enc = b'\xFF' + b'8' * 64
        with self.assertRaises(DeserializeError):
            HPKE.new(receiver_key=self.key1,
                     aead_id=HPKE.AEAD.AES128_GCM,
                     enc=wrong_enc)

        with self.assertRaises(ValueError) as cm:
            HPKE.new(receiver_key=self.key1.public_key(),
                     enc=self.key1.public_key().export_key(format='raw'),
                     aead_id=HPKE.AEAD.AES128_GCM)
        self.assertIn("'enc' cannot be an input", str(cm.exception))

        with self.assertRaises(ValueError) as cm:
            HPKE.new(receiver_key=self.key1,
                     aead_id=HPKE.AEAD.AES128_GCM)
        self.assertIn("'enc' required", str(cm.exception))

    def test_neg_unseal_wrong_ct(self):
        decryptor = HPKE.new(receiver_key=self.key1,
                             aead_id=HPKE.AEAD.CHACHA20_POLY1305,
                             enc=self.key2.public_key().export_key(format='raw'))

        with self.assertRaises(ValueError):
            decryptor.unseal(b'XYZ' * 20)

    def test_neg_unseal_no_auth_data(self):
        aead_id = HPKE.AEAD.CHACHA20_POLY1305

        encryptor = HPKE.new(receiver_key=self.key1.public_key(),
                             aead_id=aead_id)

        ct = encryptor.seal(b'ABC', auth_data=b'DEF')

        decryptor = HPKE.new(receiver_key=self.key1,
                             aead_id=aead_id,
                             enc=encryptor.enc)

        with self.assertRaises(ValueError):
            decryptor.unseal(ct)

    def test_x25519_mode_0(self):
        # RFC x9180, A.1.1.1, seq 0 and 1

        keyR_hex = "4612c550263fc8ad58375df3f557aac531d26850903e55a9f23f21d8534e8ac8"
        keyR = DH.import_x25519_private_key(bytes.fromhex(keyR_hex))

        pt_hex = "4265617574792069732074727574682c20747275746820626561757479"
        pt = bytes.fromhex(pt_hex)

        ct0_hex = "f938558b5d72f1a23810b4be2ab4f84331acc02fc97babc53a52ae8218a355a96d8770ac83d07bea87e13c512a"
        ct0 = bytes.fromhex(ct0_hex)

        enc_hex = "37fda3567bdbd628e88668c3c8d7e97d1d1253b6d4ea6d44c150f741f1bf4431"
        enc = bytes.fromhex(enc_hex)

        aad0_hex = "436f756e742d30"
        aad0 = bytes.fromhex(aad0_hex)

        aad1_hex = "436f756e742d31"
        aad1 = bytes.fromhex(aad1_hex)

        info_hex = "4f6465206f6e2061204772656369616e2055726e"
        info = bytes.fromhex(info_hex)

        ct1_hex = "af2d7e9ac9ae7e270f46ba1f975be53c09f8d875bdc8535458c2494e8a6eab251c03d0c22a56b8ca42c2063b84"
        ct1 = bytes.fromhex(ct1_hex)

        aead_id = HPKE.AEAD.AES128_GCM

        decryptor = HPKE.new(receiver_key=keyR,
                             aead_id=aead_id,
                             info=info,
                             enc=enc)

        pt_X0 = decryptor.unseal(ct0, aad0)
        self.assertEqual(pt_X0, pt)

        pt_X1 = decryptor.unseal(ct1, aad1)
        self.assertEqual(pt_X1, pt)

    def test_x25519_mode_1(self):
        # RFC x9180, A.1.2.1, seq 0 and 1

        keyR_hex = "c5eb01eb457fe6c6f57577c5413b931550a162c71a03ac8d196babbd4e5ce0fd"
        keyR = DH.import_x25519_private_key(bytes.fromhex(keyR_hex))

        psk_id_hex = "456e6e796e20447572696e206172616e204d6f726961"
        psk_id = bytes.fromhex(psk_id_hex)

        psk_hex = "0247fd33b913760fa1fa51e1892d9f307fbe65eb171e8132c2af18555a738b82"
        psk = bytes.fromhex(psk_hex)

        pt_hex = "4265617574792069732074727574682c20747275746820626561757479"
        pt = bytes.fromhex(pt_hex)

        ct0_hex = "e52c6fed7f758d0cf7145689f21bc1be6ec9ea097fef4e959440012f4feb73fb611b946199e681f4cfc34db8ea"
        ct0 = bytes.fromhex(ct0_hex)

        enc_hex = "0ad0950d9fb9588e59690b74f1237ecdf1d775cd60be2eca57af5a4b0471c91b"
        enc = bytes.fromhex(enc_hex)

        aad0_hex = "436f756e742d30"
        aad0 = bytes.fromhex(aad0_hex)

        aad1_hex = "436f756e742d31"
        aad1 = bytes.fromhex(aad1_hex)

        info_hex = "4f6465206f6e2061204772656369616e2055726e"
        info = bytes.fromhex(info_hex)

        ct1_hex = "49f3b19b28a9ea9f43e8c71204c00d4a490ee7f61387b6719db765e948123b45b61633ef059ba22cd62437c8ba"
        ct1 = bytes.fromhex(ct1_hex)

        aead_id = HPKE.AEAD.AES128_GCM

        decryptor = HPKE.new(receiver_key=keyR,
                             aead_id=aead_id,
                             info=info,
                             psk=(psk_id, psk),
                             enc=enc)

        pt_X0 = decryptor.unseal(ct0, aad0)
        self.assertEqual(pt_X0, pt)

        pt_X1 = decryptor.unseal(ct1, aad1)
        self.assertEqual(pt_X1, pt)

    def test_x25519_mode_2(self):
        # RFC x9180, A.1.3.1, seq 0 and 1

        keyR_hex = "fdea67cf831f1ca98d8e27b1f6abeb5b7745e9d35348b80fa407ff6958f9137e"
        keyR = DH.import_x25519_private_key(bytes.fromhex(keyR_hex))

        keyS_hex = "dc4a146313cce60a278a5323d321f051c5707e9c45ba21a3479fecdf76fc69dd"
        keyS = DH.import_x25519_private_key(bytes.fromhex(keyS_hex))

        pt_hex = "4265617574792069732074727574682c20747275746820626561757479"
        pt = bytes.fromhex(pt_hex)

        ct0_hex = "5fd92cc9d46dbf8943e72a07e42f363ed5f721212cd90bcfd072bfd9f44e06b80fd17824947496e21b680c141b"
        ct0 = bytes.fromhex(ct0_hex)

        enc_hex = "23fb952571a14a25e3d678140cd0e5eb47a0961bb18afcf85896e5453c312e76"
        enc = bytes.fromhex(enc_hex)

        aad0_hex = "436f756e742d30"
        aad0 = bytes.fromhex(aad0_hex)

        aad1_hex = "436f756e742d31"
        aad1 = bytes.fromhex(aad1_hex)

        info_hex = "4f6465206f6e2061204772656369616e2055726e"
        info = bytes.fromhex(info_hex)

        ct1_hex = "d3736bb256c19bfa93d79e8f80b7971262cb7c887e35c26370cfed62254369a1b52e3d505b79dd699f002bc8ed"
        ct1 = bytes.fromhex(ct1_hex)

        aead_id = HPKE.AEAD.AES128_GCM

        decryptor = HPKE.new(receiver_key=keyR,
                             sender_key=keyS.public_key(),
                             aead_id=aead_id,
                             info=info,
                             enc=enc)

        pt_X0 = decryptor.unseal(ct0, aad0)
        self.assertEqual(pt_X0, pt)

        pt_X1 = decryptor.unseal(ct1, aad1)
        self.assertEqual(pt_X1, pt)

    def test_x25519_mode_3(self):
        # RFC x9180, A.1.4.1, seq 0 and 1

        keyR_hex = "cb29a95649dc5656c2d054c1aa0d3df0493155e9d5da6d7e344ed8b6a64a9423"
        keyR = DH.import_x25519_private_key(bytes.fromhex(keyR_hex))

        keyS_hex = "fc1c87d2f3832adb178b431fce2ac77c7ca2fd680f3406c77b5ecdf818b119f4"
        keyS = DH.import_x25519_private_key(bytes.fromhex(keyS_hex))

        psk_id_hex = "456e6e796e20447572696e206172616e204d6f726961"
        psk_id = bytes.fromhex(psk_id_hex)

        psk_hex = "0247fd33b913760fa1fa51e1892d9f307fbe65eb171e8132c2af18555a738b82"
        psk = bytes.fromhex(psk_hex)

        pt_hex = "4265617574792069732074727574682c20747275746820626561757479"
        pt = bytes.fromhex(pt_hex)

        ct0_hex = "a84c64df1e11d8fd11450039d4fe64ff0c8a99fca0bd72c2d4c3e0400bc14a40f27e45e141a24001697737533e"
        ct0 = bytes.fromhex(ct0_hex)

        enc_hex = "820818d3c23993492cc5623ab437a48a0a7ca3e9639c140fe1e33811eb844b7c"
        enc = bytes.fromhex(enc_hex)

        aad0_hex = "436f756e742d30"
        aad0 = bytes.fromhex(aad0_hex)

        aad1_hex = "436f756e742d31"
        aad1 = bytes.fromhex(aad1_hex)

        info_hex = "4f6465206f6e2061204772656369616e2055726e"
        info = bytes.fromhex(info_hex)

        ct1_hex = "4d19303b848f424fc3c3beca249b2c6de0a34083b8e909b6aa4c3688505c05ffe0c8f57a0a4c5ab9da127435d9"
        ct1 = bytes.fromhex(ct1_hex)

        aead_id = HPKE.AEAD.AES128_GCM

        decryptor = HPKE.new(receiver_key=keyR,
                             sender_key=keyS.public_key(),
                             aead_id=aead_id,
                             psk=(psk_id, psk),
                             info=info,
                             enc=enc)

        pt_X0 = decryptor.unseal(ct0, aad0)
        self.assertEqual(pt_X0, pt)

        pt_X1 = decryptor.unseal(ct1, aad1)
        self.assertEqual(pt_X1, pt)


class HPKE_TestVectors(unittest.TestCase):

    def setUp(self):
        self.vectors = []
        try:
            import pycryptodome_test_vectors    # type: ignore
            init_dir = os.path.dirname(pycryptodome_test_vectors.__file__)
            full_file_name = os.path.join(init_dir, "Protocol", "wycheproof", "HPKE-test-vectors.json")
            with open(full_file_name, "r") as f:
                self.vectors = json.load(f)
        except (FileNotFoundError, ImportError):
            print("\nWarning: skipping extended tests for HPKE (install pycryptodome-test-vectors)")

    def import_private_key(self, key_hex, kem_id):
        key_bin = unhexlify(key_hex)
        if kem_id == 0x0010:
            return ECC.construct(curve='p256', d=int.from_bytes(key_bin,
                                                                byteorder="big"))
        elif kem_id == 0x0011:
            return ECC.construct(curve='p384', d=int.from_bytes(key_bin,
                                                                byteorder="big"))
        elif kem_id == 0x0012:
            return ECC.construct(curve='p521', d=int.from_bytes(key_bin,
                                                                byteorder="big"))
        elif kem_id == 0x0020:
            return DH.import_x25519_private_key(key_bin)
        elif kem_id == 0x0021:
            return DH.import_x448_private_key(key_bin)

    def test_hpke_encap(self):
        """Test HPKE encapsulation using test vectors."""

        if not self.vectors:
            self.skipTest("No test vectors available")

        for idx, vector in enumerate(self.vectors):

            kem_id = vector["kem_id"]
            kdf_id = vector["kdf_id"]
            aead_id = vector["aead_id"]

            # No export-only pseudo-cipher
            if aead_id == 0xffff:
                continue

            # We support only one KDF per curve
            supported_combi = {
                (0x10, 0x1): SHA256,
                (0x11, 0x2): SHA384,
                (0x12, 0x3): SHA512,
                (0x20, 0x1): SHA256,
                (0x21, 0x3): SHA512,
            }
            hashmod = supported_combi.get((kem_id, kdf_id))
            if hashmod is None:
                continue

            with self.subTest(idx=idx, kem_id=kem_id, aead_id=aead_id):

                receiver_pub = self.import_private_key(vector["skRm"],
                                                       kem_id).public_key()

                sender_priv = None
                if "skSm" in vector:
                    sender_priv = self.import_private_key(vector["skSm"],
                                                          kem_id)

                encap_key = self.import_private_key(vector["skEm"], kem_id)

                shared_secret, enc = HPKE.HPKE_Cipher._encap(receiver_pub,
                                                             kem_id,
                                                             hashmod,
                                                             sender_priv,
                                                             encap_key)
                self.assertEqual(enc.hex(), vector["enc"])
                self.assertEqual(shared_secret,
                                 unhexlify(vector["shared_secret"]))

            print(".", end="", flush=True)

    def test_hpke_unseal(self):
        """Test HPKE encryption and decryption using test vectors."""

        if not self.vectors:
            self.skipTest("No test vectors available")

        for idx, vector in enumerate(self.vectors):

            kem_id = vector["kem_id"]
            kdf_id = vector["kdf_id"]
            aead_id = vector["aead_id"]

            # No export-only pseudo-cipher
            if aead_id == 0xffff:
                continue

            # We support only one KDF per curve
            supported_combi = (
                (0x10, 0x1),
                (0x11, 0x2),
                (0x12, 0x3),
                (0x20, 0x1),
                (0x21, 0x3),
            )
            if (kem_id, kdf_id) not in supported_combi:
                continue

            with self.subTest(idx=idx, kem_id=kem_id, aead_id=aead_id):

                receiver_priv = self.import_private_key(vector["skRm"],
                                                        kem_id)

                sender_pub = None
                if "skSm" in vector:
                    sender_priv = self.import_private_key(vector["skSm"],
                                                          kem_id)
                    sender_pub = sender_priv.public_key()

                encap_key = unhexlify(vector["enc"])

                psk = None
                if "psk_id" in vector:
                    psk = unhexlify(vector["psk_id"]), unhexlify(vector["psk"])

                receiver_hpke = HPKE.new(receiver_key=receiver_priv,
                                         aead_id=HPKE.AEAD(aead_id),
                                         enc=encap_key,
                                         sender_key=sender_pub,
                                         psk=psk,
                                         info=unhexlify(vector["info"]))

                for encryption in vector['encryptions']:

                    plaintext = unhexlify(encryption["pt"])
                    ciphertext = unhexlify(encryption["ct"])
                    aad = unhexlify(encryption["aad"])

                    # Decrypt (unseal)
                    decrypted = receiver_hpke.unseal(ciphertext, aad)
                    self.assertEqual(decrypted, plaintext, "Decryption failed")

            print(".", end="", flush=True)


def get_tests(config={}):

    tests = []
    tests += list_test_cases(HPKE_Tests)

    if config.get('slow_tests'):
        tests += list_test_cases(HPKE_TestVectors)

    return tests


if __name__ == '__main__':
    def suite():
        return unittest.TestSuite(get_tests())
    unittest.main(defaultTest='suite')
