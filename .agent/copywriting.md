# Writing interface copy

Read this when writing or revising user-facing labels, descriptions, buttons, hints, errors, or localized strings. Follow the task's explicit scope and language requirements.

## Keep copy work within scope

A request to rewrite existing copy authorizes replacing existing string values. It does not authorize new locale keys, new explanations, exposing previously hidden help, or changing components, styles, layout, accessibility behavior, or runtime behavior. Keep those changes out of a copy-only PR unless separately requested.

Read the owning code and nearby copy before renaming a feature. Preserve what the feature does, when it applies, and the consequences of the action. Ask about unresolved meaning before changing the affected copy; continue with independently understood strings.

## Make the next action clear

Use [Steve Krug's *Don't Make Me Think* principles](https://ptgmedia.pearsoncmg.com/imprint_downloads/peachpit/peachpit/promo/Dont_Make_Me_Tipsheet.pdf): people scan interfaces, so a label should make its purpose evident without a tutorial. Prefer familiar words, concrete nouns for features, and verbs that name the action for buttons.

Apply [Robin Williams's *The Non-Designer's Design Book* principles](https://www.peachpit.com/content/images/9780133966152/samplepages/9780133966152.pdf) to wording: repeat the same name for the same concept, use parallel phrasing for equivalent controls, keep related explanations together, and distinguish names, summaries, and detailed rules. These principles guide copy decisions; they do not expand permission to redesign the UI.

- Keep the established product voice calm and direct. Remove filler, internal implementation language, and clever expressions that obscure the action.
- Preserve familiar technical terms and product names such as API, MCP, SSH, OAuth, and model names. Do not invent translations just to shorten them.
- For Chinese, target 2–4 character feature names and introductory descriptions of at most 20 characters. Preserve technical names and necessary units even when they exceed the name target. Use natural, concise phrasing in other languages rather than applying Chinese character limits.
- Shortening must preserve conditions, limits, defaults, units, permission boundaries, and destructive consequences. A short label must not imply broader capabilities or weaker restrictions.
- Keep existing detailed rules in their existing description or help strings. When the task permits separating them, use those existing locations or a separate column in the review table; do not add UI or duplicate the original description merely to achieve a short summary.
- Match visible labels, tooltips, confirmations, and accessible names where they describe the same action. Errors should state a supported recovery step; do not invent actions the product cannot perform.

## Complete localization together

Unless the task explicitly limits languages, review every supported locale for each changed copy key in the same change. Keep already-clear translations when appropriate; do not use English fallback as a substitute for completing the localized copy.

For WebUI, use [`supportedLocales`](../webui/src/i18n/config.ts) as the locale inventory. Check both `webui/src/i18n/locales/<locale>/common.json` and channel-owned `nanobot/channels/<channel>/webui/locales/<locale>.json`; common bundles do not contain all interface text. Inspect the owning client for other copy surfaces.

Preserve locale keys, interpolation variables and their occurrences, formatting tokens, configuration values, command identifiers, and preset prompts. Prompts that are sent to the model affect behavior and are not ordinary interface copy. Keep intentionally localized display names and existing optional-key conventions.

## Verify the final change

- Review an original-copy → new-copy table. List existing detailed rules separately when useful, and identify any unresolved meaning instead of guessing.
- Compare against the PR base: a copy-only change should contain existing string replacements and necessary updates to existing test selectors or copy assertions. Confirm that no locale keys or UI behavior were added or removed.
- Check the supported locale inventory, key structure, interpolation occurrences, and preserved prompts. Review semantics as well as structural parity.
- Update tests that look for changed labels without weakening their behavior assertions or changing unrelated fixture text. Run the relevant existing localization and interface tests, lint, and build checks for the affected surface. Follow [test selection guidance](simplify.md) and [verification evidence guidance](workflow.md); do not add tests solely to prove that words changed.
