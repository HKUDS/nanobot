# Third-party notices

Parts of the Cua Driver Rust workspace are derived from these MIT-licensed
projects. Each project's copyright notice is below, followed by the MIT
License text they share.

| Project                                                         | Copyright                            | Used in                                                                                                                                                        | What                                                                                                                                            |
| --------------------------------------------------------------- | ------------------------------------ | -------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------- |
| [trope-cua](https://github.com/voctory/trope-cua)               | Copyright (c) 2026 Victor Vannara    | `crates/cursor-overlay/src/motion.rs`, `crates/cursor-overlay/src/bezier.rs`; `crates/platform-windows` (`src/overlay.rs`, `src/input/`, `src/tools/impl_.rs`) | Agent-cursor motion and timing configuration and Bezier segment math; Windows cursor overlay, background input and layered pixel-click dispatch |
| [Interface-Agent](https://github.com/francedot/Interface-Agent) | Copyright (c) 2024 Francesco Bonacci | `crates/platform-windows` (`src/uia/`, `src/win32/`, `src/tools/impl_.rs`)                                                                                     | Windows UI Automation tree walk, app and window enumeration, InvokePattern click and ValuePattern set-value                                     |
| [yabai](https://github.com/koekeishiya/yabai)                   | Copyright (c) 2019 Åsmund Vikane     | `crates/platform-macos/src/input/skylight.rs` (`activate_without_raise`)                                                                                       | The focus-without-raise SkyLight event-record sequence                                                                                          |

## MIT License

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
