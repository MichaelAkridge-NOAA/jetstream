## 2025-05-11 - [Accessibility for Icon-Only Buttons and Presets in TUI]
**Learning:** In Textual-based TUIs, icon-only buttons (like calendar 📅 or navigation arrows ◄/►) lack text context for screen readers and can be ambiguous for new users. Additionally, "preset" buttons often mask complex logic.
**Action:** Use the `tooltip` attribute on Textual `Button` widgets to provide descriptive text for icon-only elements and to disclose the specific configuration (e.g., file patterns) associated with preset buttons, ensuring a more transparent and accessible user experience.
