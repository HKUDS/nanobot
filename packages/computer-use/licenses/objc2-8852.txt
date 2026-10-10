# License

The licensing of these crates is a bit complicated:
- The crates `objc2`, `block2`, `objc2-foundation` and `objc2-encode` are
  [currently][#23] licensed under [the MIT license][MIT].
- All other crates are trio-licensed under the [Zlib], [Apache-2.0] or [MIT]
  license, at your option.

Furthermore, the crates are (usually automatically) derived from Apple SDKs,
and that may have implications for licensing, see below for details.

[#23]: https://github.com/madsmtm/objc2/issues/23
[MIT]: https://opensource.org/license/MIT
[Zlib]: https://zlib.net/zlib_license.html
[Apache-2.0]: https://www.apache.org/licenses/LICENSE-2.0


## Apple SDKs

These crates are derived from Apple SDKs shipped with Xcode. You can obtain a
copy of the Xcode license at:

https://www.apple.com/legal/sla/docs/xcode.pdf

Or by typing `xcodebuild -license` in your terminal.

From reading the license, it is unclear whether distributing derived works
such as these crates are allowed?

But in any case, to practically use these crates, you will have to link, and
that only works when you have the correct Xcode SDK available to provide the
required `.tbd` files, which is why we choose to still use the normal SPDX
identifiers in the crates (Xcode is required to use the crates, and when using
Xcode you have already agreed to the Xcode license).
