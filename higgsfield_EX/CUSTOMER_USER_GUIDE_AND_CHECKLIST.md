# StudioRelay — Quick Start and Customer Checklist

StudioRelay is a Chrome extension workspace for Dola video generation. It brings prompts, account profiles, settings, and activity into one compact interface.

## 1. Install the extension

1. Download and extract the StudioRelay package.
2. Open `chrome://extensions/` in Chrome.
3. Enable **Developer mode**.
4. Select **Load unpacked**.
5. Choose the extracted StudioRelay folder.
6. Pin **StudioRelay** from Chrome's extensions menu.
7. Use **Join WhatsApp Channel** in the popup header to open the official channel in a new tab.

## 2. Activate the license

1. Open StudioRelay from the toolbar.
2. Wait for the **Device ID** to appear.
3. Select **Copy device ID** and send it to your administrator.
4. Paste the license key you receive into the **License key** field.
5. Select **Activate license**.

Existing keys continue to use the `CTB-VIP-XXXX-XXXX-XXXX-XXXX` format for compatibility.

If activation fails:

- Confirm that the complete key was pasted without extra spaces.
- Confirm that the key was generated for the Device ID shown on this computer.
- Contact your administrator if the browser, operating system, or hardware profile has changed.

## 3. Dola page status

The side panel **Studio** tab is intentionally disabled. **Prompts** is the default page.

After you run or switch an account, the page-level session badge displays:

**Dola 30s by Kartar**

When the generation enhancement is active beside **Create Video**, its status displays:

**30s (Kartar Mode)**

Each opened account profile spawns 2 simultaneous tabs (to consume 4 points across 2 videos). Generated video cards use the **Fetch & Download done** label in the StudioRelay Graphite + Indigo style.

## 4. Prompts

### Add prompts

- Paste one prompt per line into **Quick add**, then select **Add to prompt list**.
- Or select **Upload** to import a `.csv` or `.txt` file.

### Manage prompts

- Use search to find a prompt.
- Filter the list by **All**, **Queued**, or **Done**.
- Select a prompt number or its text to work with that prompt.
- Use **Paste** to send it to the active Dola page.
- Toggle its completion state as work progresses.
- Use **Reset** to return completed prompts to the queued state.
- Use **Clear** to remove the full list after confirmation.

## 5. Accounts

Only import or manage accounts and session data that you are authorized to use.

### Add accounts

- Select **Upload** for JSON, TXT, Netscape, or CSV cookie files.
- Select **Capture** to save the account signed in on the active supported tab.
- Or enter an optional account name, paste supported cookie data, and select **Import account**.

### Manage accounts

- Search by account name.
- Open an account (spawns 2 tabs for that profile).
- Switch the active account.
- Remove an individual account.
- Use **Clear** to remove all saved accounts after confirmation.

The account chip in the side panel header identifies the active profile. On the Dola page, the session badge uses the **Dola 30s by Kartar** label.

## 6. Settings

The **Settings** tab includes:

- Default video duration.
- Automatic account rotation at the daily limit.
- Automatic advance after sending a prompt.
- Automatic download for completed videos.
- Prompt compatibility cleanup.

Changes are saved automatically.

## 7. Activity

The **Activity** tab summarizes extension readiness, license state, and account workspace status.

## Customer handoff checklist

- [ ] Extension folder extracted.
- [ ] Developer mode enabled.
- [ ] Extension loaded unpacked.
- [ ] StudioRelay pinned to the toolbar.
- [ ] Device ID copied correctly.
- [ ] License key activated.
- [ ] Opens directly in Chrome's Right Side Panel.
- [ ] Prompts opens as the default side panel page; Studio is not visible.
- [ ] Prompt add, search, filter, paste, and progress controls work.
- [ ] Authorized account import or capture works.
- [ ] Opening 1 account profile spawns 2 isolated tabs.
- [ ] Account run/switch shows **Dola 30s by Kartar**.
- [ ] Create Video shows **30s (Kartar Mode)** in violet.
- [ ] Generated video cards show **Fetch & Download done** in the current theme.
- [ ] Confirmation overlay appears before destructive actions.
- [ ] No horizontal clipping is visible in the side panel.

## Troubleshooting

### The popup remains on the activation screen

Reload the extension from `chrome://extensions/`, reopen it, and verify the license key for the displayed Device ID.

### StudioRelay cannot find the active page

Open a supported Dola page first, then retry the action from the popup.

### Imported prompts or accounts do not appear

Check the accepted file type and confirm that the source content is not empty.

### Changes are not visible after an update

Use the reload button on the StudioRelay extension card, then close and reopen the popup.
