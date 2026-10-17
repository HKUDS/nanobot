# iOS PWA top-edge rendering

[Issue #5772](https://github.com/HKUDS/nanobot/issues/5772) tracks washed-out controls at the top of an installed iOS PWA. This is separate from the mobile sidebar focus and double-tap fixes in #5839.

## Compatibility surface

The initial HTML includes one empty, non-interactive `.pwa-status-bar-surface` outside React's root. It only renders in standalone mode on engines supporting `-webkit-touch-callout` and text background clipping. Normal browser tabs and Chromium PWAs keep it `display: none`.

The pinned WebKit [fixed-container sampling implementation](https://github.com/WebKit/WebKit/blob/d620932d8ce37cf83f60d5c50dace2d50fed4f80/Source/WebCore/page/LocalFrameView.cpp#L2088) looks for fixed/sticky elements near the viewport edge, covering at least 90% of its width. A primary background must exceed the 10px thin-border threshold and must not be hidden or nearly transparent. Sampling can ignore `pointer-events`. Nanobot's relative/absolute header and small button backgrounds do not provide that full-width surface. This supports the candidate mechanism; it does not prove which WebKit revision ships on an affected device or establish the reported root cause. The CSS capability check is not an iOS version check: older compatible standalone WebKit engines also receive the surface.

The surface is 11px high, viewport-fixed, full-width, and above the application layers. It inherits the body's background color, including startup and live theme changes. Clipping that background to empty text prevents it from painting over controls while retaining the background style for WebKit's sampler. It has no focusable content and cannot intercept taps. It does not add padding, move the header, change viewport fitting, or animate an artificial overlay.

This is a compatibility workaround, **not a supported Apple status-bar API**. First-person device experiments describing the same mechanism:

- [Empty-text fixed surface on iOS 27](https://qiita.com/na-trium-144/items/0add98a80ca2391e3f17)
- [iOS PWA blur experiments, CSS-only update](https://tips.ojapp.app/en/ios-27-pwa-top-blur-workaround-2/)

Keep `viewport-fit=auto` and the existing status-bar metadata. Do not replace this with a guessed safe-area inset or claim that a desktop screenshot verifies iOS system compositing.

## What the evidence establishes

| Evidence | Establishes | Does not establish |
| --- | --- | --- |
| Pinned WebKit source | A fixed surface can satisfy edge-sampling checks, including the >10px background threshold | The exact device build uses the same algorithm or removes its system blur |
| External device experiments | This workaround has worked in other installed PWAs | It fixes nanobot on the reporter's device |
| DOM/CSS contract tests | The surface is empty, outside the React root, conditionally enabled, and retains its sampling styles | Browser layout, hit testing, or system compositing |
| Desktop browser probe with platform conditions bypassed | Layout, paint, click-through and theme behavior under the tested conditions | Native iOS capability detection or standalone-shell rendering |

Do not make the surface invisible with `opacity: 0`, `visibility: hidden`, or a transparent background: those remove the background the sampler is intended to find. Empty-text clipping keeps the background style without painting a strip.

## Device acceptance gate

HTML/CSS contract tests and desktop layout checks verify scoping, color inheritance, non-interference and safe-area preservation. They cannot prove the reported iOS system blur is gone. Before marking the issue resolved, record the actual device, full iOS version, nanobot commit and served frontend asset version, then compare the same device before/after. Confirm the pre-fix version reproduces the issue:

1. Completely quit and relaunch the installed PWA; verify the latest HTML is served.
2. Check sidebar/theme controls on new and existing chats, before and after scrolling and switching chats. A related [WebKit navigation regression](https://bugs.webkit.org/show_bug.cgi?id=305546) shows why a correct first frame is not sufficient; it is not confirmation of this report's root cause.
3. Switch light/dark themes, rotate portrait/landscape, and open/close the keyboard.
4. Open and close the sidebar and settings; verify top controls and one-tap navigation.
5. Compare an ordinary Safari tab and, when available, an unaffected older iOS PWA to rule out added space, painted strips, blocked input or zoom regressions.

Record results as **pass**, **fail**, or **not tested**, with before/after screenshots. If the old build does not reproduce, report that explicitly rather than attributing the absence of blur to this patch. Do not clear site data or reinstall the PWA just to obtain fresh assets; preserve user preferences and local state.

If the workaround stops matching WebKit behavior, re-check the upstream sampling implementation and device results rather than increasing padding or layer sizes. The separately reported portrait `@` selection failure is not addressed here.
