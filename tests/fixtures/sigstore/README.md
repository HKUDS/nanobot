# Public verification fixture

`bundle_v3.txt` and `bundle_v3.txt.sigstore` are copied, without modification, from
the Sigstore project's Apache-2.0-licensed public test assets at commit
`7ee385ac8be192771bff1cc553434b11282ecce6`:
https://github.com/sigstore/sigstore-python/tree/7ee385ac8be192771bff1cc553434b11282ecce6/test/assets

Copyright The Sigstore Authors. Licensed under the Apache License, Version 2.0:
https://www.apache.org/licenses/LICENSE-2.0

These use Sigstore's staging root and contain a public artifact, public certificate and transparency proof, not
a private key or token. They prove cryptographic validation and rejection of a
valid but unauthorized publisher. They are **not** nanobot release approvals.
