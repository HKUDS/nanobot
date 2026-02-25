import unittest

from Crypto.SelfTest.st_common import list_test_cases
from Crypto.SelfTest.loader import load_test_vectors_wycheproof

from Crypto.Cipher import AES


class KW_Tests(unittest.TestCase):

    # From RFC3394
    tvs = [
        ("000102030405060708090A0B0C0D0E0F",
         "00112233445566778899AABBCCDDEEFF",
         "1FA68B0A8112B447AEF34BD8FB5A7B829D3E862371D2CFE5"),
        ("000102030405060708090A0B0C0D0E0F1011121314151617",
         "00112233445566778899AABBCCDDEEFF",
         "96778B25AE6CA435F92B5B97C050AED2468AB8A17AD84E5D"),
        ("000102030405060708090A0B0C0D0E0F101112131415161718191A1B1C1D1E1F",
         "00112233445566778899AABBCCDDEEFF",
         "64E8C3F9CE0F5BA263E9777905818A2A93C8191E7D6E8AE7"),
        ("000102030405060708090A0B0C0D0E0F1011121314151617",
         "00112233445566778899AABBCCDDEEFF0001020304050607",
         "031D33264E15D33268F24EC260743EDCE1C6C7DDEE725A936BA814915C6762D2"),
        ("000102030405060708090A0B0C0D0E0F101112131415161718191A1B1C1D1E1F",
         "00112233445566778899AABBCCDDEEFF0001020304050607",
         "A8F9BC1612C68B3FF6E6F4FBE30E71E4769C8B80A32CB8958CD5D17D6B254DA1"),
        ("000102030405060708090A0B0C0D0E0F101112131415161718191A1B1C1D1E1F",
         "00112233445566778899AABBCCDDEEFF000102030405060708090A0B0C0D0E0F",
         "28C9F404C4B810F4CBCCB35CFB87F8263F5786E2D80ED326CBC7F0E71A99F43BFB988B9B7A02DD21"),
    ]

    def test_rfc3394(self):
        for tv in self.tvs:
            kek, pt, ct = [bytes.fromhex(x) for x in tv]

            cipher = AES.new(kek, AES.MODE_KW)
            ct2 = cipher.seal(pt)

            self.assertEqual(ct, ct2)

            cipher = AES.new(kek, AES.MODE_KW)
            pt2 = cipher.unseal(ct)
            self.assertEqual(pt, pt2)

    def test_neg1(self):

        cipher = AES.new(b'-' * 16, AES.MODE_KW)

        with self.assertRaises(ValueError):
            cipher.seal(b'')

        with self.assertRaises(ValueError):
            cipher.seal(b'8' * 17)

    def test_neg2(self):

        cipher = AES.new(b'-' * 16, AES.MODE_KW)
        ct = bytearray(cipher.seal(b'7' * 16))

        cipher = AES.new(b'-' * 16, AES.MODE_KW)
        cipher.unseal(ct)

        cipher = AES.new(b'-' * 16, AES.MODE_KW)
        ct[0] ^= 0xFF
        with self.assertRaises(ValueError):
            cipher.unseal(ct)


class KW_Wycheproof(unittest.TestCase):

    def setUp(self):
        self.vectors = load_test_vectors_wycheproof(("Cipher", "wycheproof"),
                                                    "kw_test.json",
                                                    "Wycheproof tests for KW")

    def test_wycheproof(self):

        if not self.vectors:
            self.skipTest("No test vectors available")

        for vector in self.vectors:
            with self.subTest(testId=vector.id):
                cipher = AES.new(vector.key, AES.MODE_KW)

                try:
                    cipher.seal(vector.msg)
                except ValueError:
                    if vector.valid:
                        raise
                    continue

                cipher = AES.new(vector.key, AES.MODE_KW)
                try:
                    pt = cipher.unseal(vector.ct)
                except ValueError:
                    if vector.valid:
                        raise
                    continue

                self.assertEqual(pt, vector.msg)


class KWP_Tests(unittest.TestCase):

    tvs = [
        ("5840df6e29b02af1ab493b705bf16ea1ae8338f4dcc176a8",
         "c37b7e6492584340bed12207808941155068f738",
         "138bdeaa9b8fa7fc61f97742e72248ee5ae6ae5360d1ae6a5f54f373fa543b6a"),
        ("5840df6e29b02af1ab493b705bf16ea1ae8338f4dcc176a8",
         "466f7250617369",
         "afbeb0f07dfbf5419200f2ccb50bb24f"),
    ]

    def test_rfc5649(self):
        for tv in self.tvs:
            kek, pt, ct = [bytes.fromhex(x) for x in tv]

            cipher = AES.new(kek, AES.MODE_KWP)
            ct2 = cipher.seal(pt)

            self.assertEqual(ct, ct2)

            cipher = AES.new(kek, AES.MODE_KWP)
            pt2 = cipher.unseal(ct)
            self.assertEqual(pt, pt2)


class KWP_Wycheproof(unittest.TestCase):

    def setUp(self):
        self.vectors = load_test_vectors_wycheproof(("Cipher", "wycheproof"),
                                                    "kwp_test.json",
                                                    "Wycheproof tests for KWP")

    def test_wycheproof(self):

        if not self.vectors:
            self.skipTest("No test vectors available")

        for vector in self.vectors:
            with self.subTest(testId=vector.id):
                cipher = AES.new(vector.key, AES.MODE_KWP)

                try:
                    cipher.seal(vector.msg)
                except ValueError:
                    if vector.valid and not vector.warning:
                        raise
                    continue

                cipher = AES.new(vector.key, AES.MODE_KWP)
                try:
                    pt = cipher.unseal(vector.ct)
                except ValueError:
                    if vector.valid and not vector.warning:
                        raise
                    continue

                self.assertEqual(pt, vector.msg)


def get_tests(config={}):
    tests = []
    tests += list_test_cases(KW_Tests)
    tests += list_test_cases(KWP_Tests)
    tests += list_test_cases(KW_Wycheproof)
    tests += list_test_cases(KWP_Wycheproof)
    return tests


if __name__ == '__main__':
    def suite():
        return unittest.TestSuite(get_tests())
    unittest.main(defaultTest='suite')
