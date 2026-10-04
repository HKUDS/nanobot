# Sidebar touch interaction

Sidebar hover effects now require a primary pointer that supports hover. This
includes ordinary hover and the named tab/pane group-hover action controls.
Touch users can select a chat without first revealing its hover controls;
keyboard focus, active/open menu state, and existing context menus remain intact.

This is a scoped touch fix. It does not change `viewport-fit=auto`, theme bootstrap,
safe-area padding, draft storage, keyboard Enter behavior, or the service worker.
Apple startup images and network-delayed cold starts require separate work; a
splash image cannot shorten a service-worker navigation waiting on the network.
The earlier startup asset generator is not part of this change, so no `sharp`
dependency or package-lock change is required.

Automated checks cover emitted CSS media gates and existing sidebar interaction
tests. Actual iOS Safari/PWA tap synthesis should still be checked on a device;
desktop browser and synthetic event tests are not a substitute for that check.
